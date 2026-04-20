"""agents/storyboard_designer.py — ② PD/스토리보드 [Gemini Pro]

상품 프로필 + 이미지 → strategy.json (variants[].scenes[]).
"""

import json
import logging
import re
from pathlib import Path

from core.llm_client import GeminiClient
from core.schema_migrate import SCHEMA_VERSION

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _fmt(template: str, **kwargs) -> str:
    def replace(m):
        key = m.group(1)
        return str(kwargs.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)


def _v6_prompt_section() -> str:
    """v6_promotion 추가 지시. campaign 활성 시에만 prompt에 삽입."""
    return (
        '\n6. **v6_promotion** (할인·세일 강조형, hook_type="promotion", '
        "promotion 정보가 주어진 경우에만 작성)\n"
        "   - direction: 가격·할인·쿠폰 강조\n"
        "   - 모든 scene의 script_segment_brief에 "
        "'할인율 또는 할인가 인용' 명시\n"
        "   - 마지막 scene_intent: 정가→할인가 비교 컷, 할인율 배지 강조\n"
    )


def run(
    profile: dict,
    images: list[str],
    image_count: int | None = None,
    promotion: dict | None = None,
) -> dict:
    """상품 프로필 + 이미지 → strategy.json (schema_version=2) dict 반환.

    image_count: variant당 생성할 scene 수. 미지정 시 len(images) 사용.
    promotion: {"campaign": str, "original_price": int, "sale_price": int,
                "discount_rate": int}. 채워지면 v6_promotion variant 추가.
    규약: 이미지 1장 = scene 1개 (중복 금지). pipeline_runner에서
    한 번 더 정규화해 LLM 편차를 보정한다.
    """

    n = image_count if image_count is not None else len(images)
    enable_v6 = bool(promotion and promotion.get("sale_price"))
    expected_variants = 6 if enable_v6 else 5
    logger.info(
        "[storyboard_designer] 시작 (image_count=%d, variants=%d, v6=%s)",
        n, expected_variants, enable_v6,
    )
    pro = GeminiClient("pro")

    image_list = "\n".join(f"img_{i+1}: {path}" for i, path in enumerate(images))

    if enable_v6:
        promo_block = (
            f"\n[프로모션 정보 — v6_promotion 작성에 필수]\n"
            f"캠페인: {promotion['campaign']}\n"
            f"원가: {promotion['original_price']:,}원\n"
            f"할인가: {promotion['sale_price']:,}원\n"
            f"할인율: {promotion['discount_rate']}%\n"
        )
    else:
        promo_block = ""

    prompt = _fmt(
        _load_prompt("storyboard_designer.txt"),
        product_profile=json.dumps(profile, ensure_ascii=False, indent=2),
        image_list=image_list,
        image_count=n,
        promotion_block=promo_block,
        variant_count=expected_variants,
        v6_section=_v6_prompt_section() if enable_v6 else "",
    )

    result = pro.call(prompt, images=images, json_mode=True)

    # 최상위 정규화 (variants 키 보장)
    if isinstance(result, list):
        strategy = {"variants": result}
    elif "variants" not in result:
        for v in result.values():
            if isinstance(v, list):
                strategy = {"variants": v}
                break
        else:
            strategy = {"variants": [result]}
    else:
        strategy = result

    strategy.setdefault("schema_version", SCHEMA_VERSION)
    strategy.setdefault("image_count", n)

    valid_images = {f"img_{i+1}" for i in range(len(images))}
    variants = strategy.get("variants", [])

    for var in variants:
        if "scenes" not in var and "clips" in var:
            var["scenes"] = var.pop("clips")

        for scene in var.get("scenes", []) or []:
            src = scene.get("source_image", "")
            if src not in valid_images:
                logger.warning(
                    "[storyboard_designer] 잘못된 source_image %r → img_1로 교정", src,
                )
                scene["source_image"] = "img_1"
            if "scene_num" not in scene and "clip_num" in scene:
                scene["scene_num"] = scene.pop("clip_num")

    logger.info("[storyboard_designer] 완료: variants %d개", len(variants))
    return strategy
