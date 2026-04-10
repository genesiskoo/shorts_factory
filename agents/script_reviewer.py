"""agents/script_reviewer.py — ⑤ 검수 [Gemini Flash] (순수 함수)"""

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


def run(scripts: dict, profile: dict) -> dict:
    """scripts + profile → 검수 결과 dict 반환. 회귀/재시도는 pipeline.py에서.

    반환:
      {
        "all_passed": bool,
        "scripts": [...],  # 원본 대본 배열
        "feedback": [{"variant_id": ..., "passed": bool, ...}]
      }
    """

    logger.info("[script_reviewer] 시작")
    flash = GeminiClient("flash")

    forbidden = profile.get("forbidden_expressions", []) or []

    prompt = _fmt(
        _load_prompt("script_reviewer.txt"),
        scripts_json=json.dumps(scripts.get("scripts", []), ensure_ascii=False),
        forbidden_expressions=", ".join(forbidden) if forbidden else "없음",
    )

    result = flash.call(prompt, json_mode=True)

    # 정규화
    if "all_passed" not in result:
        # 모델이 feedback 배열만 반환한 경우
        if isinstance(result, list):
            feedback = result
        else:
            feedback = result.get("feedback", [])

        all_passed = all(f.get("passed", False) for f in feedback)
        result = {
            "all_passed": all_passed,
            "scripts": scripts.get("scripts", []),
            "feedback": feedback,
        }
    else:
        # scripts 필드가 없으면 원본 유지
        if not result.get("scripts"):
            result["scripts"] = scripts.get("scripts", [])

    # len() 하드체크: LLM 판단과 무관하게 100자 초과 시 강제 fail
    script_text_map = {
        s.get("variant_id"): s.get("script_text", "")
        for s in result.get("scripts", [])
    }
    for fb in result.get("feedback", []):
        actual_len = len(script_text_map.get(fb.get("variant_id", ""), ""))
        if actual_len > 100:
            fb["char_count"] = actual_len
            fb["passed"] = False
            logger.warning(
                f"[script_reviewer] {fb['variant_id']} 글자수 초과 강제 fail: {actual_len}자"
            )

    # all_passed 재계산 (하드체크 반영)
    result["all_passed"] = all(f.get("passed", False) for f in result.get("feedback", []))

    logger.info(
        f"[script_reviewer] 완료: all_passed={result.get('all_passed')}, "
        f"feedback={len(result.get('feedback', []))}개"
    )
    return result
