"""agents/hook_writer.py — ③ 작가(훅) [Gemini Flash]"""

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


def run(strategy: dict, profile: dict | None = None) -> dict:
    """strategy.json → hooks.json dict 반환."""

    logger.info("[hook_writer] 시작")
    flash = GeminiClient("flash")

    variants = strategy.get("variants", [])
    variants_summary = "\n".join(
        f"- {v.get('variant_id')}: hook_type={v.get('hook_type')}, direction={v.get('direction')}"
        for v in variants
    )

    target_audience = (profile or {}).get("target_audience", "20~30대")
    forbidden = ", ".join((profile or {}).get("forbidden_expressions", []) or ["없음"])

    prompt = _fmt(
        _load_prompt("hook_writer.txt"),
        variants_summary=variants_summary,
        target_audience=target_audience,
        forbidden_expressions=forbidden,
    )

    result = flash.call(prompt, json_mode=True)

    # 정규화: {"hooks": [...]} 보장
    if isinstance(result, list):
        result = {"hooks": result}
    elif "hooks" not in result:
        for v in result.values():
            if isinstance(v, list):
                result = {"hooks": v}
                break

    logger.info(f"[hook_writer] 완료: {len(result.get('hooks', []))}개 훅")
    return result
