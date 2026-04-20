"""Task CRUD 라우터. Day 2 범위: POST/GET 만. next/regenerate-*는 Day 3."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path  # noqa: F401

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlmodel import Session, select

from config import OUTPUT_DIR, UPLOADS_DIR
from db import Task, TaskStatus, TaskStep, get_session
from schemas import (
    BuildCapcutReq,
    DropVariantReq,
    EditPromptReq,
    EditScriptReq,
    NextStepReq,
    RegenerateClipReq,
    RegenerateScriptReq,
    RegenerateTtsReq,
    SubProgress,
    TaskCreatedResp,
    TaskDetailResp,
    TaskListResp,
    TaskSummary,
    UploadClipResp,
)
from services.pipeline_runner import (
    SCRIPT_STAGE_ORDER,
    regenerate_clip,
    regenerate_script_variant,
    regenerate_tts_variant,
    run_capcut_build,
    run_script_generation,
    run_tts_generation,
    run_video_generation,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CAMPAIGN = {
    "none", "family_month", "children_day", "parents_day", "fast_delivery",
}
ACTIVE_STATUSES = [
    TaskStatus.pending,
    TaskStatus.running,
    TaskStatus.awaiting_user,
]
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# 스크립트 목표 글자수 상수.
# 실제 상한은 task별로 image_count × CHARS_PER_IMAGE_CAP. 아래 전역 값은 폼 검증의
# 절대 경계만 정의하며 3장 업로드 시(≈147 상한) 충돌하지 않도록 MIN을 낮춤.
DEFAULT_TARGET_CHAR_COUNT = 250  # 메타데이터 기본값(개별 task는 image_count 기반 계산)
TARGET_CHAR_COUNT_MIN = 100      # 전역 하한
TARGET_CHAR_COUNT_MAX = 500      # 전역 상한

# 이미지 1장당 클립 1개 규약 기반 상한/기본값 계수.
#   CHARS_PER_IMAGE_CAP: Veo 클립 약 7초 × TTS 약 7자/초 ≈ 49 (하드 상한)
#   CHARS_PER_IMAGE_DEFAULT: 하드 상한의 92% (헤드룸) ≈ 45
CHARS_PER_IMAGE_CAP = 49
CHARS_PER_IMAGE_DEFAULT = 45


def _max_target_for_images(image_count: int) -> int:
    """image_count 기준 target_char_count 상한. 전역 MAX를 넘지 못함."""
    return min(TARGET_CHAR_COUNT_MAX, image_count * CHARS_PER_IMAGE_CAP)


def _default_target_for_images(image_count: int) -> int:
    """image_count 미지정 시 적용할 기본 target_char_count."""
    return min(TARGET_CHAR_COUNT_MAX, image_count * CHARS_PER_IMAGE_DEFAULT)


def _sanitize_filename(name: str) -> str:
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    stem_clean = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:40] or "image"
    if ext not in ALLOWED_IMAGE_EXT:
        ext = ".jpg"
    return f"{stem_clean}{ext}"


def _compute_artifacts(output_dir: str | None) -> dict[str, bool]:
    keys = (
        "product_profile", "strategy", "scripts_final",
        "audio", "clips", "capcut_drafts",
    )
    if not output_dir:
        return {k: False for k in keys}
    d = Path(output_dir)
    return {
        "product_profile": (d / "product_profile.json").exists(),
        "strategy": (d / "strategy.json").exists(),
        "scripts_final": (d / "scripts_final.json").exists(),
        "audio": (d / "audio").exists() and any((d / "audio").glob("*.mp3")),
        "clips": (d / "clips").exists() and any((d / "clips").glob("*.mp4")),
        "capcut_drafts": (d / "capcut_drafts").exists()
            and any((d / "capcut_drafts").iterdir()),
    }


def _to_summary(t: Task) -> TaskSummary:
    return TaskSummary(
        id=t.id,
        product_name=t.product_name,
        status=t.status,
        current_step=t.current_step,
        created_at=t.created_at,
        completed_at=t.completed_at,
        error=t.error,
    )


@router.post("", response_model=TaskCreatedResp, status_code=201)
async def create_task(
    background_tasks: BackgroundTasks,
    product_name: str = Form(...),
    price_info: str | None = Form(None),
    detail_text: str | None = Form(None),
    seller_memo: str | None = Form(None),
    campaign_variant: str | None = Form(None),
    landing_url: str | None = Form(None),
    coupon_info: str | None = Form(None),
    target_char_count: int | None = Form(None),
    original_price: int | None = Form(None),
    sale_price: int | None = Form(None),
    images: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> TaskCreatedResp:
    if len(images) < 3 or len(images) > 5:
        raise HTTPException(400, "이미지는 3~5장이어야 합니다.")

    if campaign_variant and campaign_variant not in ALLOWED_CAMPAIGN:
        raise HTTPException(
            400,
            f"campaign_variant는 {sorted(ALLOWED_CAMPAIGN)} 중 하나여야 합니다.",
        )

    # 가격 검증: 둘 다 양수, sale ≤ original. 한쪽만 입력하면 promotion 비활성화
    # (campaign_variant도 함께 있어야 v6 활성화 — pipeline_runner에서 최종 판정)
    for label, val in (("original_price", original_price), ("sale_price", sale_price)):
        if val is not None and val < 0:
            raise HTTPException(400, f"{label}는 0 이상이어야 합니다.")
    if original_price and sale_price and sale_price > original_price:
        raise HTTPException(
            400, "sale_price는 original_price보다 작거나 같아야 합니다.",
        )

    # 글자수 전역 범위 검증
    if target_char_count is not None and not (
        TARGET_CHAR_COUNT_MIN <= target_char_count <= TARGET_CHAR_COUNT_MAX
    ):
        raise HTTPException(
            400,
            f"target_char_count는 {TARGET_CHAR_COUNT_MIN}~{TARGET_CHAR_COUNT_MAX} 범위여야 합니다.",
        )
    # image_count 기반 per-task 상한 검증(클립 = 이미지 1:1 규약)
    max_for_images = _max_target_for_images(len(images))
    if target_char_count is not None and target_char_count > max_for_images:
        raise HTTPException(
            400,
            f"이미지 {len(images)}장 기준 target_char_count 상한은 {max_for_images}자입니다 "
            f"(요청: {target_char_count}). 이미지를 늘리거나 target을 낮추세요.",
        )
    # 미제공 시 이미지 수 기반 기본값
    if target_char_count is None:
        target_char_count = _default_target_for_images(len(images))

    active = session.exec(
        select(Task).where(
            Task.product_name == product_name,
            Task.status.in_(ACTIVE_STATUSES),  # type: ignore[attr-defined]
        )
    ).first()
    if active:
        raise HTTPException(
            409,
            f"동일 상품명의 진행 중 작업이 있습니다 (task_id={active.id}).",
        )

    for img in images:
        if img.content_type not in ALLOWED_IMAGE_MIME:
            raise HTTPException(
                400,
                f"지원하지 않는 이미지 타입: {img.content_type}",
            )

    task = Task(
        product_name=product_name,
        price_info=price_info,
        detail_text=detail_text,
        seller_memo=seller_memo,
        campaign_variant=campaign_variant,
        landing_url=landing_url,
        coupon_info=coupon_info,
        target_char_count=target_char_count,
        original_price=original_price,
        sale_price=sale_price,
        images="[]",
        status=TaskStatus.pending,
        current_step=TaskStep.generating_script,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    saved_paths: list[str] = []
    for idx, img in enumerate(images):
        sanitized = _sanitize_filename(img.filename or f"img_{idx}")
        dest = UPLOADS_DIR / f"{task.id}_{idx}_{sanitized}"
        content = await img.read()
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(400, f"이미지 크기 초과(>10MB): {img.filename}")
        dest.write_bytes(content)
        saved_paths.append(str(dest.resolve()))

    task.images = json.dumps(saved_paths, ensure_ascii=False)
    session.add(task)
    session.commit()

    logger.info(
        "created task %d: %s (%d images)", task.id, product_name, len(saved_paths)
    )

    background_tasks.add_task(run_script_generation, task.id)

    return TaskCreatedResp(task_id=task.id, status=task.status)


@router.get("", response_model=TaskListResp)
def list_tasks(session: Session = Depends(get_session)) -> TaskListResp:
    tasks = session.exec(select(Task).order_by(Task.created_at.desc())).all()
    return TaskListResp(tasks=[_to_summary(t) for t in tasks])


@router.get("/{task_id}", response_model=TaskDetailResp)
def get_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> TaskDetailResp:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")

    sub_progress = None
    sub_duration_sec: int | None = None
    if task.sub_started_at is not None:
        sub_duration_sec = int(
            (datetime.utcnow() - task.sub_started_at).total_seconds()
        )
    if task.sub_agent and task.sub_started_at:
        try:
            idx = SCRIPT_STAGE_ORDER.index(task.sub_agent)
            cur = idx + 1
            total = len(SCRIPT_STAGE_ORDER)
        except ValueError:
            cur, total = 1, 1
        sub_progress = SubProgress(
            current=cur,
            total=total,
            agent=task.sub_agent,
            elapsed_sec=float(sub_duration_sec or 0),
        )

    try:
        tts_options = json.loads(task.tts_options) if task.tts_options else None
    except json.JSONDecodeError:
        tts_options = None

    from services.i2v_models import normalize_chain
    from services import clip_sources as _cs
    sources = _cs.load(task.output_dir) if task.output_dir else {}
    return TaskDetailResp(
        id=task.id,
        product_name=task.product_name,
        status=task.status,
        current_step=task.current_step,
        sub_progress=sub_progress,
        sub_duration_sec=sub_duration_sec,
        progress_message=task.progress_message,
        original_price=task.original_price,
        sale_price=task.sale_price,
        created_at=task.created_at,
        completed_at=task.completed_at,
        output_dir=task.output_dir,
        error=task.error,
        artifacts=_compute_artifacts(task.output_dir),
        images=json.loads(task.images or "[]"),
        selected_variant_ids=json.loads(task.selected_variant_ids or "[]"),
        selected_clips=json.loads(task.selected_clips or "{}"),
        campaign_variant=task.campaign_variant,
        tts_provider=task.tts_provider,
        tts_options=tts_options,
        target_char_count=task.target_char_count,
        i2v_model=task.i2v_model,
        i2v_models_chain=normalize_chain(task.i2v_model),
        clip_sources=sources,
    )


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Task 삭제. status 무관(running도 삭제 가능).

    정리 범위:
    - DB row
    - UPLOADS_DIR의 업로드 이미지 (task.images 경로)
    - task.output_dir 전체 디렉토리 (shutil.rmtree)

    주의: 진행 중 Veo 호출은 동기식이라 취소 불가 → Veo 완료 후
    video_generator가 output_dir을 재생성해 고아 mp4가 남을 수 있음.
    응답의 `warning` 필드로 사용자에게 안내.
    """
    import shutil

    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")

    was_running = task.status == TaskStatus.running
    product_name = task.product_name
    output_dir = task.output_dir

    # 1. 업로드 이미지 제거 (task.images JSON)
    removed_images = 0
    try:
        for p in json.loads(task.images or "[]"):
            try:
                path = Path(p)
                if path.is_file() and path.resolve().is_relative_to(
                    UPLOADS_DIR.resolve()
                ):
                    path.unlink()
                    removed_images += 1
            except (OSError, ValueError):
                continue
    except json.JSONDecodeError:
        pass

    # 2. output_dir 전체 제거 — OUTPUT_DIR 하위 경로일 때만 (경로 탈출 방어)
    output_removed = False
    if output_dir:
        try:
            out_path = Path(output_dir).resolve()
            if (
                out_path.exists()
                and out_path.is_dir()
                and out_path.is_relative_to(OUTPUT_DIR.resolve())
                and out_path != OUTPUT_DIR.resolve()
            ):
                shutil.rmtree(out_path, ignore_errors=True)
                output_removed = not out_path.exists()
            elif out_path.exists():
                logger.warning(
                    "task %d: output_dir %s outside OUTPUT_DIR — skipping rmtree",
                    task_id, out_path,
                )
        except (OSError, ValueError):
            pass

    # 3. DB row 제거
    session.delete(task)
    session.commit()

    logger.info(
        "deleted task %d (%s): images=%d, output_removed=%s, was_running=%s",
        task_id, product_name, removed_images, output_removed, was_running,
    )

    warning = None
    if was_running:
        warning = (
            "진행 중이던 작업은 강제 삭제되었습니다. "
            "Veo/ElevenLabs 호출은 취소되지 않으므로 완료되면 "
            "output 폴더가 재생성되어 고아 파일이 남을 수 있습니다."
        )

    return {
        "task_id": task_id,
        "product_name": product_name,
        "removed_images": removed_images,
        "output_removed": output_removed,
        "was_running": was_running,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# 단계 진행 + 개별 재생성 + CapCut 빌드
# ---------------------------------------------------------------------------


def _assert_status(task: Task, allowed: set[TaskStatus]) -> None:
    if task.status not in allowed:
        raise HTTPException(
            409,
            f"현재 상태({task.status})에서 이 작업은 허용되지 않습니다. "
            f"allowed={sorted(s.value for s in allowed)}",
        )


# 역방향 전이 화이트리스트. 확장 필요 시 이 dict에 1줄 추가하면 됨.
# UI state 되돌리기만 수행 — artifact 파일은 건드리지 않으므로 데이터 손실 없음.
_BACK_TRANSITIONS: dict[TaskStep, TaskStep] = {
    TaskStep.review_prompts: TaskStep.review_tts,
    TaskStep.select_tts: TaskStep.select_scripts,
}


@router.post("/{task_id}/back")
def back_step(
    task_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """이전 단계로 되돌리기. 화이트리스트 전이만 허용.

    status는 awaiting_user 전제, artifact는 보존. current_step만 교체하므로
    다음 polling cycle에서 프론트가 이전 화면으로 리렌더한다.
    """
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})

    prev = _BACK_TRANSITIONS.get(task.current_step) if task.current_step else None
    if prev is None:
        allowed = sorted(s.value for s in _BACK_TRANSITIONS.keys())
        raise HTTPException(
            409,
            f"현재 단계({task.current_step})에서는 이전으로 이동할 수 없습니다. "
            f"허용: {allowed}",
        )

    old_step = task.current_step
    task.current_step = prev
    session.add(task)
    session.commit()

    logger.info(
        "task %d: back transition %s -> %s",
        task_id, old_step, prev,
    )
    return {"task_id": task_id, "next_step": prev}


