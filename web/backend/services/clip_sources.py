"""클립 출처 추적 — output/{name}/clip_sources.json.

strategy.json은 LLM 생성 결과로 두고, 출처(veo/user)는 별도 파일로 관리.
파일 미존재 시 모두 veo 출처로 간주 (하위호환).
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger("web.clip_sources")

ClipSourceType = Literal["veo", "user"]


class ClipSourceEntry(TypedDict, total=False):
    source: ClipSourceType
    uploaded_at: str
    original_filename: str
    duration_sec: float | None
    width: int | None
    height: int | None
    model: str  # veo only


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "clip_sources.json"


def _key(variant_id: str, clip_num: int) -> str:
    return f"{variant_id}_{clip_num}"


def load(output_dir: str | Path) -> dict[str, ClipSourceEntry]:
    p = _path(output_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("clip_sources.json 파싱 실패 (%s) — 빈 dict 반환", e)
        return {}


def save(output_dir: str | Path, data: dict[str, ClipSourceEntry]) -> None:
    """atomic write — temp 파일에 쓴 후 rename. 동시성에서 partial write 방지."""
    p = _path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="clip_sources_", suffix=".tmp", dir=str(p.parent),
    )
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        Path(tmp_name).replace(p)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def get_source(
    output_dir: str | Path, variant_id: str, clip_num: int,
) -> ClipSourceEntry | None:
    return load(output_dir).get(_key(variant_id, clip_num))


def is_user_clip(output_dir: str | Path, variant_id: str, clip_num: int) -> bool:
    entry = get_source(output_dir, variant_id, clip_num)
    return bool(entry) and entry.get("source") == "user"


def mark_user_upload(
    output_dir: str | Path,
    variant_id: str,
    clip_num: int,
    *,
    original_filename: str,
    duration_sec: float | None,
    width: int | None,
    height: int | None,
) -> ClipSourceEntry:
    data = load(output_dir)
    entry: ClipSourceEntry = {
        "source": "user",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "original_filename": original_filename,
        "duration_sec": duration_sec,
        "width": width,
        "height": height,
    }
    data[_key(variant_id, clip_num)] = entry
    save(output_dir, data)
    return entry


def mark_veo(
    output_dir: str | Path,
    variant_id: str,
    clip_num: int,
    model: str,
) -> ClipSourceEntry:
    data = load(output_dir)
    entry: ClipSourceEntry = {"source": "veo", "model": model}
    data[_key(variant_id, clip_num)] = entry
    save(output_dir, data)
    return entry
