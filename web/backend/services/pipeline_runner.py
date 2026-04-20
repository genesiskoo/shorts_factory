"""기존 agents 래핑 + 스텝별 실행 + 개별 재생성.

원칙: pipeline.py / agents/* / core/* / scripts/* 수정 금지.
checkpoint 파일 존재 시 load_or_run이 재실행 스킵.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

import config  # noqa: F401 — sys.path 삽입 side effect
from config import PROJECT_ROOT
from db import Task, TaskStatus, TaskStep, engine

from core.checkpoint import load_or_run, save_json  # noqa: E402
from core.schema_migrate import (  # noqa: E402
    SCHEMA_VERSION,
    migrate_scripts_final_v1_to_v2,
    migrate_strategy_v1_to_v2,
)
from agents import (  # noqa: E402
    product_analyzer,
    pd_strategist,
    storyboard_designer,
    hook_writer,
    scriptwriter,
    scene_writer,
    script_reviewer,
    tts_generator,
    video_generator,
)

# SHORTS_USE_LEGACY_AGENTS=1 → 기존 pd_strategist/scriptwriter 사용 (rollback hatch).
_USE_LEGACY = os.getenv("SHORTS_USE_LEGACY_AGENTS", "").strip() in ("1", "true", "yes")
_strategy_agent = pd_strategist if _USE_LEGACY else storyboard_designer
_script_agent = scriptwriter if _USE_LEGACY else scene_writer

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
from services import typecast_tts  # noqa: E402
from services.capcut_tail import maybe_append_campaign_tail  # noqa: E402

logger = logging.getLogger("web.pipeline_runner")

# Veo preview는 동시 요청 429 유발 → 모든 video_generator 호출을 직렬화
_VIDEO_SEMAPHORE = threading.Semaphore(1)

MAX_SCRIPT_RETRIES = 2
DEFAULT_TARGET_CHAR_COUNT = 250

# scripts/capcut_builder.py:16 — 원본 저장 경로 (수정 금지, 참조만)
_CAPCUT_SYSTEM_PROJECTS = (
    Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
)

SCRIPT_STAGE_ORDER = [
    "product_analyzer",
    "pd_strategist", "storyboard_designer",
    "hook_writer",
    "scriptwriter", "scene_writer",
    "script_reviewer",
]


# ---------------------------------------------------------------------------
# Storyboard 정규화. scenes[]가 source of truth, clips[]는 video_generator/
# capcut_builder가 참조하는 호환용 mirror. mirror는 매 normalize마다 재생성되어
# stale 위험 없음. 외부 코드는 clips[]를 직접 수정하지 말 것.
# ---------------------------------------------------------------------------

def _normalize_storyboard(strategy: dict, image_count: int) -> int:
    """변경 단위 수 반환. v1 입력은 우선 v2로 마이그레이션."""
    if image_count <= 0:
        return 0
    migrate_strategy_v1_to_v2(strategy)

    all_imgs = [f"img_{i + 1}" for i in range(image_count)]
    mutated = 0

    for var in strategy.get("variants", []):
        scenes = var.get("scenes", []) or []
        if len(scenes) > image_count:
            scenes = scenes[:image_count]
            mutated += 1

        used: set[str] = set()
        for s in scenes:
            src = s.get("source_image")
            if src not in all_imgs or src in used:
                for img in all_imgs:
                    if img not in used:
                        s["source_image"] = img
                        used.add(img)
                        mutated += 1
                        break
            else:
                used.add(src)

        for i, s in enumerate(scenes):
            s["scene_num"] = i + 1
            s.setdefault("timeline", "middle")
            s.setdefault("expected_duration_sec", 7)
            s.setdefault("i2v_prompt_baseline", s.get("i2v_prompt", ""))

        var["scenes"] = scenes

        # video_generator/capcut_builder가 참조하는 clips[] mirror
        var["clips"] = [
            {
                "clip_num": s["scene_num"],
                "source_image": s["source_image"],
                "i2v_prompt": s.get("i2v_prompt_refined")
                or s.get("i2v_prompt_baseline", ""),
                "timeline": s.get("timeline", "middle"),
                "scene": s.get("scene_intent", ""),
            }
            for s in scenes
        ]

        if len(scenes) < image_count:
            logger.warning(
                "variant %s: scene 부족 (%d/%d) — storyboard_designer LLM 이슈",
                var.get("variant_id"), len(scenes), image_count,
            )

    strategy.setdefault("schema_version", SCHEMA_VERSION)
    strategy.setdefault("image_count", image_count)
    return mutated


def _apply_refined_prompts(strategy: dict, scripts_final: dict) -> int:
    """scripts_final의 scene refined prompt를 strategy.clips[].i2v_prompt에 반영.

    video_generator는 strategy.clips[].i2v_prompt만 보므로, refined가 반영되어야
    영상이 대본 톤을 따른다. 갱신된 clip 개수 반환.
    """
    refined_map: dict[tuple[str, int], str] = {}
    for sc in scripts_final.get("scripts", []) or []:
        vid = sc.get("variant_id")
        for s in sc.get("scenes", []) or []:
            refined = s.get("i2v_prompt_refined")
            if refined and vid is not None:
                refined_map[(vid, s.get("scene_num"))] = refined

    if not refined_map:
        return 0

    updated = 0
    for var in strategy.get("variants", []):
        vid = var.get("variant_id")
        for s in var.get("scenes", []) or []:
            key = (vid, s.get("scene_num"))
            if key in refined_map:
                s["i2v_prompt_refined"] = refined_map[key]
        for c in var.get("clips", []) or []:
            key = (vid, c.get("clip_num"))
            if key in refined_map:
                c["i2v_prompt"] = refined_map[key]
                updated += 1
    return updated


# 기존 호출 호환성을 위한 alias (다른 곳에서 _normalize_strategy를 import할 가능성)
_normalize_strategy = _normalize_storyboard


def _materialize_canonical_clips(result: dict, output_dir: str) -> int:
    """video_generator 캐시 safety net.

    video_generator가 (source_image, i2v_prompt) 중복을 캐시 재사용으로
    처리해 result[clip_key]가 다른 파일을 가리킬 때, canonical 경로
    (clips/clip_{variant_id}_{clip_num}.mp4)에 실제 파일이 없으면 복사해
    capcut_builder가 정상 참조하도록 한다. _normalize_strategy가 중복을
    제거하면 이 함수는 노옵.
    """
    clips_dir = Path(output_dir) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    for clip_key, src in (result or {}).items():
        if not src:
            continue
        dst = clips_dir / f"{clip_key}.mp4"
        if dst.exists():
            continue
        src_path = Path(src)
        try:
            if src_path.exists() and src_path.resolve() != dst.resolve():
                shutil.copy2(src_path, dst)
                created += 1
                logger.warning(
                    "materialize: %s (duplicate of %s)", dst.name, src_path.name,
                )
        except (OSError, ValueError) as e:
            logger.warning("materialize skip %s: %s", clip_key, e)
    return created


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


def _start_stage(task_id: int, sub_agent: str, message: str | None = None) -> None:
    _update(
        task_id,
        status=TaskStatus.running,
        sub_agent=sub_agent,
        sub_started_at=datetime.utcnow(),
        progress_message=message or f"[{sub_agent}] 시작",
    )


def _set_progress_message(task_id: int, message: str) -> None:
    """sub_agent 진행 중 세부 메시지 DB 갱신. 200자에서 자른다 (DB 컬럼 한도)."""
    _update(task_id, progress_message=message[:200])


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
        progress_message=f"실패: {err[:120]}",
    )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _build_promotion(task: Task) -> dict | None:
    """campaign_variant ≠ 'none' + sale_price 채워졌을 때 promotion dict 반환.

    schema_designer/scene_writer가 v6_promotion variant를 추가 생성하기 위한
    조건부 입력. 둘 중 하나라도 빠지면 None → 기존 5개 variant만 생성.
    """
    campaign = (task.campaign_variant or "").strip().lower()
    if not campaign or campaign == "none":
        return None
    if not task.sale_price or not task.original_price:
        return None
    discount_rate = max(
        0,
        round((task.original_price - task.sale_price) / task.original_price * 100),
    )
    return {
        "campaign": campaign,
        "original_price": task.original_price,
        "sale_price": task.sale_price,
        "discount_rate": discount_rate,
    }


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
        _update(task_id, output_dir=out, current_step=TaskStep.generating_script)

        images = _resolved_images(task)

        _start_stage(task_id, "product_analyzer", "[product_analyzer] 상품 이미지·정보 분석 중")
        profile = load_or_run(
            f"{out}/product_profile.json",
            product_analyzer.run,
            task.product_name, images,
            task.price_info, task.detail_text, task.seller_memo,
        )
        _set_progress_message(task_id, "[product_analyzer] 프로필 생성 완료")

        promotion = _build_promotion(task)
        n_variants = 6 if promotion else 5
        _start_stage(
            task_id, _strategy_agent.__name__,
            f"[{_strategy_agent.__name__}] {n_variants}개 소구 스토리보드 설계 중"
            + (" (+v6_promotion)" if promotion else ""),
        )
        image_count = len(images)
        strategy_kwargs: dict = {"image_count": image_count}
        # legacy pd_strategist는 promotion 미지원 → kwargs 추가 시 TypeError 방지
        if promotion and _strategy_agent.__name__ == "storyboard_designer":
            strategy_kwargs["promotion"] = promotion
        strategy = load_or_run(
            f"{out}/strategy.json",
            _strategy_agent.run,
            profile, images,
            **strategy_kwargs,
        )
        mutated = _normalize_storyboard(strategy, image_count)
        if mutated:
            logger.info(
                "task %d: storyboard normalized (%d unit(s) 수정, image_count=%d)",
                task_id, mutated, image_count,
            )
        _set_progress_message(
            task_id,
            f"[{_strategy_agent.__name__}] 5개 스토리보드 완성 ({image_count}장/소구)",
        )
        # 첫 save는 retry 루프 종료 후 refined 적용 결과까지 한 번에 영속화.

        scripts_final: dict | None = None
        prev_feedback: list = []
        target_char_count = task.target_char_count or DEFAULT_TARGET_CHAR_COUNT

        for attempt in range(MAX_SCRIPT_RETRIES + 1):
            suffix = f"_v{attempt}" if attempt > 0 else ""
            attempt_label = "" if attempt == 0 else f" (재시도 {attempt}/{MAX_SCRIPT_RETRIES})"

            _start_stage(task_id, "hook_writer", f"[hook_writer] 5개 훅 작성 중{attempt_label}")
            hooks = load_or_run(
                f"{out}/hooks{suffix}.json",
                hook_writer.run, strategy, profile,
            )
            _set_progress_message(task_id, f"[hook_writer] 훅 완성{attempt_label}")

            _start_stage(
                task_id, _script_agent.__name__,
                f"[{_script_agent.__name__}] Scene별 대본 작성 중{attempt_label}",
            )
            scripts = load_or_run(
                f"{out}/scripts{suffix}.json",
                _script_agent.run, hooks, strategy, profile,
                review_feedback=prev_feedback if attempt > 0 else None,
                target_char_count=target_char_count,
            )
            n_scripts = len(scripts.get("scripts", []))
            _set_progress_message(
                task_id,
                f"[{_script_agent.__name__}] {n_scripts}개 대본 완성{attempt_label}",
            )

            _start_stage(task_id, "script_reviewer", f"[script_reviewer] 검수 중{attempt_label}")
            review_result = script_reviewer.run(
                scripts, profile, target_char_count=target_char_count,
            )

            if review_result.get("all_passed") or attempt == MAX_SCRIPT_RETRIES:
                scripts_final = {
                    "schema_version": SCHEMA_VERSION,
                    "scripts": review_result.get(
                        "scripts", scripts.get("scripts", [])
                    ),
                }
                migrate_scripts_final_v1_to_v2(scripts_final)
                save_json(f"{out}/scripts_final.json", scripts_final)

                applied = _apply_refined_prompts(strategy, scripts_final)
                if applied:
                    logger.info(
                        "task %d: %d clip prompt(s) updated with refined prompts",
                        task_id, applied,
                    )
                save_json(f"{out}/strategy.json", strategy)
                break
            prev_feedback = review_result.get("feedback", [])

        n_final = len(scripts_final.get("scripts", [])) if scripts_final else 0
        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step=TaskStep.select_scripts,
            progress_message=f"대본 생성 완료: {n_final}개 변형 선택 대기",
        )
        logger.info("task %d: script generation complete", task_id)

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")


def _build_typecast_context(strategy: dict, variant_id: str) -> dict:
    """strategy.json에서 해당 variant의 target_emotion/direction을
    Typecast Smart Emotion의 previous_text로 조립. 없으면 빈 dict.
    """
    for v in strategy.get("variants", []):
        if v.get("variant_id") != variant_id:
            continue
        parts = []
        if v.get("target_emotion"):
            parts.append(str(v["target_emotion"]))
        if v.get("direction"):
            parts.append(str(v["direction"]))
        if parts:
            return {"previous_text": " ".join(parts)[:200]}
        return {}
    return {}


def _dispatch_tts(task: Task, filtered: dict, out: str) -> None:
    """task.tts_provider 기준으로 ElevenLabs/Typecast 분기.

    tts_provider가 None 또는 'elevenlabs'면 기존 경로 유지.
    'typecast'면 web/backend/services/typecast_tts.py 사용 + Smart Emotion
    자동 주입(per-variant `target_emotion`/`direction` → previous_text).
    """
    provider = (task.tts_provider or "elevenlabs").lower()
    if provider == "typecast":
        try:
            options = json.loads(task.tts_options or "{}")
        except json.JSONDecodeError:
            options = {}
        try:
            strategy = _load_json(Path(out) / "strategy.json")
        except FileNotFoundError:
            strategy = {"variants": []}
        per_ctx = {
            s["variant_id"]: _build_typecast_context(strategy, s["variant_id"])
            for s in filtered.get("scripts", [])
            if s.get("variant_id")
        }
        typecast_tts.run(filtered, out, options, per_ctx)
    else:
        tts_generator.run(filtered, out)


def run_tts_generation(task_id: int, selected_variant_ids: list[str]) -> None:
    """⑥ TTS 생성. provider는 task.tts_provider 기준 분기.
    selected variant만 scripts_final에서 필터링 후 호출."""
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
            current_step=TaskStep.generating_tts,
        )
        provider_tag = (task.tts_provider or "elevenlabs").lower()
        _start_stage(
            task_id,
            "typecast_tts" if provider_tag == "typecast" else "tts_generator",
            f"[{provider_tag}_tts] {len(filtered['scripts'])}개 변형 음성 합성 중",
        )

        _dispatch_tts(task, filtered, out)

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step=TaskStep.review_tts,
            progress_message=f"[{provider_tag}_tts] {len(filtered['scripts'])}개 음성 합성 완료",
        )
        logger.info("task %d: tts generation complete (provider=%s)", task_id, provider_tag)

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
        scripts_final_path = Path(out) / "scripts_final.json"
        if scripts_final_path.exists():
            scripts_final = _load_json(scripts_final_path)
            migrate_scripts_final_v1_to_v2(scripts_final)
            _apply_refined_prompts(strategy, scripts_final)

        images = _resolved_images(task)
        image_map = {f"img_{i+1}": p for i, p in enumerate(images)}

        _normalize_storyboard(strategy, len(images))

        # regenerate_clip이 baseline이 아닌 refined 값을 다시 읽도록 보장.
        save_json(f"{out}/strategy.json", strategy)

        strategy_filtered = {
            **strategy,
            "variants": [
                v for v in strategy.get("variants", [])
                if v.get("variant_id") in selected
            ],
        }

        _update(task_id, current_step=TaskStep.generating_video)
        n_total_clips = sum(
            len(v.get("scenes") or v.get("clips") or [])
            for v in strategy_filtered.get("variants", [])
        )
        _start_stage(
            task_id, "video_generator",
            f"[video_generator] Veo로 {n_total_clips}개 클립 생성 중 (5~15분 소요)",
        )

        from services.i2v_models import normalize_chain
        models_chain = normalize_chain(task.i2v_model)
        logger.info("task %d: i2v models chain = %s", task_id, models_chain)

        with _VIDEO_SEMAPHORE:
            result = video_generator.run(
                strategy_filtered, images, image_map, out,
                models=models_chain,
            )

        # safety net: strategy 내 중복이 혹시 남아있으면 canonical 파일 보장
        created = _materialize_canonical_clips(result, out)
        if created:
            logger.info(
                "task %d: materialized %d canonical clip file(s) from cache",
                task_id, created,
            )

        # video_generator는 예외 대신 result[clip_key] is None으로 실패를 표시.
        # 부분 성공도 select_clips로 진입시켜 사용자가 실패 클립만 재생성하도록.
        total = len(result)
        failed_keys = [k for k, v in result.items() if v is None]
        failed_count = len(failed_keys)

        # 성공한 클립을 clip_sources.json에 veo 출처로 기록 (사용자 업로드와 구분)
        from services import clip_sources as _cs
        primary_model = models_chain[0] if models_chain else "unknown"
        for clip_key, mp4 in result.items():
            if not mp4:
                continue
            # clip_key 패턴: clip_{variant_id}_{clip_num}
            m = clip_key.removeprefix("clip_")
            parts = m.rsplit("_", 1)
            if len(parts) == 2:
                vid, num_s = parts
                try:
                    _cs.mark_veo(out, vid, int(num_s), primary_model)
                except (ValueError, OSError):
                    pass

        if total == 0 or failed_count == total:
            raise RuntimeError(
                f"video generation produced no clips (0/{total} succeeded)"
            )

        partial_error = None
        if failed_count:
            partial_error = (
                f"{failed_count}/{total} clips failed "
                f"(Veo 429 또는 생성 실패 — select_clips에서 개별 재생성 가능)"
            )
            logger.warning("task %d: video partial failure — %s", task_id, partial_error)

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step=TaskStep.select_clips,
            error=partial_error,
            progress_message=(
                f"[video_generator] {total - failed_count}/{total} 클립 생성 완료"
                + (f" — {failed_count}개 실패 (재생성 필요)" if failed_count else "")
            ),
        )
        logger.info(
            "task %d: video generation complete (%d/%d ok)",
            task_id, total - failed_count, total,
        )

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
        migrate_scripts_final_v1_to_v2(scripts)
        images = _resolved_images(task)
        _normalize_storyboard(strategy, len(images))

        filtered_variants = []
        for v in strategy.get("variants", []):
            vid = v.get("variant_id")
            if vid not in selected_vids:
                continue
            keep_nums = set(selected_clips.get(vid, []))
            if keep_nums:
                v = {
                    **v,
                    "scenes": [
                        s for s in v.get("scenes", []) or []
                        if s.get("scene_num") in keep_nums
                    ],
                    "clips": [
                        c for c in v.get("clips", []) or []
                        if c.get("clip_num") in keep_nums
                    ],
                }
            filtered_variants.append(v)
        strategy_filtered = {**strategy, "variants": filtered_variants}

        # scripts_filtered에 product_name 명시적 주입 — capcut_builder가 프로젝트
        # 폴더명을 `{product_name}_{variant_id}`로 구성하는 근거.
        scripts_filtered = {
            "product_name": task.product_name,
            "scripts": [
                s for s in scripts.get("scripts", [])
                if s.get("variant_id") in selected_vids
            ],
        }

        _update(
            task_id,
            current_step=TaskStep.building_capcut,
            template_assignments=json.dumps(
                template_assignments or {}, ensure_ascii=False
            ),
            campaign_variant=campaign_variant or task.campaign_variant,
        )
        _start_stage(
            task_id, "capcut_builder",
            f"[capcut_builder] {len(selected_vids)}개 CapCut 프로젝트 빌드 중",
        )

        capcut_builder.run(
            audio_dir=f"{out}/audio",
            clips_dir=f"{out}/clips",
            scripts=scripts_filtered,
            strategy=strategy_filtered,
            output_dir=f"{out}/capcut_drafts",
        )

        # scripts/capcut_builder.py::build_capcut_project 는 CAPCUT_PROJECTS 시스템
        # 경로에만 저장하고 output_dir 인자를 무시 → 웹 다운로드용으로 mirror.
        # project_name이 `{product_name}_{variant_id}`로 바뀌었으므로 src 경로도 동기화.
        from agents.capcut_builder import _build_project_name  # type: ignore
        drafts_out = Path(out) / "capcut_drafts"
        drafts_out.mkdir(parents=True, exist_ok=True)
        copied = []
        tail_applied = 0
        for vid in selected_vids:
            project_name = _build_project_name(task.product_name, vid)
            src = _CAPCUT_SYSTEM_PROJECTS / project_name

            # campaign_variant tail mp4 append (system 경로에서 먼저 후처리 → mirror가 복제)
            if maybe_append_campaign_tail(src, task.campaign_variant):
                tail_applied += 1

            # 다운로드 zip 식별은 여전히 variant_id 기준 유지 (routes/files.py 호환)
            dst = drafts_out / vid
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                copied.append(vid)
            else:
                logger.warning(
                    "capcut mirror skip: source missing %s", src,
                )
        if tail_applied:
            logger.info(
                "task %d: campaign tail applied to %d/%d projects (variant=%s)",
                task_id, tail_applied, len(selected_vids), task.campaign_variant,
            )
        logger.info(
            "task %d: capcut mirrored %d/%d variants",
            task_id, len(copied), len(selected_vids),
        )

        _clear_stage(
            task_id,
            status=TaskStatus.completed,
            current_step=TaskStep.completed,
            completed_at=datetime.utcnow(),
            progress_message=f"[capcut_builder] {len(copied)}개 프로젝트 빌드 완료",
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

        _update(task_id, current_step=TaskStep.select_scripts)
        _start_stage(task_id, "hook_writer", f"[hook_writer] {variant_id} 재생성 (훅)")
        hooks = load_or_run(
            str(out / "hooks.json"),
            hook_writer.run, strategy, profile,
        )

        _start_stage(
            task_id, _script_agent.__name__,
            f"[{_script_agent.__name__}] {variant_id} 재생성 (대본)",
        )
        scripts = load_or_run(
            str(out / "scripts.json"),
            _script_agent.run, hooks, strategy, profile,
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
            current_step=TaskStep.select_scripts,
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

        _update(task_id, current_step=TaskStep.review_tts)
        provider_tag = (task.tts_provider or "elevenlabs").lower()
        _start_stage(
            task_id,
            "typecast_tts" if provider_tag == "typecast" else "tts_generator",
            f"[{provider_tag}_tts] {variant_id} 재생성 (음성)",
        )

        _dispatch_tts(task, filtered, str(out))

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step=TaskStep.review_tts,
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
        images = _resolved_images(task)
        # v2 task: scenes의 refined prompt가 clips mirror에 항상 반영되도록.
        scripts_final_path = out / "scripts_final.json"
        if scripts_final_path.exists():
            scripts_final = _load_json_file(scripts_final_path)
            migrate_scripts_final_v1_to_v2(scripts_final)
            _apply_refined_prompts(strategy, scripts_final)
        _normalize_storyboard(strategy, len(images))

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
        image_map = {f"img_{i+1}": p for i, p in enumerate(images)}

        _update(task_id, current_step=TaskStep.select_clips)
        _start_stage(task_id, "video_generator")

        from services.i2v_models import normalize_chain
        models_chain = normalize_chain(task.i2v_model)

        with _VIDEO_SEMAPHORE:
            result = video_generator.run(
                strategy_subset, images, image_map, str(out),
                models=models_chain,
            )

        _materialize_canonical_clips(result, str(out))

        # 재생성 성공 시 출처를 veo로 갱신 (force 덮어쓰기로 user→veo 전환 가능).
        # clip_sources 저장 실패가 task 흐름을 깨뜨리지 않도록 OSError 차단.
        from services import clip_sources as _cs
        primary_model = models_chain[0] if models_chain else "unknown"
        target_key = f"clip_{variant_id}_{clip_num}"
        if result.get(target_key):
            try:
                _cs.mark_veo(str(out), variant_id, clip_num, primary_model)
            except OSError as exc:
                logger.warning(
                    "clip_sources 갱신 실패 (task=%d, %s): %s",
                    task_id, target_key, exc,
                )

        _clear_stage(
            task_id,
            status=TaskStatus.awaiting_user,
            current_step=TaskStep.select_clips,
        )
        logger.info(
            "task %d: clip regeneration complete (variant=%s clip=%d)",
            task_id, variant_id, clip_num,
        )

    except Exception as e:
        _mark_failed(task_id, f"{type(e).__name__}: {e}")
