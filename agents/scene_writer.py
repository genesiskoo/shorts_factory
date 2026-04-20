"""agents/scene_writer.py — ④ Scene 단위 대본 작가 [Gemini Flash]

hooks + storyboard(scenes) + profile → scripts_final
  - scripts[].scenes[].script_segment + i2v_prompt_refined
  - scripts[].hook_text + outro_text + full_text + script_text(legacy mirror)
"""

import json
import logging
import re
from pathlib import Path

from core.llm_client import GeminiClient
from core.schema_migrate import (
    SCHEMA_VERSION,
    assemble_full_text,
    migrate_strategy_v1_to_v2,
)

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent / "prompts"

# 저비용 Veo 모델(lite/fast)이 화면에 텍스트를 생성하거나 상품을 변형시키는
# 문제를 방지하기 위한 영문 가드 구문. LLM이 누락해도 코드에서 강제 append.
# substring 검사는 lowercase 비교 — LLM이 대소문자 다르게 생성해도 중복 회피.
MANDATORY_NEGATIVE_HINTS = (
    "no text on screen, no captions, no overlay text, "
    "preserve product appearance unchanged, minimal hand interaction, "
    "avoid product distortion or warping"
)
_GUARD_SENTINEL = "no text on screen"  # 포함 여부 판정 키워드


def _ensure_negative_hints(prompt: str) -> str:
    """i2v_prompt_refined에 가드 구문이 없으면 append. 빈 prompt는 그대로 반환."""
    if not prompt or _GUARD_SENTINEL in prompt.lower():
        return prompt
    sep = "" if prompt.rstrip().endswith((",", ".")) else ", "
    return prompt.rstrip() + sep + MANDATORY_NEGATIVE_HINTS


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _fmt(template: str, **kwargs) -> str:
    def replace(m):
        key = m.group(1)
        return str(kwargs.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)


def _format_storyboard(strategy: dict, hook_map: dict[str, str]) -> str:
    """variants[].scenes[]를 LLM이 읽기 쉬운 텍스트로 직렬화."""
    blocks: list[str] = []
    for v in strategy.get("variants", []):
        vid = v.get("variant_id", "?")
        hook = hook_map.get(vid, "")
        blocks.append(
            f"### {vid} (hook_type={v.get('hook_type')}, direction={v.get('direction')})"
        )
        blocks.append(f"훅(연결할 hook_text 후보): \"{hook}\"")
        for s in v.get("scenes", []) or []:
            blocks.append(
                f"  scene_num={s.get('scene_num')} "
                f"timeline={s.get('timeline')} "
                f"duration={s.get('expected_duration_sec', 7)}s "
                f"source_image={s.get('source_image')}"
            )
            blocks.append(f"    intent: {s.get('scene_intent', '')}")
            blocks.append(f"    brief : {s.get('script_segment_brief', '')}")
            blocks.append(f"    baseline_prompt: {s.get('i2v_prompt_baseline', '')}")
        blocks.append("")
    return "\n".join(blocks)


_WHITESPACE = re.compile(r"\s+")


def _normalize_ws(s: str) -> str:
    return _WHITESPACE.sub(" ", s or "").strip()


def _enforce_full_text(script: dict) -> None:
    """full_text를 hook+segments+outro 결정적 조립값으로 강제.

    공백 정규화 비교: 띄어쓰기/개행 차이는 무시. 실제 토큰이 다를 때만
    덮어쓰고 warning. script_text(legacy mirror)는 _enforce_full_text가 책임지지
    않는다 — migrate_scripts_final_v1_to_v2가 일원화.
    """
    expected = assemble_full_text(script)
    if _normalize_ws(script.get("full_text", "")) != _normalize_ws(expected):
        logger.warning(
            "[scene_writer] %s: full_text 불일치 → 결정적 조립값으로 덮어씀",
            script.get("variant_id", "?"),
        )
        script["full_text"] = expected
    script["script_text"] = script["full_text"]


def _enforce_scene_order(script: dict, expected_scene_nums: list[int]) -> int:
    """scenes 길이/순서를 strategy 입력과 동기화. 누락 시 빈 segment 채움.

    반환: 채운 빈 scene 개수. caller(run)가 결과를 보고 fail로 처리할지 결정.
    review_feedback에 추후 반영하기 위함.
    """
    scenes = script.get("scenes", []) or []
    by_num = {s.get("scene_num"): s for s in scenes if s.get("scene_num") is not None}
    rebuilt: list[dict] = []
    missing = 0
    for n in expected_scene_nums:
        if n in by_num:
            rebuilt.append(by_num[n])
        else:
            missing += 1
            logger.error(
                "[scene_writer] %s: scene_num=%d 누락 → 빈 segment (review에서 fail 예정)",
                script.get("variant_id", "?"), n,
            )
            rebuilt.append({
                "scene_num": n,
                "script_segment": "",
                "i2v_prompt_refined": "",
            })
    script["scenes"] = rebuilt
    return missing


