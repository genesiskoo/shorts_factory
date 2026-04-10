"""core/checkpoint.py — load_or_run: 중간 산출물 캐싱"""

import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def load_or_run(filepath: str, func: Callable, *args, **kwargs) -> Any:
    """filepath가 존재하면 로드, 없으면 func 실행 후 저장."""
    path = Path(filepath)

    if path.exists():
        logger.info(f"[checkpoint] 기존 파일 로드: {path.name}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    logger.info(f"[checkpoint] 실행 시작: {func.__module__}.{func.__name__}")
    result = func(*args, **kwargs)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"[checkpoint] 저장 완료: {path.name}")
    return result


def save_json(filepath: str, data: Any) -> None:
    """JSON 직접 저장 헬퍼."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"[checkpoint] 저장: {path.name}")
