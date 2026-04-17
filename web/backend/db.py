"""SQLModel Task 정의. 지시서 섹션 4.1 준수."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterator

from sqlmodel import Field, Session, SQLModel, create_engine

from config import DB_PATH


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    awaiting_user = "awaiting_user"
    completed = "completed"
    failed = "failed"


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

    status: TaskStatus = Field(default=TaskStatus.pending, index=True)
    current_step: str | None = None
    sub_agent: str | None = None
    sub_started_at: datetime | None = None

    selected_variant_ids: str | None = None
    selected_clips: str | None = None
    template_assignments: str | None = None

    output_dir: str | None = None

    error: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
