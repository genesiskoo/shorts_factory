"""agents/product_analyzer.py — ① 리서처 [Gemini Flash]

3-Step 로직:
  Step 1: 이미지+텍스트로 상품 유형 분류
  Step 2: 유형별 분기 리서치
  Step 3: product_profile.json 생성
"""

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
    """단순 {var} 치환. JSON 중괄호와 충돌하지 않도록 알파벳/밑줄 식별자만 치환."""
    def replace(m):
        key = m.group(1)
        return str(kwargs.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)


def run(
    product_name: str,
    images: list[str],
    price_info: str | None = None,
    detail_text: str | None = None,
    seller_memo: str | None = None,
) -> dict:
    """상품 분석 실행. product_profile dict 반환."""

    logger.info(f"[product_analyzer] 시작: {product_name}")
    flash = GeminiClient("flash")

    # ── Step 1: 유형 분류 ──────────────────────────────────────────────────
    logger.info("[product_analyzer] Step1: 유형 분류")
    classify_prompt = _fmt(
        _load_prompt("product_analyzer_classify.txt"),
        product_name=product_name,
        price_info=price_info or "없음",
        detail_text=detail_text or "없음",
        seller_memo=seller_memo or "없음",
    )
    classify_result = flash.call(classify_prompt, images=images, json_mode=True)
    if isinstance(classify_result, list):
        classify_result = classify_result[0] if classify_result else {}
    product_type: str = classify_result.get("product_type", "C_emotion")
    type_reason: str = classify_result.get("type_reason", "")
    logger.info(f"[product_analyzer] 유형: {product_type} — {type_reason}")

    # ── Step 2: 유형별 분기 리서치 ────────────────────────────────────────
    research_data: dict = {}
    image_analysis: dict = {}

    if product_type in ("A_spec", "B_niche_spec"):
        logger.info("[product_analyzer] Step2: 스펙 검색 (A/B)")
        spec_prompt = _fmt(
            _load_prompt("product_analyzer_search_spec.txt"),
            product_name=product_name,
            product_type=product_type,
            seller_memo=seller_memo or "없음",
        )
        research_data = flash.call(spec_prompt, json_mode=True)

        img_prompt = _fmt(
            _load_prompt("product_analyzer_image_analysis.txt"),
            product_name=product_name,
            product_type=product_type,
        )
        image_analysis = flash.call(img_prompt, images=images, json_mode=True)

    elif product_type in ("C_emotion", "E_visual"):
        logger.info("[product_analyzer] Step2: 이미지 분석 + 트렌드 검색 (C/E)")

        img_prompt = _fmt(
            _load_prompt("product_analyzer_image_analysis.txt"),
            product_name=product_name,
            product_type=product_type,
        )
        image_analysis = flash.call(img_prompt, images=images, json_mode=True)

        trend_prompt = _fmt(
            _load_prompt("product_analyzer_trend_search.txt"),
            product_name=product_name,
            product_type=product_type,
            image_analysis=json.dumps(image_analysis, ensure_ascii=False),
        )
        research_data = flash.call(trend_prompt, json_mode=True)

    elif product_type == "D_efficacy":
        logger.info("[product_analyzer] Step2: 성분 검색 (D)")
        efficacy_prompt = _fmt(
            _load_prompt("product_analyzer_efficacy_search.txt"),
            product_name=product_name,
            seller_memo=seller_memo or "없음",
            detail_text=detail_text or "없음",
        )
        research_data = flash.call(efficacy_prompt, json_mode=True)

        img_prompt = _fmt(
            _load_prompt("product_analyzer_image_analysis.txt"),
            product_name=product_name,
            product_type=product_type,
        )
        image_analysis = flash.call(img_prompt, images=images, json_mode=True)

    # ── Step 3: product_profile.json 생성 ────────────────────────────────
    logger.info("[product_analyzer] Step3: 프로필 JSON 생성")
    finalize_prompt = _fmt(
        _load_prompt("product_analyzer_finalize.txt"),
        product_name=product_name,
        product_type=product_type,
        type_reason=type_reason,
        price_info=price_info or "없음",
        research_data=json.dumps(research_data, ensure_ascii=False),
        image_analysis=json.dumps(image_analysis, ensure_ascii=False),
    )
    profile = flash.call(finalize_prompt, json_mode=True)

    # 필수 필드 보정
    profile.setdefault("product_name", product_name)
    profile.setdefault("product_type", product_type)
    profile.setdefault("image_analysis", image_analysis)
    profile.setdefault("source_reliability", research_data.get("source_reliability", "medium"))

    # selling_points 5개 보장
    sps = profile.get("selling_points", [])
    if len(sps) < 5:
        logger.warning(f"[product_analyzer] selling_points {len(sps)}개 — 부족하지만 진행")

    logger.info(f"[product_analyzer] 완료: {product_name}")
    return profile