# variant drop 허용 단계 — 사용자 개입(awaiting_user) + 파이프라인 중간 검수 단계만.
# select_scripts는 체크박스로 이미 조정 가능, running/generating_*은 중간 취소 불가.
_DROP_ALLOWED_STEPS: set[TaskStep] = {
    TaskStep.select_tts,
    TaskStep.review_tts,
    TaskStep.review_prompts,
    TaskStep.select_clips,
    TaskStep.preview_timeline,
    TaskStep.select_template,
}

# TTS 옵션 검증 상수 — Typecast API 스펙 기반.
_ALLOWED_TTS_PROVIDERS = {"elevenlabs", "typecast"}
_ALLOWED_EMOTION_PRESETS = {
    "normal", "happy", "sad", "angry", "whisper", "toneup", "tonedown",
}
_ALLOWED_AUDIO_FORMATS = {"mp3", "wav"}


def _validate_tts_options(provider: str, options: dict | None) -> dict:
    """select_tts / preview 공통 검증. 잘못된 값은 400."""
    if options is None:
        options = {}
    if provider == "typecast":
        voice_id = options.get("voice_id")
        if not voice_id or not isinstance(voice_id, str):
            raise HTTPException(400, "tts_options.voice_id는 필수 (Typecast).")
        emotion_type = options.get("emotion_type")
        if emotion_type not in (None, "smart", "preset"):
            raise HTTPException(
                400, "emotion_type은 'smart' 또는 'preset'이어야 합니다."
            )
        if emotion_type == "preset":
            preset = options.get("emotion_preset", "normal")
            if preset not in _ALLOWED_EMOTION_PRESETS:
                raise HTTPException(
                    400,
                    f"emotion_preset은 {sorted(_ALLOWED_EMOTION_PRESETS)} 중 하나.",
                )
            intensity = options.get("emotion_intensity")
            if intensity is not None and not 0.0 <= float(intensity) <= 2.0:
                raise HTTPException(400, "emotion_intensity는 0.0~2.0.")
        tempo = options.get("audio_tempo")
        if tempo is not None and not 0.5 <= float(tempo) <= 2.0:
            raise HTTPException(400, "audio_tempo는 0.5~2.0.")
        pitch = options.get("audio_pitch")
        if pitch is not None and not -12 <= int(pitch) <= 12:
            raise HTTPException(400, "audio_pitch는 -12~12.")
        volume = options.get("volume")
        if volume is not None and not 0 <= int(volume) <= 200:
            raise HTTPException(400, "volume은 0~200.")
        fmt = options.get("audio_format", "mp3")
        if fmt not in _ALLOWED_AUDIO_FORMATS:
            raise HTTPException(400, "audio_format은 mp3 또는 wav.")
    # elevenlabs는 현재 서버에서 voice 고정 — options는 향후 확장 지점.
    return options


