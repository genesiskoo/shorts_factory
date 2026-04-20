"""Backend config: project root sys.path 삽입 + 경로 상수 + .env 로드."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
WEB_DIR = BACKEND_DIR.parent
PROJECT_ROOT = WEB_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_env_file() -> None:
    """PROJECT_ROOT/.env를 파싱해 os.environ에 주입 (python-dotenv 불필요).

    core/config.py의 _load()가 같은 일을 하지만 lazy(첫 get_*_config 호출 시).
    Typecast는 core.config와 무관한 경로이므로 서버 startup에 backend가
    책임지고 .env를 미리 실어둬야 /api/tts/voices / /tts-preview가 작동한다.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file()

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
