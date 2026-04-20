"""Pydantic 요청/응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from db import TaskStatus, TaskStep


class TaskSummary(BaseModel):
    id: int
    product_name: str
    status: TaskStatus
    current_step: TaskStep | None
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
    current_step: TaskStep | None
    sub_progress: SubProgress | None = None
    sub_duration_sec: int | None = None
    # 마지막 진행 메시지. SubProgress와 분리해 awaiting_user/completed 후에도
    # 직전 단계 결과("[scene_writer] 5개 대본 완성")를 UI에 노출.
    progress_message: str | None = None
    # 프로모션 가격. campaign_variant != 'none' + sale_price 채워졌을 때
    # v6_promotion variant 활성화. discount_rate는 frontend에서 derive.
    original_price: int | None = None
    sale_price: int | None = None
    created_at: datetime
    completed_at: datetime | None
    output_dir: str | None
    error: str | None = None
    artifacts: dict[str, bool]
    images: list[str] = []  # absolute paths; frontend는 basename만 사용
    selected_variant_ids: list[str] = []
    selected_clips: dict[str, list[int]] = {}
    campaign_variant: str | None = None
    tts_provider: str | None = None
    tts_options: dict[str, Any] | None = None
    target_char_count: int | None = None
    i2v_model: str | None = None
    i2v_models_chain: list[str] = []
    # {f"{variant_id}_{clip_num}": {"source": "veo"|"user", ...}}
    clip_sources: dict[str, dict[str, Any]] = {}


class HealthResp(BaseModel):
    status: str
    project_root: str


class NextStepReq(BaseModel):
    step: TaskStep
    selected_variant_ids: list[str] | None = None
    selected_clips: dict[str, list[int]] | None = None
    tts_provider: str | None = None
    tts_options: dict[str, Any] | None = None
    # review_prompts → generating_video 전이 시 우선 사용할 Veo 모델 ID.
    # video_generator는 이 모델 + DEFAULT_FALLBACK_CHAIN 잔여를 폴백 체인으로 사용.
    i2v_model: str | None = None


class TtsVoice(BaseModel):
    voice_id: str
    voice_name: str
    gender: str | None = None
    age: str | None = None
    use_cases: list[str] = []
    emotions: list[str] = []


class TtsVoicesResp(BaseModel):
    provider: str
    model: str | None = None
    voices: list[TtsVoice]


class TtsPreviewReq(BaseModel):
    provider: str  # "elevenlabs" | "typecast"
    options: dict[str, Any]
    sample_text: str | None = None
    previous_text: str | None = None


class RegenerateScriptReq(BaseModel):
    variant_id: str
    direction: str | None = None


class RegenerateTtsReq(BaseModel):
    variant_id: str


class RegenerateClipReq(BaseModel):
    variant_id: str
    clip_num: int
    # 사용자 업로드 클립을 덮어쓰려면 명시적 force=True 필요. UI에서 confirm.
    force: bool = False


class UploadClipResp(BaseModel):
    task_id: int
    variant_id: str
    clip_num: int
    saved_filename: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio_warning: str | None = None
    ffprobe_skipped: bool = False


class EditScriptReq(BaseModel):
    variant_id: str
    # scene_num 지정 시 scenes[scene_num].script_segment만 갱신 후 full_text
    # 자동 재조립. 미지정(=None) 시 기존 동작(전체 script_text 치환).
    scene_num: int | None = Field(default=None, ge=1)
    script_text: str


class EditPromptReq(BaseModel):
    variant_id: str
    clip_num: int
    i2v_prompt: str


class DropVariantReq(BaseModel):
    variant_id: str


class BuildCapcutReq(BaseModel):
    template_assignments: dict[str, str] | None = None
    campaign_variant: str | None = None


class TaskCreatedResp(BaseModel):
    task_id: int
    status: TaskStatus


class I2VModelInfo(BaseModel):
    provider: str
    model: str
    family: str
    label: str
    notes: str
    expected_sec_per_clip: int
    daily_quota_estimate: int | None = None
    quality_tier: int | None = None
    speed_tier: int | None = None


class ModelsConfigResp(BaseModel):
    i2v: I2VModelInfo
    default_target_char_count: int


class I2VModelsListResp(BaseModel):
    """페이지 6 모델 선택 드롭다운용. 선택 가능한 모든 Veo 모델 + 기본 폴백 체인."""
    models: list[I2VModelInfo]
    default_chain: list[str]
    config_default: str  # config.yaml에 박힌 기본값
