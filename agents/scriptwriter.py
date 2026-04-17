"""agents/scriptwriter.py — ④ 작가(대본) [Gemini Flash]"""

import json
import logging
import re
from pathlib import Path

from core.llm_client import GeminiClient

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _fmt(template: str, **kwargs) -> str:
    def replace(m):
        key = m.group(1)
        return str(kwargs.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)


def run(hooks: dict, strategy: dict, profile: dict, review_feedback: list | None = None) -> dict:
    """hooks + strategy + profile → scripts.json dict 반환."""

    logger.info("[scriptwriter] 시작")
    flash = GeminiClient("flash")

    # 훅과 소구 방향 결합
    hook_map = {h["variant_id"]: h["hook_text"] for h in hooks.get("hooks", [])}
    hooks_and_directions = "\n".join(
        f"- {v.get('variant_id')}: 훅=\"{hook_map.get(v.get('variant_id', ''), '')}\", 방향={v.get('direction')}"
        for v in strategy.get("variants", [])
    )

    # 이전 검수 피드백 섹션 구성 (재시도 시에만 주입)
    feedback_section = ""
    if review_feedback:
        lines = ["[이전 검수 피드백 — 이 문제를 반드시 수정하라]"]
        for fb in review_feedback:
            if not fb.get("passed"):
                vid = fb.get("variant_id", "?")
                notes = []
                if fb.get("char_count", 0) > 100:
                    notes.append(f"글자수 {fb['char_count']}자 → 반드시 100자 이내로 줄일 것")
                if fb.get("hook_score", 10) < 7:
                    notes.append(f"훅 점수 {fb['hook_score']} → 더 강한 훅 필요")
                if not fb.get("no_forbidden_violation", True):
                    notes.append("금지 표현 사용됨 → 제거할 것")
                if fb.get("differentiation_score", 10) < 6:
                    notes.append(f"차별성 {fb['differentiation_score']} → 다른 소구와 더 다르게")
                if fb.get("keyword_duplication"):
                    notes.append("감성 키워드 중복 → 다른 표현으로 교체")
                if notes:
                    lines.append(f"- {vid}: " + ", ".join(notes))
        if lines:
            feedback_section = "\n".join(lines) + "\n\n"

    prompt = _fmt(
        _load_prompt("scriptwriter.txt"),
        product_name=profile.get("product_name", ""),
        target_audience=profile.get("target_audience", ""),
        selling_points=", ".join(profile.get("selling_points", [])),
        forbidden_expressions=", ".join(profile.get("forbidden_expressions", []) or ["없음"]),
        price_advantage=profile.get("price_advantage", "없음"),
        hooks_and_directions=hooks_and_directions,
        review_feedback=feedback_section,
    )

    result = flash.call(prompt, json_mode=True)

    # 정규화: {"scripts": [...]} 보장
    if isinstance(result, list):
        result = {"scripts": result}
    elif "scripts" not in result:
        for v in result.values():
            if isinstance(v, list):
                result = {"scripts": v}
                break

    logger.info(f"[scriptwriter] 완료: {len(result.get('scripts', []))}개 대본")
    return result
