"""TTS 관련 라우트 — voices 프록시 + 미리듣기.

provider별 voice 목록과 미리듣기 엔드포인트. Typecast API 키는 서버만 들고
있으며 프론트에 노출하지 않는다.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session

from db import Task, get_session
from schemas import TtsPreviewReq, TtsVoice, TtsVoicesResp
from services import typecast_tts

router = APIRouter(prefix="/api", tags=["tts"])
logger = logging.getLogger("web.tts")

_VOICES_TTL_SEC = 600
_VOICES_CACHE: dict[tuple[str, str], tuple[float, list[TtsVoice]]] = {}

_PREVIEW_SAMPLE_MAX = 200
_PREVIEW_LIMIT_PER_TASK = 10
_PREVIEW_COUNTS: dict[int, int] = {}

_DEFAULT_SAMPLE_TEXT = "안녕하세요. 이 목소리로 대본을 읽어드립니다."


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------


def _convert_typecast_voice(raw: dict, model: str) -> TtsVoice:
    """Typecast v2 voices 응답 → 프론트 모델.

    `models` 필드는 `[{"version": "ssfm-v30", "emotions": [...]}, ...]` 형태.
    지정 model과 일치하는 emotions만 추출.
    """
    emotions: list[str] = []
    for m in raw.get("models", []):
        if isinstance(m, dict) and m.get("version") == model:
            emotions = list(m.get("emotions") or [])
            break
    return TtsVoice(
        voice_id=raw.get("voice_id", ""),
        voice_name=raw.get("voice_name", ""),
        gender=raw.get("gender"),
        age=raw.get("age"),
        use_cases=list(raw.get("use_cases") or []),
        emotions=emotions,
    )


@router.get("/tts/voices", response_model=TtsVoicesResp)
def list_tts_voices(
    provider: str = Query(..., description="elevenlabs | typecast"),
    model: str = Query("ssfm-v30", description="Typecast model"),
) -> TtsVoicesResp:
    provider = provider.lower().strip()

    if provider == "elevenlabs":
        # 현재 ElevenLabs는 Matilda 고정. 향후 설정 확장 지점.
        return TtsVoicesResp(
            provider="elevenlabs",
            model=None,
            voices=[
                TtsVoice(
                    voice_id="XrExE9yKIg1WjnnlVkGX",
                    voice_name="Matilda",
                    gender="female",
                    age=None,
                    use_cases=["narration"],
                    emotions=[],
                )
            ],
        )

    if provider != "typecast":
        raise HTTPException(400, f"지원하지 않는 provider: {provider}")

    cache_key = (provider, model)
    now = time.time()
    cached = _VOICES_CACHE.get(cache_key)
    if cached and now - cached[0] < _VOICES_TTL_SEC:
        return TtsVoicesResp(provider=provider, model=model, voices=cached[1])

    try:
        raw_list = typecast_tts.list_voices(model=model)
    except typecast_tts.TypecastAuthError as e:
        raise HTTPException(401, f"Typecast 인증 실패: {e}") from e
    except typecast_tts.TypecastError as e:
        raise HTTPException(502, f"Typecast voices 호출 실패: {e}") from e

    voices = [_convert_typecast_voice(v, model) for v in raw_list]
    _VOICES_CACHE[cache_key] = (now, voices)
    logger.info("typecast voices cached: %d voices (model=%s)", len(voices), model)
    return TtsVoicesResp(provider=provider, model=model, voices=voices)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@router.post("/tasks/{task_id}/tts-preview")
def preview_tts(
    task_id: int,
    body: TtsPreviewReq,
    session: Session = Depends(get_session),
) -> Response:
    """선택한 provider/options로 짧은 샘플을 즉시 합성해 오디오 반환.

    task_id는 rate-limit 카운터 키로만 사용(해당 task가 DB에 있는지만 확인).
    """
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")

    count = _PREVIEW_COUNTS.get(task_id, 0)
    if count >= _PREVIEW_LIMIT_PER_TASK:
        raise HTTPException(
            429,
            f"미리듣기 횟수 초과 ({_PREVIEW_LIMIT_PER_TASK}회/task).",
        )

    provider = (body.provider or "").lower().strip()
    if provider != "typecast":
        # MVP: ElevenLabs 미리듣기는 아직 미지원(Matilda 고정이라 의미 적음).
        raise HTTPException(
            400,
            "미리듣기는 현재 Typecast만 지원합니다.",
        )

    sample_text = (body.sample_text or _DEFAULT_SAMPLE_TEXT).strip()
    if not sample_text:
        sample_text = _DEFAULT_SAMPLE_TEXT
    if len(sample_text) > _PREVIEW_SAMPLE_MAX:
        raise HTTPException(
            400, f"sample_text는 {_PREVIEW_SAMPLE_MAX}자를 초과할 수 없습니다."
        )

    # 옵션 검증은 tasks.py의 것과 동일 규칙. 가볍게 재검증.
    from routes.tasks import _validate_tts_options  # 순환 회피 위해 지연 import
    options = _validate_tts_options(provider, body.options)

    ctx = None
    if body.previous_text:
        ctx = {"previous_text": body.previous_text[:200]}

    try:
        audio, media = typecast_tts.preview(sample_text, options, ctx)
    except typecast_tts.TypecastAuthError as e:
        raise HTTPException(401, f"Typecast 인증 실패: {e}") from e
    except typecast_tts.TypecastCreditError as e:
        raise HTTPException(402, f"Typecast 크레딧 부족: {e}") from e
    except typecast_tts.TypecastRateLimitError as e:
        raise HTTPException(429, f"Typecast 쿼터 초과: {e}") from e
    except typecast_tts.TypecastError as e:
        raise HTTPException(502, f"Typecast preview 실패: {e}") from e

    _PREVIEW_COUNTS[task_id] = count + 1
    return Response(content=audio, media_type=media)
