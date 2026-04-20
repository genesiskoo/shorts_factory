"""파일 시스템 조작 헬퍼.

- checkpoint 파일 삭제 (재생성 강제)
- scripts_final 부분 치환
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("web.file_ops")

# variant_id는 영문/숫자/underscore/hyphen만 허용. path traversal 방어.
_SAFE_VARIANT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _check_variant_id(variant_id: str) -> None:
    if not _SAFE_VARIANT_ID.match(variant_id or ""):
        raise ValueError(f"unsafe variant_id: {variant_id!r}")


def delete_if_exists(path: Path) -> bool:
    if path.exists():
        path.unlink()
        logger.info("deleted %s", path)
        return True
    return False


def clip_path(output_dir: str | Path, variant_id: str, clip_num: int) -> Path:
    """pipeline 실제 네이밍: clips/clip_{variant_id}_{clip_num}.mp4"""
    _check_variant_id(variant_id)
    if not isinstance(clip_num, int) or clip_num < 1:
        raise ValueError(f"clip_num must be int >= 1: {clip_num!r}")
    return Path(output_dir) / "clips" / f"clip_{variant_id}_{clip_num}.mp4"


def audio_paths(output_dir: str | Path, variant_id: str) -> tuple[Path, Path]:
    _check_variant_id(variant_id)
    d = Path(output_dir) / "audio"
    return d / f"{variant_id}.mp3", d / f"{variant_id}.srt"


def invalidate_script_cache(output_dir: str | Path) -> None:
    """대본 재생성 시 캐시 파일 전체 삭제.

    기본 파일(hooks.json/scripts.json/scripts_final.json)뿐 아니라
    script_reviewer feedback loop의 attempt suffix 파일(hooks_v1.json 등)도
    함께 제거. 방치 시 디스크 점유가 쌓이고, 향후 재생성 루틴이 suffix 파일을
    참조하도록 확장될 경우 stale 데이터로 오동작할 위험을 차단.
    """
    d = Path(output_dir)
    for name in ("hooks.json", "scripts.json", "scripts_final.json"):
        delete_if_exists(d / name)
    # attempt suffix 파일 — scripts_final.json은 위에서 처리됨, 패턴이 겹치지 않음
    for pattern in ("hooks_v*.json", "scripts_v*.json"):
        for p in d.glob(pattern):
            delete_if_exists(p)


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


def patch_script_text(
    scripts_final_path: Path,
    variant_id: str,
    new_text: str,
) -> dict:
    """scripts_final.json에서 variant_id의 script_text만 부분 업데이트.

    사용자 인라인 편집용. replace_variant_in_scripts와 달리 기존 entry의
    title/hook_text/hashtags는 유지한 채 script_text만 치환한다. variant_id가
    없으면 KeyError.
    """
    data = load_json(scripts_final_path)
    scripts = data.get("scripts", [])
    for i, s in enumerate(scripts):
        if s.get("variant_id") == variant_id:
            scripts[i] = {**s, "script_text": new_text}
            break
    else:
        raise KeyError(f"variant_id={variant_id} not in scripts_final")
    data["scripts"] = scripts
    save_json(scripts_final_path, data)
    return data


def patch_script_segment(
    scripts_final_path: Path,
    variant_id: str,
    scene_num: int,
    new_segment: str,
) -> dict:
    """scripts_final.json에서 (variant_id, scene_num)의 script_segment만 갱신.

    full_text/script_text는 hook+segments+outro로 재조립한다. scenes가
    빈 v1 데이터에 호출하면 KeyError — caller가 patch_script_text로 fallback.
    """
    from core.schema_migrate import (
        assemble_full_text,
        migrate_scripts_final_v1_to_v2,
    )

    data = load_json(scripts_final_path)
    migrate_scripts_final_v1_to_v2(data)
    scripts = data.get("scripts", [])
    for si, s in enumerate(scripts):
        if s.get("variant_id") != variant_id:
            continue
        scenes = s.get("scenes", []) or []
        if not scenes:
            raise KeyError(
                f"variant_id={variant_id} scenes empty (legacy v1) — "
                "use patch_script_text instead"
            )
        for ci, scene in enumerate(scenes):
            if scene.get("scene_num") == scene_num:
                scenes[ci] = {**scene, "script_segment": new_segment}
                updated = {**s, "scenes": scenes}
                full = assemble_full_text(updated)
                updated["full_text"] = full
                updated["script_text"] = full
                scripts[si] = updated
                data["scripts"] = scripts
                save_json(scripts_final_path, data)
                return data
        raise KeyError(f"scene_num={scene_num} not in variant {variant_id}")
    raise KeyError(f"variant_id={variant_id} not in scripts_final")


def patch_prompt_in_strategy(
    strategy_path: Path,
    variant_id: str,
    clip_num: int,
    new_prompt: str,
) -> dict:
    """strategy.json에서 (variant_id, clip_num) 조합의 i2v_prompt만 부분 업데이트.

    사용자 인라인 편집용. 해당 variant/clip을 못 찾으면 KeyError.
    """
    data = load_json(strategy_path)
    variants = data.get("variants", [])
    for vi, v in enumerate(variants):
        if v.get("variant_id") != variant_id:
            continue
        clips = v.get("clips", [])
        for ci, c in enumerate(clips):
            if c.get("clip_num") == clip_num:
                clips[ci] = {**c, "i2v_prompt": new_prompt}
                variants[vi] = {**v, "clips": clips}
                data["variants"] = variants
                save_json(strategy_path, data)
                return data
        raise KeyError(f"clip_num={clip_num} not in variant {variant_id}")
    raise KeyError(f"variant_id={variant_id} not in strategy")