@router.post("/{task_id}/drop-variant")
def drop_variant(
    task_id: int,
    body: DropVariantReq,
    session: Session = Depends(get_session),
) -> dict:
    """선택된 variant 중 하나를 이후 파이프라인에서 제외.

    - selected_variant_ids 배열에서 제거 + selected_clips dict에서 키 제거
    - artifact 파일(audio/clip mp4)은 유지 (디스크 정리는 DELETE task 때 일괄)
    - 최소 1개는 남겨야 함 (전부 drop 불가)
    """
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})

    if task.current_step not in _DROP_ALLOWED_STEPS:
        allowed = sorted(s.value for s in _DROP_ALLOWED_STEPS)
        raise HTTPException(
            409,
            f"현재 단계({task.current_step})에서는 variant를 제외할 수 없습니다. "
            f"허용: {allowed}",
        )

    variant_id = body.variant_id
    try:
        current = json.loads(task.selected_variant_ids or "[]")
    except json.JSONDecodeError:
        current = []

    if variant_id not in current:
        raise HTTPException(
            404,
            f"variant_id={variant_id}는 selected_variant_ids에 없습니다. "
            f"현재: {current}",
        )
    if len(current) <= 1:
        raise HTTPException(
            400,
            "최소 1개의 variant는 유지해야 합니다.",
        )

    remaining = [v for v in current if v != variant_id]
    task.selected_variant_ids = json.dumps(remaining, ensure_ascii=False)

    # selected_clips에서도 해당 variant 키 제거
    try:
        clips_map = json.loads(task.selected_clips or "{}")
    except json.JSONDecodeError:
        clips_map = {}
    if variant_id in clips_map:
        clips_map.pop(variant_id, None)
        task.selected_clips = json.dumps(clips_map, ensure_ascii=False)

    session.add(task)
    session.commit()

    logger.info(
        "task %d: dropped variant %s (remaining=%s)",
        task_id, variant_id, remaining,
    )
    return {
        "task_id": task_id,
        "dropped": variant_id,
        "remaining": remaining,
    }


