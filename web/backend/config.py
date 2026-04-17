"""Backend config: project root sys.path 삽입 + 경로 상수."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
WEB_DIR = BACKEND_DIR.parent
PROJECT_ROOT = WEB_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

UPLOADS_DIR = BACKEND_DIR / "uploads"
LOGS_DIR = BACKEND_DIR / "logs"
DB_PATH = BACKEND_DIR / "tasks.db"
OUTPUT_DIR = PROJECT_ROOT / "output"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
