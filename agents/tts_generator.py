"""agents/tts_generator.py — ⑥ 성우 [ElevenLabs]

scripts_final → audio/ (MP3 5개 + SRT 5개, word-level 타임스탬프)
"""

import json
import logging
import os
from pathlib import Path

from elevenlabs import ElevenLabs

from core.config import get_tts_config

logger = logging.getLogger(__name__)

MATILDA_VOICE_ID = "XrExE9yKIg1WjnnlVkGX"


def _alignment_to_srt(alignment: dict) -> str:
    """word-level 타임스탬프 → SRT 문자열 변환."""
    chars = alignment.get("characters", [])
    char_start = alignment.get("character_start_times_seconds", [])
    char_end = alignment.get("character_end_times_seconds", [])

    if not chars:
        return ""

    # 단어 단위로 묶기
    words: list[tuple[str, float, float]] = []
    word = ""
    w_start = 0.0
    w_end = 0.0

    for i, ch in enumerate(chars):
        t_s = char_start[i] if i < len(char_start) else 0.0
        t_e = char_end[i] if i < len(char_end) else 0.0

        if ch == " " or ch == "\n":
            if word:
                words.append((word, w_start, w_end))
                word = ""
        else:
            if not word:
                w_start = t_s
            word += ch
            w_end = t_e

    if word:
        words.append((word, w_start, w_end))

    # SRT 생성 (단어 2~3개씩 묶기)
    def ts(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    idx = 1
    chunk_size = 3
    for i in range(0, len(words), chunk_size):
        chunk = words[i: i + chunk_size]
        text = " ".join(w[0] for w in chunk)
        t_start = chunk[0][1]
        t_end = chunk[-1][2]
        lines.append(f"{idx}\n{ts(t_start)} --> {ts(t_end)}\n{text}\n")
        idx += 1

    return "\n".join(lines)


def run(scripts_final: dict, output_dir: str) -> dict:
    """scripts_final → audio/ 디렉토리에 MP3+SRT 저장. 파일 경로 dict 반환."""

    logger.info("[tts_generator] 시작")
    cfg = get_tts_config()
    client = ElevenLabs(api_key=cfg["api_key"])
    model_id = cfg.get("model", "eleven_multilingual_v2")

    audio_dir = Path(output_dir) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    scripts = scripts_final.get("scripts", [])
    result: dict[str, dict] = {}

    for script in scripts:
        variant_id = script.get("variant_id", "unknown")
        script_text = script.get("script_text", "")

        mp3_path = audio_dir / f"{variant_id}.mp3"
        srt_path = audio_dir / f"{variant_id}.srt"

        # 이미 존재하면 스킵 (checkpoint 역할)
        if mp3_path.exists() and srt_path.exists():
            logger.info(f"[tts_generator] {variant_id} — 기존 파일 사용")
            result[variant_id] = {"mp3": str(mp3_path), "srt": str(srt_path)}
            continue

        logger.info(f"[tts_generator] {variant_id} TTS 생성 중...")

        try:
            tts_response = client.text_to_speech.convert_with_timestamps(
                voice_id=MATILDA_VOICE_ID,
                text=script_text,
                model_id=model_id,
                output_format="mp3_44100_128",
                apply_text_normalization="on",
            )

            # MP3 저장
            audio_bytes = bytes(tts_response.audio_base64) if isinstance(
                tts_response.audio_base64, (bytes, bytearray)
            ) else __import__("base64").b64decode(tts_response.audio_base64)

            mp3_path.write_bytes(audio_bytes)

            # SRT 생성
            alignment = tts_response.alignment
            if alignment:
                srt_content = _alignment_to_srt({
                    "characters": alignment.characters,
                    "character_start_times_seconds": alignment.character_start_times_seconds,
                    "character_end_times_seconds": alignment.character_end_times_seconds,
                })
            else:
                srt_content = ""
            srt_path.write_text(srt_content, encoding="utf-8")

            result[variant_id] = {"mp3": str(mp3_path), "srt": str(srt_path)}
            logger.info(f"[tts_generator] {variant_id} 완료")

        except Exception as e:
            logger.error(f"[tts_generator] {variant_id} 실패: {e}")
            result[variant_id] = {"error": str(e)}

    logger.info(f"[tts_generator] 전체 완료: {len(result)}개")
    return result
