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

from config import UPLOADS_DIR
from db import Task, TaskStatus, get_session
from schemas import (
    BuildCapcutReq,
    NextStepReq,
    RegenerateClipReq,
    RegenerateScriptReq,
    RegenerateTtsReq,
    SubProgress,
    TaskCreatedResp,
    TaskDetailResp,
    TaskListResp,
    TaskSummary,
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
        images="[]",
        status=TaskStatus.pending,
        current_step="generating_script",
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
    if task.sub_agent and task.sub_started_at:
        try:
            idx = SCRIPT_STAGE_ORDER.index(task.sub_agent)
            cur = idx + 1
            total = len(SCRIPT_STAGE_ORDER)
        except ValueError:
            cur, total = 1, 1
        elapsed = (datetime.utcnow() - task.sub_started_at).total_seconds()
        sub_progress = SubProgress(
            current=cur,
            total=total,
            agent=task.sub_agent,
            elapsed_sec=elapsed,
        )

    return TaskDetailResp(
        id=task.id,
        product_name=task.product_name,
        status=task.status,
        current_step=task.current_step,
        sub_progress=sub_progress,
        created_at=task.created_at,
        completed_at=task.completed_at,
        output_dir=task.output_dir,
        error=task.error,
        artifacts=_compute_artifacts(task.output_dir),
        images=json.loads(task.images or "[]"),
        selected_variant_ids=json.loads(task.selected_variant_ids or "[]"),
        selected_clips=json.loads(task.selected_clips or "{}"),
        campaign_variant=task.campaign_variant,
    )


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

    if step == "select_scripts":
        if not body.selected_variant_ids:
            raise HTTPException(400, "selected_variant_ids 필요")
        task.selected_variant_ids = json.dumps(
            body.selected_variant_ids, ensure_ascii=False
        )
        session.add(task)
        session.commit()
        background_tasks.add_task(
            run_tts_generation, task_id, body.selected_variant_ids
        )
        return {"task_id": task_id, "next_step": "generating_tts"}

    if step == "review_tts":
        task.current_step = "review_prompts"
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": "review_prompts"}

    if step == "review_prompts":
        background_tasks.add_task(run_video_generation, task_id)
        return {"task_id": task_id, "next_step": "generating_video"}

    if step == "select_clips":
        if body.selected_clips is not None:
            task.selected_clips = json.dumps(
                body.selected_clips, ensure_ascii=False
            )
        task.current_step = "preview_timeline"
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": "preview_timeline"}

    if step == "preview_timeline":
        task.current_step = "select_template"
        session.add(task)
        session.commit()
        return {"task_id": task_id, "next_step": "select_template"}

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
    if task.current_step != "select_scripts":
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
    if task.current_step != "review_tts":
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
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    _assert_status(task, {TaskStatus.awaiting_user})
    if task.current_step != "select_clips":
        raise HTTPException(
            409,
            f"클립 재생성은 select_clips 단계에서만 (현재: {task.current_step})",
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
    if task.current_step != "select_template":
        raise HTTPException(
            409,
            f"CapCut 빌드는 select_template 단계에서만 (현재: {task.current_step})",
        )

    if body.campaign_variant and body.campaign_variant not in ALLOWED_CAMPAIGN:
        raise HTTPException(
            400,
            f"campaign_variant는 {sorted(ALLOWED_CAMPAIGN)} 중 하나.",
        )

    background_tasks.add_task(
        run_capcut_build,
        task_id,
        body.template_assignments,
        body.campaign_variant,
    )
    return {"task_id": task_id, "status": "building"}