@router.post("/{task_id}/next")
def next_step(
    task_id: int,
    body: NextStepReq,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})

    step = body.step
    # 방어적 가드: body.step이 실제 현재 step과 일치해야 함. 프론트가 stale
    # 상태에서 다른 step을 보내 파이프라인을 건너뛰는 상황을 차단.
    if task.current_step != step:
        raise HTTPException(
            409,
            f"요청 step({step})이 현재 단계({task.current_step})와 다릅니다.",
        )

    if step == TaskStep.select_scripts:
        if not body.selected_variant_ids:
            raise HTTPException(400, "selected_variant_ids 필요")
        task.selected_variant_ids = json.dumps(
            body.selected_variant_ids, ensure_ascii=False
        )
        # select_tts 단계로 전이 (provider/voice 선택 필요). TTS 생성은 여기서 시작 안 함.
        task.current_step = TaskStep.select_tts
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": TaskStep.select_tts}

    if step == TaskStep.select_tts:
        provider = (body.tts_provider or "").lower().strip()
        if provider not in _ALLOWED_TTS_PROVIDERS:
            raise HTTPException(
                400,
                f"tts_provider는 {sorted(_ALLOWED_TTS_PROVIDERS)} 중 하나.",
            )
        options = _validate_tts_options(provider, body.tts_options)

        try:
            selected = json.loads(task.selected_variant_ids or "[]")
        except json.JSONDecodeError:
            selected = []
        if not selected:
            raise HTTPException(
                409,
                "selected_variant_ids가 비어있습니다. 이전 단계에서 선택하세요.",
            )

        task.tts_provider = provider
        task.tts_options = json.dumps(options, ensure_ascii=False)
        # 선제적 상태 전이 (race condition 방지)
        task.current_step = TaskStep.generating_tts
        task.status = TaskStatus.running
        session.add(task)
        session.commit()
        background_tasks.add_task(run_tts_generation, task_id, selected)
        return {"task_id": task_id, "next_step": TaskStep.generating_tts}

    if step == TaskStep.review_tts:
        task.current_step = TaskStep.review_prompts
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": TaskStep.review_prompts}

    if step == TaskStep.review_prompts:
        if body.i2v_model is not None:
            from services.i2v_models import I2V_CATALOG
            if body.i2v_model not in I2V_CATALOG:
                raise HTTPException(
                    400,
                    f"i2v_model={body.i2v_model}는 카탈로그에 없습니다.",
                )
            task.i2v_model = body.i2v_model
        # 선제적 상태 전이: background task가 첫 _update 하기 전에 프론트가
        # GET /tasks/{id}를 쳐서 UI가 멈추는 race condition 방지
        task.current_step = TaskStep.generating_video
        task.status = TaskStatus.running
        session.add(task)
        session.commit()
        background_tasks.add_task(run_video_generation, task_id)
        return {"task_id": task_id, "next_step": TaskStep.generating_video}

    if step == TaskStep.select_clips:
        if body.selected_clips is not None:
            task.selected_clips = json.dumps(
                body.selected_clips, ensure_ascii=False
            )
        task.current_step = TaskStep.preview_timeline
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": TaskStep.preview_timeline}

    if step == TaskStep.preview_timeline:
        task.current_step = TaskStep.select_template
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": TaskStep.select_template}

    raise HTTPException(400, f"알 수 없는 step: {step}")


