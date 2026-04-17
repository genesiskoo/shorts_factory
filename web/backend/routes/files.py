"""이미지/오디오/클립 파일 서빙 + CapCut zip 다운로드."""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from config import UPLOADS_DIR
from db import Task, get_session

router = APIRouter(prefix="/api/tasks", tags=["files"])
logger = logging.getLogger(__name__)


def _get_task(task_id: int, session: Session) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    return task


def _safe_under(root: Path, target: Path) -> None:
    """target이 root 하위 경로인지 검증 (path traversal 방지)."""
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        raise HTTPException(403, "접근 거부")


@router.get("/{task_id}/image/{filename}")
def serve_image(
    task_id: int,
    filename: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = _get_task(task_id, session)
    # 해당 task의 업로드 이미지만 서빙
    images: list[str] = json.loads(task.images or "[]")
    image_basenames = {Path(p).name for p in images}
    if filename not in image_basenames:
        raise HTTPException(404, f"image {filename} not in task {task_id}")

    path = UPLOADS_DIR / filename
    _safe_under(UPLOADS_DIR, path)
    if not path.exists():
        raise HTTPException(404, "파일 없음")
    return FileResponse(path)


@router.get("/{task_id}/audio/{variant_id}")
def serve_audio(
    task_id: int,
    variant_id: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = _get_task(task_id, session)
    if not task.output_dir:
        raise HTTPException(404, "output_dir 미설정")
    root = Path(task.output_dir) / "audio"
    path = root / f"{variant_id}.mp3"
    _safe_under(root, path)
    if not path.exists():
        raise HTTPException(404, "오디오 파일 없음")
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/{task_id}/clip/{variant_id}/{clip_num}")
def serve_clip(
    task_id: int,
    variant_id: str,
    clip_num: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = _get_task(task_id, session)
    if not task.output_dir:
        raise HTTPException(404, "output_dir 미설정")
    root = Path(task.output_dir) / "clips"
    # 실제 네이밍: clip_{variant_id}_{clip_num}.mp4
    path = root / f"clip_{variant_id}_{clip_num}.mp4"
    _safe_under(root, path)
    if not path.exists():
        raise HTTPException(404, "클립 파일 없음")
    return FileResponse(path, media_type="video/mp4")


@router.get("/{task_id}/download/{variant_id}")
def download_capcut_zip(
    task_id: int,
    variant_id: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = _get_task(task_id, session)
    if not task.output_dir:
        raise HTTPException(404, "output_dir 미설정")
    root = Path(task.output_dir) / "capcut_drafts"
    project_dir = root / variant_id
    _safe_under(root, project_dir)
    if not project_dir.exists():
        raise HTTPException(404, f"CapCut 프로젝트 없음: {variant_id}")

    # tmp zip 생성 후 FileResponse
    tmp_root = Path(tempfile.mkdtemp(prefix="capcut_dl_"))
    base = tmp_root / f"{task.product_name}_{variant_id}"
    try:
        archive = shutil.make_archive(str(base), "zip", str(project_dir))
    except Exception as e:
        raise HTTPException(500, f"zip 생성 실패: {e}")

    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"{task.product_name}_{variant_id}.zip",
    )
