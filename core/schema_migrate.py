"""core/schema_migrate.py — strategy/scripts_final v1 → v2 in-memory 마이그레이션.

호출 규약:
- 두 migrate 함수 모두 idempotent (schema_version>=2면 즉시 반환).
- in-place 변경 + 동일 dict 반환. caller가 같은 reference를 이어 쓸 수 있음.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 2

_TIMELINE_FALLBACK = ["intro", "middle", "climax", "outro"]


def _ensure_int_version(d: dict) -> int:
    raw = d.get("schema_version", 1)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def migrate_strategy_v1_to_v2(strategy: dict) -> dict:
    """strategy.json의 variants[].clips[] → variants[].scenes[] 변환.

    clips가 이미 비어있는 빈 variant도 통과시키되, scenes를 [] 로 둔다.
    """
    if not isinstance(strategy, dict):
        return strategy
    if _ensure_int_version(strategy) >= SCHEMA_VERSION:
        return strategy

    variants = strategy.get("variants", []) or []
    for var in variants:
        if not isinstance(var, dict):
            continue
        if "scenes" in var and var["scenes"]:
            continue
        clips = var.get("clips", []) or []
        scenes: list[dict[str, Any]] = []
        for idx, clip in enumerate(clips):
            if not isinstance(clip, dict):
                continue
            scene_num = clip.get("clip_num") or (idx + 1)
            timeline = clip.get("timeline") or _TIMELINE_FALLBACK[
                min(idx, len(_TIMELINE_FALLBACK) - 1)
            ]
            scenes.append({
                "scene_num": int(scene_num),
                "source_image": clip.get("source_image", f"img_{idx + 1}"),
                "timeline": timeline,
                "expected_duration_sec": int(clip.get("expected_duration_sec") or 7),
                "scene_intent": clip.get("scene", ""),
                "script_segment_brief": "",
                "i2v_prompt_baseline": clip.get("i2v_prompt", ""),
            })
        var["scenes"] = scenes

    strategy["schema_version"] = SCHEMA_VERSION
    if "image_count" not in strategy:
        first_with_scenes = next(
            (v for v in variants if v.get("scenes")), None
        )
        if first_with_scenes:
            strategy["image_count"] = len(first_with_scenes["scenes"])
    return strategy


def migrate_scripts_final_v1_to_v2(scripts_final: dict) -> dict:
    """scripts_final.json을 v2 형태로 변환 + script_text↔full_text mirror 일원화.

    v1 task는 segment 분리를 시도하지 않는다(의미 보존 위험). hook_text/outro_text/
    scenes를 빈 값으로 두고 full_text==script_text 동일값을 유지한다 — UI는
    scenes 비어있으면 fallback("전체 대본 보기") 표시. v2 입력이라도 script_text
    누락분은 보강 (mirror 책임 단일 진입점).
    """
    if not isinstance(scripts_final, dict):
        return scripts_final

    is_v1 = _ensure_int_version(scripts_final) < SCHEMA_VERSION

    for script in scripts_final.get("scripts", []) or []:
        if not isinstance(script, dict):
            continue
        text = script.get("full_text", "") or script.get("script_text", "")
        script.setdefault("full_text", text)
        script["script_text"] = script["full_text"]
        if is_v1:
            script.setdefault("hook_text", "")
            script.setdefault("outro_text", "")
            script.setdefault("hook_attached_to", 1)
            script.setdefault("outro_attached_to", None)
            script.setdefault("scenes", [])

    scripts_final["schema_version"] = SCHEMA_VERSION
    return scripts_final


def assemble_full_text(script: dict) -> str:
    """hook + scenes[*].script_segment + outro 결정적 조립.

    scene_writer가 직접 full_text를 산출하는 것이 원칙이지만,
    인라인 편집(scene segment 변경) 후 재조립할 때 호출한다.
    """
    parts: list[str] = []
    hook = (script.get("hook_text") or "").strip()
    if hook:
        parts.append(hook)
    for scene in script.get("scenes", []) or []:
        seg = (scene.get("script_segment") or "").strip()
        if seg:
            parts.append(seg)
    outro = (script.get("outro_text") or "").strip()
    if outro:
        parts.append(outro)
    return " ".join(parts)
