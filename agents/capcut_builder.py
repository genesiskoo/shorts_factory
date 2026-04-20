"""agents/capcut_builder.py — ⑧ 편집자 래퍼

scripts/capcut_builder.py::build_capcut_project()를 pipeline 인터페이스로 감싼다.
"""

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

# scripts/ 경로 추가
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from capcut_builder import build_capcut_project  # type: ignore


def _sanitize_project_name(name: str) -> str:
    """CapCut 프로젝트 폴더명으로 안전한 문자열 반환.

    Windows 파일명 금지 문자(/ \\ : * ? " < > |) 제거, 경로 탈출 차단(..),
    양 끝 공백 trim, 너무 길면 80자로 컷. 한글/공백은 유지.
    """
    s = str(name or "").strip()
    s = s.replace("..", "_")
    for ch in '/\\:*?"<>|':
        s = s.replace(ch, "_")
    s = re.sub(r"\s+", " ", s).strip(" _")
    return s[:80] or "project"


def _build_project_name(product_name: str | None, variant_id: str) -> str:
    """`{product_name}_{variant_id}` 형식 생성. product_name 누락/공백 시 variant_id만."""
    vid = _sanitize_project_name(variant_id)
    prod_raw = (product_name or "").strip()
    if not prod_raw:
        return vid
    prod = _sanitize_project_name(prod_raw)
    # sanitize 후 fallback("project")만 남는다면 product_name은 사실상 의미 없음
    if not prod or prod == "project":
        return vid
    return f"{prod}_{vid}"

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
    """MP3 길이(초) 측정. ffprobe → mutagen 순. 둘 다 실패 시 RuntimeError.

    이전엔 둘 다 실패 시 파일 크기 / 128kbps 추정으로 fallback했으나,
    ElevenLabs/Typecast가 320kbps mp3를 출력하면 2.5배 부풀린 값을 반환해
    capcut 빌드의 root duration을 왜곡(예: 22.55s mp3 → 55.23s 추정)했다.
    silent 추정 fallback을 완전히 제거하고 명시적 실패로 전환.
    """
    if shutil.which("ffprobe"):
        try:
            proc = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json", str(mp3_path),
                ],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode == 0:
                dur_str = (json.loads(proc.stdout).get("format") or {}).get("duration")
                if dur_str:
                    return float(dur_str)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError,
                ValueError, json.JSONDecodeError) as e:
            logger.warning("ffprobe failed for %s: %s — trying mutagen", mp3_path.name, e)

    try:
        from mutagen.mp3 import MP3
        return MP3(str(mp3_path)).info.length
    except Exception as e:
        raise RuntimeError(
            f"mp3 duration 측정 실패 ({mp3_path.name}): "
            f"ffprobe·mutagen 모두 사용 불가. ffprobe 설치 또는 "
            f"`pip install mutagen` 필요. 마지막 에러: {e}"
        ) from e


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

        units = var.get("scenes") or var.get("clips") or []
        timeline_order = {"intro": 0, "middle": 1, "climax": 2, "outro": 3}

        def _sort_key(u: dict) -> tuple[int, int]:
            n = u.get("scene_num") if u.get("scene_num") is not None else u.get("clip_num")
            if isinstance(n, int):
                return (0, n)
            return (1, timeline_order.get(u.get("timeline", "middle"), 1))

        sorted_units = sorted(units, key=_sort_key)

        video_clips = []
        for u in sorted_units:
            num = u.get("scene_num") if u.get("scene_num") is not None else u.get("clip_num", 0)
            clip_key = f"clip_{variant_id}_{num}"
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

        # 프로젝트 폴더명: {product_name}_{variant_id} — CapCut UI에서 식별 가능
        project_name = _build_project_name(
            scripts.get("product_name") or script.get("title"),
            variant_id,
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
                project_name=project_name,
                cta_text="구매링크는 프로필 링크 참고",
            )
            logger.info(f"[capcut_builder] {variant_id} 완료: {project_path}")
        except Exception as e:
            logger.error(f"[capcut_builder] {variant_id} 실패: {e}")

    logger.info("[capcut_builder] 전체 완료")
