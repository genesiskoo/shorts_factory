"""사용자 업로드 mp4 검증 (ffprobe 기반).

ffprobe가 PATH에 없으면 graceful skip — 검증 결과를 None/None으로 반환하고
caller가 경고만 표시. 사용자 환경에 ffmpeg가 없을 수 있고, 검증보다 업로드
허용이 더 중요하다.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("web.clip_validator")

# 9:16 ≈ 0.5625. ±0.02로 1080×1920, 720×1280, 540×960 모두 허용.
TARGET_ASPECT = 9.0 / 16.0
ASPECT_TOLERANCE = 0.02
MAX_DURATION_SEC = 60.0
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB


@dataclass
class ProbeResult:
    width: int | None
    height: int | None
    duration_sec: float | None
    aspect_ratio: float | None  # width / height
    is_portrait_9x16: bool | None  # None = 검증 불가
    has_ffprobe: bool


def has_ffprobe() -> bool:
    return shutil.which("ffprobe") is not None


def probe_mp4(path: Path) -> ProbeResult:
    """ffprobe로 width/height/duration 추출. ffprobe 미설치 시 has_ffprobe=False."""
    if not has_ffprobe():
        logger.warning("ffprobe not found in PATH — clip validation skipped")
        return ProbeResult(None, None, None, None, None, False)

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("ffprobe failed for %s: %s", path.name, e)
        return ProbeResult(None, None, None, None, None, True)

    if proc.returncode != 0:
        logger.warning("ffprobe non-zero (%s): %s", path.name, proc.stderr[:200])
        return ProbeResult(None, None, None, None, None, True)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ProbeResult(None, None, None, None, None, True)

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    if not streams:
        return ProbeResult(None, None, None, None, None, True)

    s0 = streams[0]
    w = s0.get("width")
    h = s0.get("height")
    duration_raw = fmt.get("duration") or s0.get("duration")
    try:
        dur = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        dur = None

    aspect = (float(w) / float(h)) if (w and h) else None
    is_portrait = (
        abs(aspect - TARGET_ASPECT) <= ASPECT_TOLERANCE
        if aspect is not None else None
    )
    return ProbeResult(w, h, dur, aspect, is_portrait, True)


def validate_upload(path: Path) -> tuple[ProbeResult, list[str]]:
    """업로드 mp4를 검증한다. 반환: (probe 결과, 거부 사유 목록).

    거부 사유가 비어있으면 통과. caller는 raise HTTPException(422, ...)으로 변환.
    9:16 위반은 거부 사유가 아닌 경고로 처리 (사용자가 의도적으로 다른 비율을
    쓸 수도 있음 — CapCut이 letterbox 처리). 길이 초과는 hard reject.
    """
    rejects: list[str] = []
    if not path.exists():
        rejects.append("uploaded file missing")
        return ProbeResult(None, None, None, None, None, False), rejects

    size = path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        rejects.append(
            f"file too large ({size / 1024 / 1024:.1f}MB > "
            f"{MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB)"
        )

    probe = probe_mp4(path)
    if probe.has_ffprobe:
        if probe.duration_sec is not None and probe.duration_sec > MAX_DURATION_SEC:
            rejects.append(
                f"duration {probe.duration_sec:.1f}s exceeds {MAX_DURATION_SEC:.0f}s limit"
            )
        if probe.width and probe.height:
            if probe.is_portrait_9x16 is False:
                # warn only (CapCut handles non-9:16 with letterbox)
                logger.warning(
                    "uploaded clip %s is not 9:16 (got %dx%d, ratio %.3f)",
                    path.name, probe.width, probe.height, probe.aspect_ratio or 0,
                )
    return probe, rejects
