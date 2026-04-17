"""FastAPI 엔트리포인트."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config  # noqa: F401 — sys.path 삽입 side effect
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from config import ALLOWED_CORS_ORIGINS, LOGS_DIR, PROJECT_ROOT
from db import Task, TaskStatus, engine, init_db
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


def _recover_running_tasks() -> int:
    """서버 재시작 시 status=running인 Task를 failed로 마킹. awaiting_user는 보존."""
    count = 0
    with Session(engine) as session:
        stmt = select(Task).where(Task.status == TaskStatus.running)
        for task in session.exec(stmt).all():
            task.status = TaskStatus.failed
            task.error = "server restarted during execution"
            session.add(task)
            count += 1
        session.commit()
    if count:
        logger.warning("startup: marked %d running tasks as failed", count)
    return count


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

app.include_router(tasks_router)
app.include_router(artifacts_router)
app.include_router(files_router)


@app.get("/api/health", response_model=HealthResp)
async def health() -> HealthResp:
    return HealthResp(status="ok", project_root=str(PROJECT_ROOT))
