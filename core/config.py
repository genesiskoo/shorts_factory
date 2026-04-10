"""core/config.py — config.yaml 로드 + API 키 환경변수 치환"""

import os
import re
import yaml
from pathlib import Path
from typing import Literal

_config: dict | None = None
_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _load() -> dict:
    global _config
    if _config is not None:
        return _config

    # .env 로드 (python-dotenv 없어도 직접 파싱)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key not in os.environ:
                    os.environ[key] = val

    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _config = _resolve_env(raw)
    return _config


def _resolve_env(obj):
    """${VAR} 문법을 환경변수로 치환."""
    if isinstance(obj, str):
        def replace(m):
            var = m.group(1)
            # 없는 키는 빈 문자열로 허용 (실제 사용 시점에 검증)
            return os.environ.get(var, "")
        return re.sub(r"\$\{(\w+)\}", replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env(v) for v in obj]
    return obj


def get_llm_config(tier: Literal["pro", "flash", "fallback"]) -> dict:
    """tier에 맞는 LLM 설정 반환. {'provider', 'model', 'api_key'}"""
    cfg = _load()
    return cfg["llm"][tier]


def get_tts_config() -> dict:
    return _load()["tts"]


def get_i2v_config() -> dict:
    return _load()["i2v"]


def get_paths_config() -> dict:
    return _load()["paths"]
