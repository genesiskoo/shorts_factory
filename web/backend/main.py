"""FastAPI 엔트리포인트."""
from __future__ import annotations

import json
import logging
import sys
import threading
from contextlib import asynccontextmanager
from typing import Callable

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config  # noqa: F401 — sys.path 삽입 side effect
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlmodel import Session, select

from config import ALLOWED_CORS_ORIGINS, LOGS_DIR, PROJECT_ROOT
from db import Task, TaskStatus, TaskStep, engine, init_db
from schemas import HealthResp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "web.log", encoding="utf-8", delay=True),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("web.main")

# 자동 재개 화이트리스트 (checkpoint 재사용이 안전한 단계만)
_RESUME_MAX = 3


# 마이그레이션은 db.init_db()가 자동 수행 (db.py::_migrate_task_columns).


def _pick_resume_trigger(task: Task) -> Callable[[], None] | None:
    """running 상태 Task를 자동 재개 가능한지 판정하고 실행 callable 반환.

    checkpoint가 안전한 tts_generator / video_generator / capcut_builder
    정상 흐름만 대상. 재생성 엔드포인트나 script 단계는 feedback loop/사용자
    트리거 재호출이 불명확하므로 화이트리스트에서 제외한다.
    """
    # pipeline_runner는 기동 중 lazy import (circular 회피)
    from services.pipeline_runner import (
        run_capcut_build,
        run_tts_generation,
        run_video_generation,
    )

    task_id = task.id
    step = task.current_step

    if step == TaskStep.generating_tts and task.sub_agent in (
        "tts_generator",
        "typecast_tts",
    ):
        try:
            selected = json.loads(task.selected_variant_ids or "[]")
        except json.JSONDecodeError:
            return None
        if not selected:
            return None
        return lambda: run_tts_generation(task_id, selected)

    if step == TaskStep.generating_video and task.sub_agent == "video_generator":
        return lambda: run_video_generation(task_id)

    if step == TaskStep.building_capcut and task.sub_agent == "capcut_builder":
        try:
            assignments = json.loads(task.template_assignments or "null")
        except json.JSONDecodeError:
            assignments = None
        campaign = task.campaign_variant
        return lambda: run_capcut_build(task_id, assignments, campaign)

    return None


def _recover_running_tasks() -> tuple[int, int]:
    """서버 재시작 시 status=running Task 복구.

    화이트리스트 매칭 + resume_count < 3 → threading.Thread로 자동 재개.
    그 외는 failed 마킹. awaiting_user는 손대지 않음.
    """
    resumed = 0
    failed = 0
    triggers: list[Callable[[], None]] = []

    with Session(engine) as session:
        stmt = select(Task).where(Task.status == TaskStatus.running)
        for task in session.exec(stmt).all():
            trigger = _pick_resume_trigger(task)
            if trigger is not None and task.resume_count < _RESUME_MAX:
                task.resume_count = task.resume_count + 1
                task.error = None
                session.add(task)
                triggers.append(trigger)
                resumed += 1
                logger.warning(
                    "startup: resuming task %d (step=%s, sub_agent=%s, attempt=%d)",
                    task.id, task.current_step, task.sub_agent, task.resume_count,
                )
            else:
                task.status = TaskStatus.failed
                task.error = (
                    "server restarted during execution (resume_count exceeded)"
                    if task.resume_count >= _RESUME_MAX
                    else "server restarted during execution"
                )
                task.sub_agent = None
                task.sub_started_at = None
                session.add(task)
                failed += 1
        session.commit()

    # DB commit 이후 스레드 시작 (재개된 작업이 같은 row를 즉시 update할 수 있음)
    for trigger in triggers:
        threading.Thread(target=trigger, daemon=True).start()

    if resumed or failed:
        logger.warning(
            "startup: resumed %d, failed %d running tasks", resumed, failed,
        )
    return resumed, failed


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _recover_running_tasks()
    logger.info("FastAPI startup complete (project_root=%s)", PROJECT_ROOT)
    yield
    logger.info("FastAPI shutdown")


app = FastAPI(title="shorts_factory web UI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.tasks import router as tasks_router  # noqa: E402
from routes.artifacts import router as artifacts_router  # noqa: E402
from routes.files import router as files_router  # noqa: E402
from routes.tts import router as tts_router  # noqa: E402
from routes.config_info import router as config_info_router  # noqa: E402

app.include_router(tasks_router)
app.include_router(artifacts_router)
app.include_router(files_router)
app.include_router(tts_router)
app.include_router(config_info_router)


@app.get("/api/health", response_model=HealthResp)
async def health() -> HealthResp:
    return HealthResp(status="ok", project_root=str(PROJECT_ROOT))