def run(
    hooks: dict,
    strategy: dict,
    profile: dict,
    review_feedback: list | None = None,
    target_char_count: int = 250,
) -> dict:
    """hooks + strategy(scenes) + profile → scripts_final (schema_version=2) dict 반환.

    target_char_count: 합산 full_text 목표. ±20% 허용.
    """

    logger.info("[scene_writer] 시작 (target=%d자)", target_char_count)
    strategy = migrate_strategy_v1_to_v2(strategy)

    flash = GeminiClient("flash")
    target_char_min = max(int(target_char_count * 0.8), 50)
    target_char_max = int(target_char_count * 1.2)
    target_sec_min = max(int(target_char_count / 7), 5)
    target_sec_max = max(int(target_char_count / 4.5), target_sec_min + 1)

    hook_map = {h["variant_id"]: h["hook_text"] for h in hooks.get("hooks", [])}
    storyboard_text = _format_storyboard(strategy, hook_map)

    # 검수 피드백 섹션
    feedback_section = ""
    if review_feedback:
        lines = ["[이전 검수 피드백 — 반드시 수정하라]"]
        for fb in review_feedback:
            if fb.get("passed"):
                continue
            vid = fb.get("variant_id", "?")
            notes: list[str] = []
            actual = fb.get("char_count", 0)
            if actual and not (target_char_min <= actual <= target_char_max):
                if actual > target_char_max:
                    notes.append(
                        f"full_text {actual}자 → {target_char_min}~{target_char_max}자로 줄일 것"
                    )
                else:
                    notes.append(
                        f"full_text {actual}자 → {target_char_min}~{target_char_max}자로 늘릴 것"
                    )
            if fb.get("hook_score", 10) < 7:
                notes.append(f"훅 점수 {fb['hook_score']} → 더 강한 훅")
            if not fb.get("no_forbidden_violation", True):
                notes.append("금지 표현 사용됨")
            if fb.get("differentiation_score", 10) < 6:
                notes.append(f"차별성 {fb['differentiation_score']} → 다른 소구와 더 다르게")
            if fb.get("keyword_duplication"):
                notes.append("감성 키워드 중복 → 다른 표현으로")
            if notes:
                lines.append(f"- {vid}: " + ", ".join(notes))
        if len(lines) > 1:
            feedback_section = "\n".join(lines) + "\n\n"

    prompt = _fmt(
        _load_prompt("scene_writer.txt"),
        product_name=profile.get("product_name", ""),
        target_audience=profile.get("target_audience", ""),
        selling_points=", ".join(profile.get("selling_points", [])),
        forbidden_expressions=", ".join(profile.get("forbidden_expressions", []) or ["없음"]),
        price_advantage=profile.get("price_advantage", "없음"),
        variants_storyboard=storyboard_text,
        review_feedback=feedback_section,
        target_char_count=target_char_count,
        target_char_min=target_char_min,
        target_char_max=target_char_max,
        target_sec_min=target_sec_min,
        target_sec_max=target_sec_max,
    )

    result = flash.call(prompt, json_mode=True)

    # scripts 키 정규화
    if isinstance(result, list):
        result = {"scripts": result}
    elif "scripts" not in result:
        for v in result.values():
            if isinstance(v, list):
                result = {"scripts": v}
                break

    result.setdefault("schema_version", SCHEMA_VERSION)

    # variant_id → expected scene_num 목록
    expected_by_vid: dict[str, list[int]] = {
        v.get("variant_id"): [s.get("scene_num") for s in (v.get("scenes") or [])]
        for v in strategy.get("variants", [])
    }

    total_missing = 0
    for script in result.get("scripts", []):
        vid = script.get("variant_id")
        expected = expected_by_vid.get(vid, [])
        if expected:
            total_missing += _enforce_scene_order(script, expected)
        if "outro_attached_to" not in script and expected:
            script["outro_attached_to"] = expected[-1]
        script.setdefault("hook_attached_to", 1)
        script.setdefault("hook_text", "")
        script.setdefault("outro_text", "")
        for scene in script.get("scenes", []) or []:
            scene["i2v_prompt_refined"] = _ensure_negative_hints(
                scene.get("i2v_prompt_refined", "")
            )
        _enforce_full_text(script)

    if total_missing:
        logger.warning(
            "[scene_writer] 완료: %d개 대본 (누락된 scene 총 %d개 — script_reviewer가 글자수로 자동 fail 처리)",
            len(result.get("scripts", [])), total_missing,
        )
    else:
        logger.info(
            "[scene_writer] 완료: %d개 대본",
            len(result.get("scripts", [])),
        )
    return result
