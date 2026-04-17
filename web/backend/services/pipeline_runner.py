"""기존 agents 래핑 + 스텝별 실행 + 개별 재생성.

원칙: pipeline.py / agents/* / core/* / scripts/* 수정 금지.
checkpoint 파일 존재 시 load_or_run이 재실행 스킵.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

import config  # noqa: F401 — sys.path 삽입 side effect
from config import PROJECT_ROOT
from db import Task, TaskStatus, engine

from core.checkpoint import load_or_run, save_json  # noqa: E402
from agents import (  # noqa: E402
    product_analyzer,
    pd_strategist,
    hook_writer,
    scriptwriter,
    script_reviewer,
    tts_generator,
    video_generator,
)

try:
    from agents import capcut_builder  # noqa: E402
except ImportError:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import capcut_builder  # type: ignore  # noqa: E402

from services.file_ops import (  # noqa: E402
    audio_paths,
    clip_path,
    delete_if_exists,
    invalidate_script_cache,
    load_json as _load_json_file,
    replace_variant_in_scripts,
    save_json as _save_json_file,
)

logger = logging.getLogger("web.pipeline_runner")

# Veo preview는 동시 요청 429 유발 → 모든 video_generator 호출을 직렬화
_VIDEO_SEMAPHORE = threading.Semaphore(1)

MAX_SCRIPT_RETRIES = 2

# scripts/capcut_builder.py:16 — 원본 저장 경로 (수정 금지, 참조만)
_CAPCUT_SYSTEM_PROJECTS = (
    Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
)

SCRIPT_STAGE_ORDER = [
    "product_analyzer",
    "pd_strategist",
    "hook_writer",
    "scriptwriter",
    "script_reviewer",
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load_task(task_id: int) -> Task:
    with Session(engine) as s:
        task = s.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        return task


def _update(task_id: int, **fields) -> None:
    with Session(engine) as s:
        task = s.get(Task, task_id)
        if task is None:
            return
        for k, v in fields.items():
            setattr(task, k, v)
        s.add(task)
        s.commit()


def _start_stage(task_id: int, sub_agent: str) -> None:
    _update(
        task_id,
        status=TaskStatus.running,
        sub_agent=sub_agent,
        sub_started_at=datetime.utcnow(),
    )


def _clear_stage(task_id: int, **extra) -> None:
    _update(task_id, sub_agent=None, sub_started_at=None, **extra)


def _mark_failed(task_id: int, err: str) -> None:
    logger.exception("task %d failed: %s", task_id, err)
    _update(
        task_id,
        status=TaskStatus.failed,
        error=err,
        sub_agent=None,
        sub_started_at=None,
    )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _output_dir_for(task: Task) -> str:
    if task.output_dir:
        return str(Path(task.output_dir).resolve())
    return str((PROJECT_ROOT / "output" / task.product_name).resolve())


def _resolved_images(task: Task) -> list[str]:
    return [str(Path(p).resolve()) for p in json.loads(task.images)]


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Main stage wrappers
# ---------------------------------------------------------------------------

def run_script_generation(task_id: int) -> None:
    """①②③④⑤ 순차 실행. 완료 시 awaiting_user / select_scripts."""
    try:
        task = _load_task(task_id)
        out = _output_dir_for(task)
        Path(out).mkdir(parents=True, exist_ok=True)
        _update(task_id, output_dir=out, current_step="generating_script")

        images = _resolved_images(task)

        _start_stage(task_id, "product_analyzer")
        profile = load_or_run(
            f"{out}/product_profile.json",
            product_analyzer.run,
            task.product_name, images,
            task.price_info, task.detail_text, task.seller_memo,
        )

        _start_stage(task_id, "pd_strategist")
        strategy = load_or_run(
            f"{out}/strategy.json",
            pd_strategist.run,
            profile, images,
        )

        scripts_final: dict | None = None
        prev_feedback: list = []

        for attempt in range(MAX_SCRIPT_RETRIES + 1):
            suffix = f"_v{attempt}" if attempt > 0 else ""

            _start_stage(task_id, "hook_writer")
            hooks = load_or_run(
                f"{out}/hooks{suffix}.json",
                hook_writer.run, strategy, profile,
            )

            _start_stage(task_id, "scriptwriter")
            scripts = load_or_run(
                f"{out}/scripts{suffix}.json",
                scriptwriter.run, hooks, strategy, profile,
                review_feedback=prev_feedback if attempt > 0 else None,
            )

            _start_stage(task_id, "script_reviewer")
            review_result = script_reviewer.run(scripts, profile)

            if review_result.get("all_passed") or attempt == MAX_SCRIPT_RETRIES:
                scripts_final = {
                    "scripts": review_result.get(
                        "scripts", scripts.get("scripts", [])
                    )
                }
                save_json(f"{out}/scripts_final.json", scripts_final)
                break
            prev_feedback = review_result.get("feedback", [])

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="select_scripts",
        )
        logger.info("task %d: script generation complete", task_id)

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def run_tts_generation(task_id: int, selected_variant_ids: list[str]) -> None:
    """⑥ tts_generator. selected variant만 scripts_final에서 필터링 후 호출."""
    try:
        task = _load_task(task_id)
        out = _output_dir_for(task)

        scripts_final = _load_json(Path(out) / "scripts_final.json")
        filtered = {
            "scripts": [
                s for s in scripts_final.get("scripts", [])
                if s.get("variant_id") in selected_variant_ids
            ]
        }
        if not filtered["scripts"]:
            raise ValueError(
                f"no scripts match selected_variant_ids={selected_variant_ids}"
            )

        _update(
            task_id,
            selected_variant_ids=json.dumps(
                selected_variant_ids, ensure_ascii=False
            ),
            current_step="generating_tts",
        )
        _start_stage(task_id, "tts_generator")

        tts_generator.run(filtered, out)

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="review_tts",
        )
        logger.info("task %d: tts generation complete", task_id)

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def run_video_generation(task_id: int) -> None:
    """⑦ video_generator. selected variant만 strategy에서 필터링.
    Veo 429 회피를 위해 전역 Semaphore로 직렬화.
    """
    try:
        task = _load_task(task_id)
        out = _output_dir_for(task)
        selected = json.loads(task.selected_variant_ids or "[]")
        if not selected:
            raise ValueError("selected_variant_ids 비어있음")

        strategy = _load_json(Path(out) / "strategy.json")
        strategy_filtered = {
            **strategy,
            "variants": [
                v for v in strategy.get("variants", [])
                if v.get("variant_id") in selected
            ],
        }

        images = _resolved_images(task)
        image_map = {f"img_{i+1}": p for i, p in enumerate(images)}

        _update(task_id, current_step="generating_video")
        _start_stage(task_id, "video_generator")

        with _VIDEO_SEMAPHORE:
            video_generator.run(strategy_filtered, images, image_map, out)

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="select_clips",
        )
        logger.info("task %d: video generation complete", task_id)

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def run_capcut_build(
    task_id: int,
    template_assignments: dict[str, str] | None = None,
    campaign_variant: str | None = None,
) -> None:
    """⑧ capcut_builder. selected_variant_ids + selected_clips로 필터링된
    strategy/scripts dict를 전달해 부분 빌드 달성 (제약 #1)."""
    try:
        task = _load_task(task_id)
        out = _output_dir_for(task)

        selected_vids = json.loads(task.selected_variant_ids or "[]")
        if not selected_vids:
            raise ValueError("selected_variant_ids 비어있음")
        selected_clips = json.loads(task.selected_clips or "{}")

        strategy = _load_json(Path(out) / "strategy.json")
        scripts = _load_json(Path(out) / "scripts_final.json")

        # variants 필터 + 각 variant의 clips 필터
        filtered_variants = []
        for v in strategy.get("variants", []):
            vid = v.get("variant_id")
            if vid not in selected_vids:
                continue
            keep_nums = set(selected_clips.get(vid, []))
            if keep_nums:
                v = {
                    **v,
                    "clips": [
                        c for c in v.get("clips", [])
                        if c.get("clip_num") in keep_nums
                    ],
                }
            filtered_variants.append(v)
        strategy_filtered = {**strategy, "variants": filtered_variants}

        scripts_filtered = {
            "scripts": [
                s for s in scripts.get("scripts", [])
                if s.get("variant_id") in selected_vids
            ]
        }

        _update(
            task_id,
            current_step="building_capcut",
            template_assignments=json.dumps(
                template_assignments or {}, ensure_ascii=False
            ),
            campaign_variant=campaign_variant or task.campaign_variant,
        )
        _start_stage(task_id, "capcut_builder")

        capcut_builder.run(
            audio_dir=f"{out}/audio",
            clips_dir=f"{out}/clips",
            scripts=scripts_filtered,
            strategy=strategy_filtered,
            output_dir=f"{out}/capcut_drafts",
        )

        # scripts/capcut_builder.py::build_capcut_project 는 CAPCUT_PROJECTS 시스템
        # 경로에만 저장하고 output_dir 인자를 무시 → 웹 다운로드용으로 mirror.
        drafts_out = Path(out) / "capcut_drafts"
        drafts_out.mkdir(parents=True, exist_ok=True)
        copied = []
        for vid in selected_vids:
            src = _CAPCUT_SYSTEM_PROJECTS / vid
            dst = drafts_out / vid
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied.append(vid)
            else:
                logger.warning(
                    "capcut mirror skip: source missing %s", src,
                )
        logger.info(
            "task %d: capcut mirrored %d/%d variants",
            task_id, len(copied), len(selected_vids),
        )

        _clear_stage(
            task_id,
            status=TaskStatus.completed,
            current_step="completed",
            completed_at=datetime.utcnow(),
        )
        logger.info("task %d: capcut build complete", task_id)

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 개별 재생성 (제약 #2, #3 전략)
# ---------------------------------------------------------------------------

def regenerate_script_variant(
    task_id: int,
    variant_id: str,
    direction: str | None = None,
) -> None:
    """단일 variant 대본 재생성.

    hook_writer + scriptwriter를 전체 재호출 후 해당 variant만 치환 (옵션 A).
    대본이 바뀌므로 해당 variant의 audio/*도 stale → 삭제해 TTS 재생성 유도.
    script_reviewer는 재호출하지 않음 (단일 variant 검수 인터페이스 부재).
    """
    try:
        task = _load_task(task_id)
        out = Path(_output_dir_for(task))
        scripts_final_path = out / "scripts_final.json"
        if not scripts_final_path.exists():
            raise FileNotFoundError("scripts_final.json not found")

        profile = _load_json_file(out / "product_profile.json")
        strategy = _load_json_file(out / "strategy.json")

        # direction을 feedback 형태로 주입 (scriptwriter 기존 인터페이스 활용)
        feedback: list[dict] = []
        if direction:
            feedback = [{
                "variant_id": variant_id,
                "passed": False,
                "notes": [direction],
            }]

        # 기존 hooks.json/scripts.json 삭제해 load_or_run이 LLM 재호출하도록
        invalidate_script_cache(out)

        _update(task_id, current_step="select_scripts")
        _start_stage(task_id, "hook_writer")
        hooks = load_or_run(
            str(out / "hooks.json"),
            hook_writer.run, strategy, profile,
        )

        _start_stage(task_id, "scriptwriter")
        scripts = load_or_run(
            str(out / "scripts.json"),
            scriptwriter.run, hooks, strategy, profile,
            review_feedback=feedback or None,
        )

        new_entry = next(
            (s for s in scripts.get("scripts", []) if s.get("variant_id") == variant_id),
            None,
        )
        if new_entry is None:
            raise ValueError(f"regenerated scripts missing variant_id={variant_id}")

        replace_variant_in_scripts(scripts_final_path, variant_id, new_entry)

        # 대본이 바뀌었으므로 해당 variant의 TTS는 stale
        mp3, srt = audio_paths(out, variant_id)
        delete_if_exists(mp3)
        delete_if_exists(srt)

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="select_scripts",
        )
        logger.info(
            "task %d: script regeneration complete (variant=%s)",
            task_id, variant_id,
        )

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def regenerate_tts_variant(task_id: int, variant_id: str) -> None:
    """단일 variant TTS 재생성. audio 파일 삭제 후 tts_generator 호출."""
    try:
        task = _load_task(task_id)
        out = Path(_output_dir_for(task))

        scripts_final = _load_json_file(out / "scripts_final.json")
        script = next(
            (s for s in scripts_final.get("scripts", [])
             if s.get("variant_id") == variant_id),
            None,
        )
        if script is None:
            raise ValueError(f"variant_id={variant_id} not in scripts_final")

        # checkpoint 삭제 → run 재호출 시 재생성
        mp3, srt = audio_paths(out, variant_id)
        delete_if_exists(mp3)
        delete_if_exists(srt)

        filtered = {"scripts": [script]}

        _update(task_id, current_step="review_tts")
        _start_stage(task_id, "tts_generator")

        tts_generator.run(filtered, str(out))

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="review_tts",
        )
        logger.info(
            "task %d: tts regeneration complete (variant=%s)",
            task_id, variant_id,
        )

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def regenerate_clip(task_id: int, variant_id: str, clip_num: int) -> None:
    """단일 클립 재생성. 해당 mp4 삭제 후 video_generator에 subset 전달.

    중복 캐시 우회를 위해 strategy를 해당 variant+clip_num 1개로 축소.
    """
    try:
        task = _load_task(task_id)
        out = Path(_output_dir_for(task))

        strategy = _load_json_file(out / "strategy.json")
        variant = next(
            (v for v in strategy.get("variants", [])
             if v.get("variant_id") == variant_id),
            None,
        )
        if variant is None:
            raise ValueError(f"variant_id={variant_id} not in strategy")
        target_clip = next(
            (c for c in variant.get("clips", [])
             if c.get("clip_num") == clip_num),
            None,
        )
        if target_clip is None:
            raise ValueError(
                f"clip_num={clip_num} not in variant {variant_id}"
            )

        delete_if_exists(clip_path(out, variant_id, clip_num))

        strategy_subset = {
            **strategy,
            "variants": [{**variant, "clips": [target_clip]}],
        }
        images = _resolved_images(task)
        image_map = {f"img_{i+1}": p for i, p in enumerate(images)}

        _update(task_id, current_step="select_clips")
        _start_stage(task_id, "video_generator")

        with _VIDEO_SEMAPHORE:
            video_generator.run(strategy_subset, images, image_map, str(out))

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step="select_clips",
        )
        logger.info(
            "task %d: clip regeneration complete (variant=%s clip=%d)",
            task_id, variant_id, clip_num,
        )

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")
