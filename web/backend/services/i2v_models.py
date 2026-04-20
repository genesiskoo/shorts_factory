"""Veo 모델 카탈로그 + 폴백 체인 정책.

Google Gemini API의 image-to-video 지원 모델을 한 곳에서 관리한다.
사용자가 페이지 6(review_prompts)에서 우선순위 모델을 선택하면,
video_generator가 [선택 → 폴백 체인 default 잔여]를 순서대로 시도한다.

가용 모델 (2026-04 기준 ai.google.dev/gemini-api/docs/video):
- veo-3.1-generate-preview        : 최신, 최고 품질, 가장 비싼 quota
- veo-3.1-fast-generate-preview   : 최신, 빠르고 합리적
- veo-3.1-lite-generate-preview   : 최신, 저비용/저품질
- veo-3.0-generate-001            : 안정 버전
- veo-3.0-fast-generate-001       : 안정 빠른 버전
- veo-2.0-generate-001            : 구버전 안전망

정확한 RPM/RPD는 ai.dev/rate-limit 대시보드 참조 — quota 경험치는 추정.
"""
from __future__ import annotations

from typing import TypedDict


class I2VModelMeta(TypedDict):
    model: str
    family: str
    label: str
    notes: str
    expected_sec_per_clip: int
    daily_quota_estimate: int | None
    quality_tier: int  # 1(저) ~ 3(고)
    speed_tier: int    # 1(느림) ~ 3(빠름)


I2V_CATALOG: dict[str, I2VModelMeta] = {
    "veo-3.1-fast-generate-preview": {
        "model": "veo-3.1-fast-generate-preview",
        "family": "Veo 3.1",
        "label": "Veo 3.1 Fast (preview)",
        "notes": "최신, 빠르고 합리적. 폴백 체인 1순위.",
        "expected_sec_per_clip": 75,
        "daily_quota_estimate": 10,
        "quality_tier": 2,
        "speed_tier": 3,
    },
    "veo-3.1-generate-preview": {
        "model": "veo-3.1-generate-preview",
        "family": "Veo 3.1",
        "label": "Veo 3.1 (preview)",
        "notes": "최신, 최고 품질. quota 가장 적음.",
        "expected_sec_per_clip": 120,
        "daily_quota_estimate": 5,
        "quality_tier": 3,
        "speed_tier": 1,
    },
    "veo-3.1-lite-generate-preview": {
        "model": "veo-3.1-lite-generate-preview",
        "family": "Veo 3.1",
        "label": "Veo 3.1 Lite (preview)",
        "notes": "저비용/저품질. quota 자주 소진.",
        "expected_sec_per_clip": 90,
        "daily_quota_estimate": 7,
        "quality_tier": 1,
        "speed_tier": 2,
    },
    "veo-3.0-fast-generate-001": {
        "model": "veo-3.0-fast-generate-001",
        "family": "Veo 3.0",
        "label": "Veo 3 Fast",
        "notes": "안정 버전 빠른 모드. preview 쿼터 소진 시 폴백.",
        "expected_sec_per_clip": 80,
        "daily_quota_estimate": 8,
        "quality_tier": 2,
        "speed_tier": 3,
    },
    "veo-3.0-generate-001": {
        "model": "veo-3.0-generate-001",
        "family": "Veo 3.0",
        "label": "Veo 3",
        "notes": "안정 stable 버전. 품질 양호.",
        "expected_sec_per_clip": 110,
        "daily_quota_estimate": 6,
        "quality_tier": 3,
        "speed_tier": 2,
    },
    "veo-2.0-generate-001": {
        "model": "veo-2.0-generate-001",
        "family": "Veo 2.0",
        "label": "Veo 2",
        "notes": "구버전 안전망. 품질은 떨어지나 독립 쿼터.",
        "expected_sec_per_clip": 100,
        "daily_quota_estimate": 8,
        "quality_tier": 1,
        "speed_tier": 2,
    },
}

# 사용자가 선택을 안 했거나 선택 모델이 카탈로그에 없을 때 사용하는 기본 우선순위.
# preview 쿼터가 자주 소진되므로 fast → lite → standard preview → 3.0 안정 → 2.0 순.
DEFAULT_FALLBACK_CHAIN: list[str] = [
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
    "veo-3.1-generate-preview",
    "veo-3.0-fast-generate-001",
    "veo-3.0-generate-001",
    "veo-2.0-generate-001",
]


def normalize_chain(
    primary: str | None,
    *,
    catalog: dict[str, I2VModelMeta] = I2V_CATALOG,
) -> list[str]:
    """사용자 우선 모델 + 카탈로그 잔여 모델로 폴백 체인 구성.

    - primary가 카탈로그에 있으면 맨 앞에 오고 나머지는 DEFAULT_FALLBACK_CHAIN
      순서를 유지하며 중복 제거.
    - primary가 None/미등록이면 DEFAULT_FALLBACK_CHAIN 그대로.
    """
    chain: list[str] = []
    if primary and primary in catalog:
        chain.append(primary)
    for m in DEFAULT_FALLBACK_CHAIN:
        if m not in chain and m in catalog:
            chain.append(m)
    return chain
