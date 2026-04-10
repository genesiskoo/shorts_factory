"""agents/pd_strategist.py — ② PD [Gemini Pro]

상품 프로필 + 이미지 → strategy.json
(5개 소구별 콘티 + I2V 프롬프트 + 이미지 배정)
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
    def replace(m):
        key = m.group(1)
        return str(kwargs.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)


def run(profile: dict, images: list[str]) -> dict:
    """상품 프로필 + 이미지 → strategy.json dict 반환."""

    logger.info("[pd_strategist] 시작")
    pro = GeminiClient("pro")

    # 이미지 인덱스 목록 (img_1, img_2, ...)
    image_list = "\n".join(f"img_{i+1}: {path}" for i, path in enumerate(images))

    prompt = _fmt(
        _load_prompt("pd_strategist.txt"),
        product_profile=json.dumps(profile, ensure_ascii=False, indent=2),
        image_list=image_list,
    )

    result = pro.call(prompt, images=images, json_mode=True)

    # 최상위가 "variants" 키를 가진 dict인지, 아니면 variants 배열 자체인지 정규화
    if isinstance(result, list):
        strategy = {"variants": result}
    elif "variants" not in result:
        # 모델이 다른 키 이름을 쓴 경우 첫 번째 list 값을 variants로 간주
        for v in result.values():
            if isinstance(v, list):
                strategy = {"variants": v}
                break
        else:
            strategy = {"variants": [result]}
    else:
        strategy = result

    # 검증: variants 5개, 각 clip에 필수 필드 확인
    variants = strategy.get("variants", [])
    valid_images = {f"img_{i+1}" for i in range(len(images))}

    for var in variants:
        for clip in var.get("clips", []):
            src = clip.get("source_image", "")
            if src not in valid_images:
                logger.warning(
                    f"[pd_strategist] 잘못된 source_image '{src}' → img_1로 교정"
                )
                clip["source_image"] = "img_1"

    logger.info(f"[pd_strategist] 완료: variants {len(variants)}개")
    return strategy
