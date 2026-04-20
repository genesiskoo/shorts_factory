"""런타임 모델/설정 정보 노출.

프런트가 하드코딩된 "Veo 3.1 preview" 같은 문구 대신 실제 config.yaml의
모델 ID와 메타데이터를 보여줄 수 있도록 한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from schemas import I2VModelInfo, I2VModelsListResp, ModelsConfigResp
from services.i2v_models import (
    DEFAULT_FALLBACK_CHAIN,
    I2V_CATALOG,
)

logger = logging.getLogger("web.config_info")
router = APIRouter(prefix="/api/config", tags=["config"])


# 표시용 메타데이터 — services/i2v_models.py의 카탈로그를 기본 사용.
# config.yaml에 박힌 model이 미등록일 때만 fallback dict 참조.
_I2V_MODEL_META_FALLBACK: dict[str, dict] = {
    m: {
        "family": meta["family"],
        "label": meta["label"],
        "notes": meta["notes"],
        "expected_sec_per_clip": meta["expected_sec_per_clip"],
        "daily_quota_estimate": meta.get("daily_quota_estimate"),
        "quality_tier": meta.get("quality_tier"),
        "speed_tier": meta.get("speed_tier"),
    }
    for m, meta in I2V_CATALOG.items()
}

# 프런트가 기본값 제안 시 참조 (routes/tasks.DEFAULT_TARGET_CHAR_COUNT와 동일).
# 중복 정의지만 순환 import 회피 + 의미적으로 "프런트가 의존할 런타임 값"이라 여기 둠.
_DEFAULT_TARGET_CHAR_COUNT = 250


@router.get("/models", response_model=ModelsConfigResp)
def get_models_config() -> ModelsConfigResp:
    """현재 파이프라인이 사용하는 모델 정보 반환."""
    try:
        from core.config import get_i2v_config  # type: ignore
        cfg = get_i2v_config()
    except Exception as e:
        raise HTTPException(500, f"config.yaml i2v 로드 실패: {e}") from e

    provider = str(cfg.get("provider", "unknown"))
    model = str(cfg.get("model", "unknown"))
    meta = _I2V_MODEL_META_FALLBACK.get(model, {
        "family": provider.title() if provider != "unknown" else "Unknown",
        "label": model,
        "notes": "등록되지 않은 model ID. services/i2v_models.py에 추가하세요.",
        "expected_sec_per_clip": 90,
        "daily_quota_estimate": None,
        "quality_tier": None,
        "speed_tier": None,
    })

    return ModelsConfigResp(
        i2v=I2VModelInfo(
            provider=provider,
            model=model,
            family=meta["family"],
            label=meta["label"],
            notes=meta["notes"],
            expected_sec_per_clip=meta["expected_sec_per_clip"],
            daily_quota_estimate=meta.get("daily_quota_estimate"),
            quality_tier=meta.get("quality_tier"),
            speed_tier=meta.get("speed_tier"),
        ),
        default_target_char_count=_DEFAULT_TARGET_CHAR_COUNT,
    )


@router.get("/i2v-models", response_model=I2VModelsListResp)
def list_i2v_models() -> I2VModelsListResp:
    """페이지 6 모델 선택 드롭다운용.

    카탈로그 전체 + DEFAULT_FALLBACK_CHAIN 순서를 노출. 사용자가 모델 1개를
    고르면 video_generator가 [선택 → 잔여 폴백 체인] 순서로 시도한다.
    """
    try:
        from core.config import get_i2v_config  # type: ignore
        cfg = get_i2v_config()
        config_default = str(cfg.get("model", DEFAULT_FALLBACK_CHAIN[0]))
    except Exception:
        config_default = DEFAULT_FALLBACK_CHAIN[0]

    models: list[I2VModelInfo] = []
    for model_id in DEFAULT_FALLBACK_CHAIN:
        meta = _I2V_MODEL_META_FALLBACK.get(model_id)
        if not meta:
            continue
        models.append(
            I2VModelInfo(
                provider="google_deepmind",
                model=model_id,
                family=meta["family"],
                label=meta["label"],
                notes=meta["notes"],
                expected_sec_per_clip=meta["expected_sec_per_clip"],
                daily_quota_estimate=meta.get("daily_quota_estimate"),
                quality_tier=meta.get("quality_tier"),
                speed_tier=meta.get("speed_tier"),
            )
        )

    return I2VModelsListResp(
        models=models,
        default_chain=list(DEFAULT_FALLBACK_CHAIN),
        config_default=config_default,
    )
