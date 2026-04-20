"""Scene 기반 스키마 v2 로딩/저장 헬퍼.

디스크 파일은 v1 그대로 두고 로드 시점에 v2로 in-memory 변환. 다음 save 시
자연 갱신되어 점진 마이그레이션된다.
"""
from __future__ import annotations

from pathlib import Path

from core.schema_migrate import (
    SCHEMA_VERSION,
    migrate_scripts_final_v1_to_v2,
    migrate_strategy_v1_to_v2,
)

from services.file_ops import load_json, save_json


def load_strategy_v2(path: str | Path) -> dict:
    return migrate_strategy_v1_to_v2(load_json(Path(path)))


def load_scripts_final_v2(path: str | Path) -> dict:
    return migrate_scripts_final_v1_to_v2(load_json(Path(path)))


def save_strategy_v2(path: str | Path, data: dict) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        migrate_strategy_v1_to_v2(data)
    save_json(Path(path), data)


def save_scripts_final_v2(path: str | Path, data: dict) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        migrate_scripts_final_v1_to_v2(data)
    save_json(Path(path), data)