@router.post("/{task_id}/regenerate-script")
def post_regenerate_script(
    task_id: int,
    body: RegenerateScriptReq,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != TaskStep.select_scripts:
        raise HTTPException(
            409, f"대본 재생성은 select_scripts 단계에서만 (현재: {task.current_step})"
        )

    background_tasks.add_task(
        regenerate_script_variant, task_id, body.variant_id, body.direction
    )
    return {
        "task_id": task_id,
        "variant_id": body.variant_id,
        "status": "regenerating",
    }


@router.post("/{task_id}/regenerate-tts")
def post_regenerate_tts(
    task_id: int,
    body: RegenerateTtsReq,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != TaskStep.review_tts:
        raise HTTPException(
            409, f"TTS 재생성은 review_tts 단계에서만 (현재: {task.current_step})"
        )

    background_tasks.add_task(regenerate_tts_variant, task_id, body.variant_id)
    return {
        "task_id": task_id,
        "variant_id": body.variant_id,
        "status": "regenerating",
    }


@router.post("/{task_id}/regenerate-clip")
def post_regenerate_clip(
    task_id: int,
    body: RegenerateClipReq,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    from services import clip_sources as _cs
    from services.pipeline_runner import _output_dir_for

    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != TaskStep.select_clips:
        raise HTTPException(
            409,
            f"클립 재생성은 select_clips 단계에서만 (현재: {task.current_step})",
        )

    out = _output_dir_for(task)
    if _cs.is_user_clip(out, body.variant_id, body.clip_num) and not body.force:
        raise HTTPException(
            409,
            "user uploaded clip exists — pass force=true to overwrite",
        )

    background_tasks.add_task(
        regenerate_clip, task_id, body.variant_id, body.clip_num
    )
    return {
        "task_id": task_id,
        "variant_id": body.variant_id,
        "clip_num": body.clip_num,
        "status": "regenerating",
    }


@router.post("/{task_id}/upload-clip", response_model=UploadClipResp)
async def post_upload_clip(
    task_id: int,
    variant_id: str = Form(...),
    clip_num: int = Form(..., ge=1),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> UploadClipResp:
    """사용자 mp4를 clips/clip_{variant_id}_{clip_num}.mp4로 저장.

    - mime: video/mp4만 허용
    - 9:16 위반은 경고만, 60초 초과는 422
    - clip_sources.json에 source=user 기록 (regenerate-clip이 force 없으면 거부)
    """
    from services import clip_sources as _cs
    from services.clip_validator import validate_upload
    from services.file_ops import clip_path
    from services.pipeline_runner import _output_dir_for

    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step not in {
        TaskStep.select_clips, TaskStep.preview_timeline,
    }:
        raise HTTPException(
            409,
            "클립 업로드는 select_clips 또는 preview_timeline 단계에서만 "
            f"(현재: {task.current_step})",
        )

    if file.content_type not in {"video/mp4", "application/mp4"}:
        raise HTTPException(
            400, f"video/mp4만 허용 (got {file.content_type})"
        )

    # variant_id / clip_num이 strategy에 존재하는지
    out = Path(_output_dir_for(task))
    strategy_path = out / "strategy.json"
    if not strategy_path.exists():
        raise HTTPException(409, "strategy.json 없음 — 영상 생성 단계 후 업로드")
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    variant = next(
        (v for v in strategy.get("variants", [])
         if v.get("variant_id") == variant_id),
        None,
    )
    if variant is None:
        raise HTTPException(404, f"variant_id={variant_id} not in strategy")
    units = variant.get("scenes") or variant.get("clips") or []
    valid_nums = {
        (u.get("scene_num") if u.get("scene_num") is not None else u.get("clip_num"))
        for u in units
    }
    if clip_num not in valid_nums:
        raise HTTPException(
            404, f"clip_num={clip_num} not in variant {variant_id}",
        )

    target = clip_path(out, variant_id, clip_num)
    target.parent.mkdir(parents=True, exist_ok=True)

    # 임시 경로에 먼저 저장 → 검증 → 통과 시 atomic rename
    tmp = target.with_suffix(".upload.tmp")
    try:
        with open(tmp, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
        await file.close()

        probe, rejects = validate_upload(tmp)
        if rejects:
            raise HTTPException(422, "; ".join(rejects))

        tmp.replace(target)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, f"upload failed: {e}") from e

    _cs.mark_user_upload(
        str(out), variant_id, clip_num,
        original_filename=file.filename or "uploaded.mp4",
        duration_sec=probe.duration_sec,
        width=probe.width,
        height=probe.height,
    )

    aspect_warning = None
    if probe.is_portrait_9x16 is False:
        aspect_warning = (
            f"비-9:16 비율 ({probe.width}×{probe.height}, "
            f"ratio {probe.aspect_ratio:.3f}) — CapCut에서 letterbox 처리됨"
        )

    logger.info(
        "task %d: user uploaded clip variant=%s num=%d size=%.1fKB "
        "duration=%s aspect=%s",
        task_id, variant_id, clip_num, target.stat().st_size / 1024,
        probe.duration_sec, probe.aspect_ratio,
    )

    return UploadClipResp(
        task_id=task_id,
        variant_id=variant_id,
        clip_num=clip_num,
        saved_filename=target.name,
        duration_sec=probe.duration_sec,
        width=probe.width,
        height=probe.height,
        aspect_ratio_warning=aspect_warning,
        ffprobe_skipped=not probe.has_ffprobe,
    )


@router.patch("/{task_id}/edit-script")
def patch_edit_script(
    task_id: int,
    body: EditScriptReq,
    session: Session = Depends(get_session),
) -> dict:
    """사용자 인라인 편집으로 scripts_final.json의 script_text만 부분 치환.

    LLM 재호출 없이 즉시 반영되며, 해당 variant의 TTS/클립 캐시는 stale이
    되므로 audio mp3/srt를 삭제해 다음 TTS 단계가 재생성하도록 유도한다.
    (클립은 이미 select_clips/review_prompts 이전 단계이므로 미영향.)
    """
    from services.file_ops import (
        audio_paths,
        delete_if_exists,
        patch_script_segment,
        patch_script_text,
    )
    from services.pipeline_runner import _output_dir_for

    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step not in {TaskStep.select_scripts, TaskStep.review_tts}:
        raise HTTPException(
            409,
            "대본 편집은 select_scripts 또는 review_tts 단계에서만 "
            f"(현재: {task.current_step})",
        )
    text = body.script_text.strip()
    # scene segment는 짧을 수 있으므로 1자 이상만 강제. 전체 치환은 5자 유지.
    min_chars = 1 if body.scene_num is not None else 5
    if len(text) < min_chars:
        raise HTTPException(
            400, f"script_text는 최소 {min_chars}자 이상이어야 합니다."
        )
    if len(text) > 800:
        raise HTTPException(400, "script_text는 800자를 초과할 수 없습니다.")

    out = Path(_output_dir_for(task))
    try:
        if body.scene_num is not None:
            patch_script_segment(
                out / "scripts_final.json",
                body.variant_id,
                body.scene_num,
                text,
            )
        else:
            patch_script_text(out / "scripts_final.json", body.variant_id, text)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e

    if task.current_step == TaskStep.review_tts:
        mp3, srt = audio_paths(out, body.variant_id)
        delete_if_exists(mp3)
        delete_if_exists(srt)

    logger.info(
        "task %d: script edited inline (variant=%s scene=%s, %d chars)",
        task_id, body.variant_id, body.scene_num, len(text),
    )
    return {
        "task_id": task_id,
        "variant_id": body.variant_id,
        "scene_num": body.scene_num,
        "script_text_length": len(text),
        "status": "edited",
    }


@router.patch("/{task_id}/edit-prompt")
def patch_edit_prompt(
    task_id: int,
    body: EditPromptReq,
    session: Session = Depends(get_session),
) -> dict:
    """strategy.json의 (variant_id, clip_num) i2v_prompt만 부분 치환.

    review_prompts 단계에서만 허용. 클립 mp4가 이미 있다면 프롬프트 변경으로
    stale이 되므로 삭제해 다음 영상 생성이 재호출되도록 한다.
    """
    from services.file_ops import (
        clip_path,
        delete_if_exists,
        patch_prompt_in_strategy,
    )
    from services.pipeline_runner import _output_dir_for

    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != TaskStep.review_prompts:
        raise HTTPException(
            409,
            f"프롬프트 편집은 review_prompts 단계에서만 (현재: {task.current_step})",
        )
    prompt = body.i2v_prompt.strip()
    if len(prompt) < 5:
        raise HTTPException(400, "i2v_prompt는 최소 5자 이상이어야 합니다.")

    out = Path(_output_dir_for(task))
    try:
        patch_prompt_in_strategy(
            out / "strategy.json",
            body.variant_id,
            body.clip_num,
            prompt,
        )
    except KeyError as e:
        raise HTTPException(404, str(e)) from e

    # 아직 생성되지 않았을 수 있지만, 이전 실행의 잔여 클립이 있으면 stale
    delete_if_exists(clip_path(out, body.variant_id, body.clip_num))

    logger.info(
        "task %d: prompt edited inline (variant=%s clip=%d, %d chars)",
        task_id, body.variant_id, body.clip_num, len(prompt),
    )
    return {
        "task_id": task_id,
        "variant_id": body.variant_id,
        "clip_num": body.clip_num,
        "status": "edited",
    }


@router.post("/{task_id}/build-capcut")
def post_build_capcut(
    task_id: int,
    body: BuildCapcutReq,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != TaskStep.select_template:
        raise HTTPException(
            409,
            f"CapCut 빌드는 select_template 단계에서만 (현재: {task.current_step})",
        )

    if body.campaign_variant and body.campaign_variant not in ALLOWED_CAMPAIGN:
        raise HTTPException(
            400,
            f"campaign_variant는 {sorted(ALLOWED_CAMPAIGN)} 중 하나.",
        )

    # 선제적 상태 전이 (race condition 방지)
    task.current_step = TaskStep.building_capcut
    task.status = TaskStatus.running
    session.add(task)
    session.commit()

    background_tasks.add_task(
        run_capcut_build,
        task_id,
        body.template_assignments,
        body.campaign_variant,
    )
    return {"task_id": task_id, "status": "building"}
