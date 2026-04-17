"""Pydantic 요청/응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from db import TaskStatus


class TaskSummary(BaseModel):
    id: int
    product_name: str
    status: TaskStatus
    current_step: str | None
    created_at: datetime
    completed_at: datetime | None
    error: str | None = None


class TaskListResp(BaseModel):
    tasks: list[TaskSummary]


class SubProgress(BaseModel):
    current: int
    total: int
    agent: str | None
    elapsed_sec: float


class TaskDetailResp(BaseModel):
    id: int
    product_name: str
    status: TaskStatus
    current_step: str | None
    sub_progress: SubProgress | None = None
    created_at: datetime
    completed_at: datetime | None
    output_dir: str | None
    error: str | None = None
    artifacts: dict[str, bool]
    images: list[str] = []  # absolute paths; frontend는 basename만 사용
    selected_variant_ids: list[str] = []
    selected_clips: dict[str, list[int]] = {}
    campaign_variant: str | None = None


class HealthResp(BaseModel):
    status: str
    project_root: str


class NextStepReq(BaseModel):
    step: str
    selected_variant_ids: list[str] | None = None
    selected_clips: dict[str, list[int]] | None = None


class RegenerateScriptReq(BaseModel):
    variant_id: str
    direction: str | None = None


class RegenerateTtsReq(BaseModel):
    variant_id: str


class RegenerateClipReq(BaseModel):
    variant_id: str
    clip_num: int


class BuildCapcutReq(BaseModel):
    template_assignments: dict[str, str] | None = None
    campaign_variant: str | None = None


class TaskCreatedResp(BaseModel):
    task_id: int
    status: TaskStatus
