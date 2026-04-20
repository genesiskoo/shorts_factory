"""SQLModel Task 정의. 지시서 섹션 4.1 준수."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterator

from sqlmodel import Field, Session, SQLModel, create_engine
from sqlalchemy import event, text

from config import DB_PATH


class _ValueStrEnum(str, Enum):
    """str + Enum mixin with sane __str__.

    Python 3.11+에서 `str, Enum`의 기본 `__str__`가 `"Cls.name"`을 반환하기 때문에
    f-string 메시지에 Enum이 섞이면 `"TaskStatus.pending"` 등이 유출된다. `.value`를
    반환하도록 강제해 기존 문자열 기반 로그/응답 메시지와 동일한 표현을 보장.
    """
    def __str__(self) -> str:  # noqa: D401
        return self.value


class TaskStatus(_ValueStrEnum):
    pending = "pending"
    running = "running"
    awaiting_user = "awaiting_user"
    completed = "completed"
    failed = "failed"


class TaskStep(_ValueStrEnum):
    generating_script = "generating_script"
    select_scripts = "select_scripts"
    select_tts = "select_tts"
    generating_tts = "generating_tts"
    review_tts = "review_tts"
    review_prompts = "review_prompts"
    generating_video = "generating_video"
    select_clips = "select_clips"
    preview_timeline = "preview_timeline"
    select_template = "select_template"
    building_capcut = "building_capcut"
    completed = "completed"


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_name: str = Field(index=True)
    price_info: str | None = None
    detail_text: str | None = None
    seller_memo: str | None = None

    images: str  # JSON list: absolute paths

    campaign_variant: str | None = None
    landing_url: str | None = None
    coupon_info: str | None = None

    # 프로모션 강조용 가격 (campaign_variant ≠ 'none' + sale_price 채워졌을 때
    # v6_promotion variant 활성화). discount_rate는 응답 시점에 계산.
    original_price: int | None = None
    sale_price: int | None = None

    status: TaskStatus = Field(default=TaskStatus.pending, index=True)
    current_step: TaskStep | None = None
    sub_agent: str | None = None
    sub_started_at: datetime | None = None

    selected_variant_ids: str | None = None
    selected_clips: str | None = None
    template_assignments: str | None = None

    output_dir: str | None = None

    # TTS provider 선택: "elevenlabs" | "typecast" (NULL → elevenlabs fallback)
    tts_provider: str | None = None
    # TTS options JSON: voice_id, model, emotion_*, audio_tempo, audio_pitch, volume, audio_format
    tts_options: str | None = None

    # 스크립트 목표 글자수 (NULL → 파이프라인 기본값 250 사용). 허용 범위: 150~500.
    target_char_count: int | None = None

    # 페이지 6에서 사용자가 선택한 우선 Veo 모델 ID (NULL → 카탈로그 기본 폴백 체인).
    # video_generator는 [i2v_model → DEFAULT_FALLBACK_CHAIN 잔여]를 순서대로 시도.
    i2v_model: str | None = None

    # pipeline_runner가 sub_agent 진행 중 노출하는 한 줄 메시지 (≤80자).
    # 예: "[scene_writer] 5개 대본 생성 완료". sub_agent와 분리: agent는 단계명,
    # message는 그 단계 안 세부 진행. UI는 이 값을 폴링 갱신으로 표시.
    progress_message: str | None = None

    error: str | None = None
    resume_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


# WAL 모드: pipeline_runner의 짧은 _set_progress_message commit이 FastAPI 폴링
# read와 동시 발생할 때 SQLite 기본 DELETE journal 모드의 read/write lock 경합을
# 회피. "database is locked" 에러 안전망.
@event.listens_for(engine, "connect")
def _enable_wal(dbapi_conn, _conn_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


# 신규 컬럼 추가 시 (이름, SQL 타입) 튜플로 등록. SQLite는 ALTER TABLE이
# add column만 지원하므로 idempotent하게 누락된 컬럼만 추가한다.
_TASK_MIGRATIONS: list[tuple[str, str]] = [
    ("resume_count", "INTEGER NOT NULL DEFAULT 0"),
    ("tts_provider", "VARCHAR"),
    ("tts_options", "VARCHAR"),
    ("target_char_count", "INTEGER"),
    ("i2v_model", "VARCHAR"),
    ("progress_message", "VARCHAR"),
    ("original_price", "INTEGER"),
    ("sale_price", "INTEGER"),
]


def _migrate_task_columns() -> None:
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(task)")).fetchall()
        col_names = {row[1] for row in cols}
        if not col_names:
            return  # 새로 생성된 테이블 (이미 모든 컬럼 포함)
        for name, sql_type in _TASK_MIGRATIONS:
            if name not in col_names:
                conn.execute(text(f"ALTER TABLE task ADD COLUMN {name} {sql_type}"))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_task_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
