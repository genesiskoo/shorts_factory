"""agents/capcut_builder.py — ⑧ 편집자 래퍼

scripts/capcut_builder.py의 build_capcut_project()를 pipeline 인터페이스로 감싼다.
기존 scripts/capcut_builder.py는 수정하지 않는다.
"""

import logging
import re
import sys
from pathlib import Path

# scripts/ 경로 추가
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from capcut_builder import build_capcut_project  # type: ignore

logger = logging.getLogger(__name__)

# BGM 기본 경로 (프로젝트 루트의 mp3)
_DEFAULT_BGM = Path(__file__).parent.parent / "kornevmusic-epic-478847.mp3"
_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "capcut_template"


def _parse_srt(srt_path: Path) -> list[dict]:
    """SRT 파일 → [{"text": str, "start": float, "end": float}] 변환."""
    entries = []
    if not srt_path.exists():
        return entries

    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        # lines[1] = "00:00:00,000 --> 00:00:01,500"
        time_match = re.match(
            r"(\d+:\d+:\d+,\d+)\s+-->\s+(\d+:\d+:\d+,\d+)", lines[1]
        )
        if not time_match:
            continue
        text = " ".join(lines[2:])
        entries.append({
            "text": text,
            "start": _srt_ts_to_sec(time_match.group(1)),
            "end": _srt_ts_to_sec(time_match.group(2)),
        })

    return entries


def _srt_ts_to_sec(ts: str) -> float:
    """'HH:MM:SS,mmm' → 초 float."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def _get_mp3_duration(mp3_path: Path) -> float:
    """MP3 길이 추정 (mutagen 없으면 20초 기본값)."""
    try:
        from mutagen.mp3 import MP3
        return MP3(str(mp3_path)).info.length
    except Exception:
        # 대략 추정: 파일 크기 기반 (128kbps 기준)
        try:
            size_bytes = mp3_path.stat().st_size
            return size_bytes / (128 * 1024 / 8)
        except Exception:
            return 20.0


def run(
    audio_dir: str,
    clips_dir: str,
    scripts: dict,
    strategy: dict,
    output_dir: str,
) -> None:
    """각 variant별로 CapCut 프로젝트 생성."""

    logger.info("[capcut_builder] 시작")

    audio_path = Path(audio_dir)
    clips_path = Path(clips_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # template 디렉토리 확인
    template_dir = _TEMPLATE_DIR
    if not template_dir.exists():
        logger.warning(f"[capcut_builder] 템플릿 없음: {template_dir} — 스킵")
        return

    # scripts를 variant_id → script dict로 인덱싱
    script_map = {s["variant_id"]: s for s in scripts.get("scripts", [])}

    variants = strategy.get("variants", [])

    for var in variants:
        variant_id = var.get("variant_id", "unknown")
        logger.info(f"[capcut_builder] {variant_id} 프로젝트 생성 중...")

        # 클립 정렬: timeline 순서 (intro → middle → climax → outro)
        timeline_order = {"intro": 0, "middle": 1, "climax": 2, "outro": 3}
        sorted_clips = sorted(
            var.get("clips", []),
            key=lambda c: timeline_order.get(c.get("timeline", "middle"), 1),
        )

        video_clips = []
        for clip in sorted_clips:
            clip_key = f"clip_{variant_id}_{clip.get('clip_num', 0)}"
            mp4 = clips_path / f"{clip_key}.mp4"
            if mp4.exists():
                video_clips.append(str(mp4))
            else:
                logger.warning(f"[capcut_builder] 클립 없음: {mp4.name}")

        if not video_clips:
            logger.warning(f"[capcut_builder] {variant_id} — 클립 없음, 스킵")
            continue

        # TTS + SRT
        mp3_path = audio_path / f"{variant_id}.mp3"
        srt_path = audio_path / f"{variant_id}.srt"

        if not mp3_path.exists():
            logger.warning(f"[capcut_builder] TTS 없음: {mp3_path.name}, 스킵")
            continue

        tts_duration = _get_mp3_duration(mp3_path)
        srt_entries = _parse_srt(srt_path)

        # 대본에서 상품명 추출
        script = script_map.get(variant_id, {})
        product_name = (
            scripts.get("product_name")
            or script.get("title", variant_id)
        )

        try:
            project_path = build_capcut_project(
                template_dir=template_dir,
                video_clips=video_clips,
                tts_path=mp3_path,
                tts_duration_sec=tts_duration,
                srt_entries=srt_entries,
                bgm_path=_DEFAULT_BGM,
                product_name=product_name,
                project_name=variant_id,
                cta_text="구매링크는 프로필 링크 참고",
            )
            logger.info(f"[capcut_builder] {variant_id} 완료: {project_path}")
        except Exception as e:
            logger.error(f"[capcut_builder] {variant_id} 실패: {e}")

    logger.info("[capcut_builder] 전체 완료")
