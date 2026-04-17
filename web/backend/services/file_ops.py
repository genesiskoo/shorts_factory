"""파일 시스템 조작 헬퍼.

- checkpoint 파일 삭제 (재생성 강제)
- scripts_final 부분 치환
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("web.file_ops")


def delete_if_exists(path: Path) -> bool:
    if path.exists():
        path.unlink()
        logger.info("deleted %s", path)
        return True
    return False


def clip_path(output_dir: str | Path, variant_id: str, clip_num: int) -> Path:
    """pipeline 실제 네이밍: clips/clip_{variant_id}_{clip_num}.mp4"""
    return Path(output_dir) / "clips" / f"clip_{variant_id}_{clip_num}.mp4"


def audio_paths(output_dir: str | Path, variant_id: str) -> tuple[Path, Path]:
    d = Path(output_dir) / "audio"
    return d / f"{variant_id}.mp3", d / f"{variant_id}.srt"


def invalidate_script_cache(output_dir: str | Path) -> None:
    """대본 재생성을 위해 hooks.json, scripts.json, scripts_final.json 삭제.
    v1/v2 suffix 파일은 과거 재시도 기록으로 남겨둠."""
    d = Path(output_dir)
    for name in ("hooks.json", "scripts.json", "scripts_final.json"):
        delete_if_exists(d / name)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("saved %s", path.name)


def replace_variant_in_scripts(
    scripts_final_path: Path,
    variant_id: str,
    new_entry: dict,
) -> dict:
    """scripts_final.json에서 해당 variant_id만 교체. 나머지는 보존."""
    data = load_json(scripts_final_path)
    scripts = data.get("scripts", [])
    for i, s in enumerate(scripts):
        if s.get("variant_id") == variant_id:
            scripts[i] = new_entry
            break
    else:
        scripts.append(new_entry)
    data["scripts"] = scripts
    save_json(scripts_final_path, data)
    return data
