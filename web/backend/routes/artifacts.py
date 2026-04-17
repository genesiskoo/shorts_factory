"""중간 산출물 JSON 조회."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from db import Task, get_session

router = APIRouter(prefix="/api/tasks", tags=["artifacts"])

_ARTIFACT_FILES = {
    "product_profile": "product_profile.json",
    "strategy": "strategy.json",
    "hooks": "hooks.json",
    "scripts": "scripts.json",
    "scripts_final": "scripts_final.json",
}


@router.get("/{task_id}/artifact/{name}")
def get_artifact(
    task_id: int,
    name: str,
    session: Session = Depends(get_session),
) -> FileResponse:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    if name not in _ARTIFACT_FILES:
        raise HTTPException(
            400, f"지원하지 않는 artifact: {name}. allowed={list(_ARTIFACT_FILES)}"
        )
    if not task.output_dir:
        raise HTTPException(404, "output_dir 미설정")

    path = Path(task.output_dir) / _ARTIFACT_FILES[name]
    if not path.exists():
        raise HTTPException(404, f"{name} 파일 없음")
    return FileResponse(path, media_type="application/json")
