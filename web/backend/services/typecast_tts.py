"""Typecast TTS 래퍼 — ⑥ 대체 경로.

ElevenLabs 기본 경로([agents/tts_generator.py](../../agents/tts_generator.py))와
동일한 출력 파일 규약을 따라 `{output_dir}/audio/{variant_id}.mp3` +
`{variant_id}.srt`를 생성한다.

Typecast API는 SRT/timestamp를 반환하지 않으므로 응답의 duration +
script 어절 글자수 비례로 시간을 추정해 SRT를 생성한다. 추정 SRT의
정확도는 ±100~300ms 수준이며, 정확한 word-level 정렬이 필요하면
Phase 2에서 Whisper 폴백으로 교체할 예정.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("web.typecast_tts")

API_BASE = "https://api.typecast.ai"
API_ENDPOINT = f"{API_BASE}/v1/text-to-speech"
VOICES_ENDPOINT = f"{API_BASE}/v2/voices"
DEFAULT_MODEL = "ssfm-v30"
DEFAULT_LANGUAGE = "kor"
DEFAULT_TIMEOUT = 60.0  # seconds


# ---------------------------------------------------------------------------
# 예외 매핑
# ---------------------------------------------------------------------------


class TypecastError(RuntimeError):
    """Typecast API 호출 실패 공통 베이스."""


class TypecastAuthError(TypecastError):
    """401 — API 키 누락/무효."""


class TypecastCreditError(TypecastError):
    """402 — 크레딧 부족."""


class TypecastRateLimitError(TypecastError):
    """429 — 쿼터 초과."""


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 200:
        return
    body = resp.text[:300]
    if resp.status_code == 401:
        raise TypecastAuthError(f"401: {body}")
    if resp.status_code == 402:
        raise TypecastCreditError(f"402: {body}")
    if resp.status_code == 429:
        raise TypecastRateLimitError(f"429: {body}")
    raise TypecastError(f"HTTP {resp.status_code}: {body}")


# ---------------------------------------------------------------------------
# SRT 추정
# ---------------------------------------------------------------------------

_PUNCT_PAUSE_SEC = 0.15
_PUNCT_RE = re.compile(r"[.!?…,~]$")
_CHUNK_SIZE = 3  # 기존 ElevenLabs SRT와 동일(3어절 묶음)


def _format_ts(sec: float) -> str:
    """SRT 타임스탬프 포맷 (HH:MM:SS,mmm). agents/tts_generator와 동일 규칙."""
    sec = max(sec, 0.0)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:  # 반올림 보정
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _estimate_srt(text: str, duration: float) -> str:
    """어절 글자수 비례로 시간을 분배해 SRT 문자열 생성.

    1. 공백 split → 어절 리스트
    2. 각 어절 기본 가중치 = 글자수(한글/영문 공통 len 사용), 구두점 종결 시 +pause
    3. 어절별 시작/끝 시간을 누적 → 3어절씩 묶어 출력
    """
    words = [w for w in (text or "").split() if w]
    if not words or duration <= 0:
        return ""

    # 어절별 duration 계산
    weights: list[float] = []
    for w in words:
        weight = max(len(w), 1)  # 빈 어절 방어
        if _PUNCT_RE.search(w):
            weight += _PUNCT_PAUSE_SEC * 4  # 대략 4글자 분량의 휴지
        weights.append(weight)

    total_weight = sum(weights)
    per_sec = duration / total_weight

    # 누적 시간 계산
    spans: list[tuple[str, float, float]] = []
    cursor = 0.0
    for w, weight in zip(words, weights):
        start = cursor
        cursor = min(cursor + weight * per_sec, duration)
        spans.append((w, start, cursor))

    # 3어절씩 묶기
    lines = []
    idx = 1
    for i in range(0, len(spans), _CHUNK_SIZE):
        chunk = spans[i : i + _CHUNK_SIZE]
        if not chunk:
            continue
        t_start = chunk[0][1]
        t_end = chunk[-1][2]
        line_text = " ".join(w for w, _, _ in chunk)
        lines.append(
            f"{idx}\n{_format_ts(t_start)} --> {_format_ts(t_end)}\n{line_text}\n"
        )
        idx += 1
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API 호출
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    key = os.environ.get("TYPECAST_API_KEY", "").strip()
    if not key:
        raise TypecastAuthError(
            "TYPECAST_API_KEY 환경변수가 비어있습니다. .env를 확인하세요."
        )
    return key


def _build_payload(
    text: str,
    options: dict,
    ctx: dict | None = None,
) -> dict:
    """TTS 요청 payload 조립.

    options: voice_id, model, emotion_type, emotion_preset, emotion_intensity,
             audio_tempo, audio_pitch, volume, audio_format, language, seed
    ctx (optional): {"previous_text": "...", "next_text": "..."} — Smart Emotion
    """
    voice_id = options.get("voice_id")
    if not voice_id:
        raise ValueError("tts_options.voice_id is required for Typecast")

    payload: dict[str, Any] = {
        "text": text,
        "voice_id": voice_id,
        "model": options.get("model", DEFAULT_MODEL),
        "language": options.get("language", DEFAULT_LANGUAGE),
    }

    # Prompt(감정) 구성
    emotion_type = options.get("emotion_type")  # "smart" | "preset" | None
    if emotion_type == "smart":
        prompt: dict[str, Any] = {"emotion_type": "smart"}
        if ctx:
            if ctx.get("previous_text"):
                prompt["previous_text"] = ctx["previous_text"]
            if ctx.get("next_text"):
                prompt["next_text"] = ctx["next_text"]
        payload["prompt"] = prompt
    elif emotion_type == "preset":
        preset = options.get("emotion_preset", "normal")
        intensity = options.get("emotion_intensity", 1.0)
        payload["prompt"] = {
            "emotion_type": "preset",
            "emotion_preset": preset,
            "emotion_intensity": float(intensity),
        }

    # Output(튜닝) 구성 — 기본값과 다른 필드만 넣어 공백 최소화
    out: dict[str, Any] = {}
    if "audio_tempo" in options:
        out["audio_tempo"] = float(options["audio_tempo"])
    if "audio_pitch" in options:
        out["audio_pitch"] = int(options["audio_pitch"])
    if "volume" in options:
        out["volume"] = int(options["volume"])
    # format은 항상 지정 (기본 mp3)
    out["audio_format"] = options.get("audio_format", "mp3")
    payload["output"] = out

    if options.get("seed") is not None:
        payload["seed"] = int(options["seed"])

    return payload


def _synthesize_one(
    client: httpx.Client,
    text: str,
    options: dict,
    ctx: dict | None = None,
) -> tuple[bytes, float]:
    """단건 합성. (audio_bytes, duration_sec_estimate) 반환.

    Typecast API는 binary 응답이라 duration을 직접 주지 않는다. MP3일 경우
    헤더에서 직접 추출이 가능하나 외부 라이브러리 없이 대략값을 쓰려면
    `len(audio) * 8 / bitrate`. 320kbps 기준: duration ≈ len / 40000.
    WAV(44100Hz 16bit mono)는 `len / (44100*2)`.
    """
    payload = _build_payload(text, options, ctx)
    api_key = _get_api_key()
    resp = client.post(
        API_ENDPOINT,
        json=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        timeout=DEFAULT_TIMEOUT,
    )
    _raise_for_status(resp)

    audio = resp.content
    fmt = options.get("audio_format", "mp3")
    if fmt == "wav":
        duration = max(len(audio) / (44100 * 2), 0.001)
    else:
        duration = max(len(audio) / 40000.0, 0.001)  # 320kbps ≈ 40000 bytes/sec
    return audio, duration


def preview(
    text: str,
    options: dict,
    ctx: dict | None = None,
) -> tuple[bytes, str]:
    """미리듣기용 단건 합성. (audio_bytes, content_type) 반환."""
    with httpx.Client() as client:
        audio, _ = _synthesize_one(client, text, options, ctx)
    fmt = options.get("audio_format", "mp3")
    media = "audio/wav" if fmt == "wav" else "audio/mpeg"
    return audio, media


def list_voices(model: str = DEFAULT_MODEL) -> list[dict]:
    """voices 캐시 없이 외부 호출. 라우트 레이어에서 TTL 캐시 래핑."""
    api_key = _get_api_key()
    with httpx.Client() as client:
        resp = client.get(
            VOICES_ENDPOINT,
            params={"model": model},
            headers={"X-API-KEY": api_key},
            timeout=DEFAULT_TIMEOUT,
        )
    _raise_for_status(resp)
    return resp.json()


def run(
    scripts_final: dict,
    output_dir: str,
    options: dict,
    per_variant_context: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """scripts_final → audio/ 디렉토리에 MP3+SRT 저장. 파일 경로 dict 반환.

    기존 [agents/tts_generator.py](../../agents/tts_generator.py) 와 동일 시그니처
    (scripts_final, output_dir)에 options/context만 추가. 결과 dict도 동일 스키마.
    """
    logger.info("[typecast_tts] 시작 (voice_id=%s)", options.get("voice_id"))
    audio_dir = Path(output_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    scripts = scripts_final.get("scripts", [])
    result: dict[str, dict] = {}
    per_variant_context = per_variant_context or {}

    fmt = options.get("audio_format", "mp3")
    mp3_ext = ".wav" if fmt == "wav" else ".mp3"

    with httpx.Client() as client:
        for script in scripts:
            variant_id = script.get("variant_id", "unknown")
            script_text = (script.get("script_text") or "").strip()
            if not script_text:
                logger.warning("[typecast_tts] %s — script_text 비어있음, skip", variant_id)
                result[variant_id] = {
                    "mp3": None,
                    "srt": None,
                    "error": "empty script_text",
                }
                continue

            mp3_path = audio_dir / f"{variant_id}{mp3_ext}"
            srt_path = audio_dir / f"{variant_id}.srt"

            if mp3_path.exists() and srt_path.exists():
                logger.info("[typecast_tts] %s — 기존 파일 사용", variant_id)
                result[variant_id] = {"mp3": str(mp3_path), "srt": str(srt_path)}
                continue

            logger.info("[typecast_tts] %s 생성 중...", variant_id)
            try:
                audio_bytes, duration = _synthesize_one(
                    client,
                    script_text,
                    options,
                    per_variant_context.get(variant_id),
                )
                mp3_path.write_bytes(audio_bytes)

                srt_content = _estimate_srt(script_text, duration)
                srt_path.write_text(srt_content, encoding="utf-8")

                result[variant_id] = {"mp3": str(mp3_path), "srt": str(srt_path)}
                logger.info("[typecast_tts] %s 완료 (%.1fs)", variant_id, duration)

            except TypecastError as e:
                logger.error("[typecast_tts] %s 실패: %s", variant_id, e)
                result[variant_id] = {"mp3": None, "srt": None, "error": str(e)}
            except Exception as e:
                logger.exception("[typecast_tts] %s 예외: %s", variant_id, e)
                result[variant_id] = {
                    "mp3": None,
                    "srt": None,
                    "error": f"{type(e).__name__}: {e}",
                }

    logger.info("[typecast_tts] 전체 완료: %d개", len(result))
    return result
