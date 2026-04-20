"""CapCut 프로젝트 맨 뒤에 campaign 전용 tail mp4를 붙이는 post-processor.

`agents/*`, `scripts/*`는 read-only이므로 `draft_content.json`을 후처리해
기존 빌더 규칙을 지킨다. 사용자가 프로젝트 루트에 `{campaign}.mp4`를
배치해두면 `maybe_append_campaign_tail`이 해당 variant의 드래프트 끝에
video 세그먼트(+ 임베디드 오디오)로 한 번만 추가한다.

시간 단위: CapCut draft_content.json은 모든 timerange를 **microseconds**로
저장한다(예: duration=25421020 → 25.42s).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from config import PROJECT_ROOT

logger = logging.getLogger("web.capcut_tail")

# campaign_variant → PROJECT_ROOT 하위 파일명 후보 (첫 번째 존재하는 파일 사용)
# 오타/철자 변형을 허용해 실제 저장된 파일을 찾는다.
_TAIL_CANDIDATES: dict[str, list[str]] = {
    "family_month": ["family_month.mp4", "faimly_month.mp4"],
    # 추후 추가:
    # "children_day": ["children_day.mp4"],
    # "parents_day": ["parents_day.mp4"],
    # "fast_delivery": ["fast_delivery.mp4"],
}


def _resolve_tail_file(campaign_variant: str | None) -> Path | None:
    if not campaign_variant or campaign_variant == "none":
        return None
    for name in _TAIL_CANDIDATES.get(campaign_variant, []):
        p = (PROJECT_ROOT / name).resolve()
        if p.is_file():
            return p
    return None


def _probe_mp4(path: Path) -> tuple[int, int, int]:
    """ffprobe로 (duration_us, width, height) 반환.

    FFmpeg가 PATH에 있다는 전제. 없으면 CalledProcessError 발생.
    """
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    dur_sec = float(stream.get("duration") or 0.0)
    duration_us = int(round(dur_sec * 1_000_000))
    width = int(stream.get("width") or 1080)
    height = int(stream.get("height") or 1920)
    if duration_us <= 0:
        raise RuntimeError(f"ffprobe returned duration<=0 for {path}")
    return duration_us, width, height


def _uuid_upper() -> str:
    """CapCut 스타일 대문자 UUID."""
    return str(uuid.uuid4()).upper()


def _build_tail_material(
    tail_path: Path, duration_us: int, width: int, height: int
) -> dict:
    """videos[]에 추가할 material dict. 기존 video 클립 스키마와 동일."""
    return {
        "id": _uuid_upper(),
        "unique_id": "",
        "type": "video",
        "duration": duration_us,
        "path": str(tail_path).replace("\\", "/"),
        "media_path": "",
        "local_id": "",
        "has_audio": True,
        "reverse_path": "",
        "intensifies_path": "",
        "reverse_intensifies_path": "",
        "intensifies_audio_path": "",
        "cartoon_path": "",
        "width": width,
        "height": height,
        "category_id": "",
        "category_name": "local",
        "material_id": "",
        "material_name": tail_path.name,
        "material_url": "",
        "crop": {
            "lower_left_x": 0.0, "lower_left_y": 1.0,
            "lower_right_x": 1.0, "lower_right_y": 1.0,
            "upper_left_x": 0.0, "upper_left_y": 0.0,
            "upper_right_x": 1.0, "upper_right_y": 0.0,
        },
        "crop_ratio": "free",
        "audio_fade": None,
        "crop_scale": 1.0,
        "extra_type_option": 0,
        "stable": {
            "stable_level": 0, "matrix_path": "",
            "time_range": {"start": 0, "duration": 0},
        },
        "matting": {
            "flag": 0, "path": "", "interactiveTime": [],
            "has_use_quick_brush": False, "strokes": [],
            "has_use_quick_eraser": False, "expansion": 0,
            "feather": 0, "reverse": False,
            "custom_matting_id": "", "enable_matting_stroke": False,
        },
        "source": 0,
        "source_platform": 0,
        "formula_id": "",
    }


def _build_tail_segment(
    material_id: str, duration_us: int, start_us: int
) -> dict:
    """track[video][0].segments에 append 할 세그먼트. volume=1.0으로
    임베디드 오디오(프로모션 사운드) 그대로 재생."""
    return {
        "id": _uuid_upper(),
        "source_timerange": {"start": 0, "duration": duration_us},
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "is_loop": False,
        "is_tone_modify": False,
        "reverse": False,
        "intensifies_audio": False,
        "cartoon": False,
        "volume": 1.0,
        "last_nonzero_volume": 1.0,
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        },
        "uniform_scale": {"on": True, "value": 1.0},
        "material_id": material_id,
        "extra_material_refs": [],
        "render_index": 0,
        "keyframe_refs": [],
        "enable_lut": True,
        "enable_adjust": True,
        "enable_hsl": False,
        "visible": True,
        "group_id": "",
        "enable_color_curves": True,
        "enable_hsl_curves": True,
        "track_render_index": 0,
        "hdr_settings": {"mode": 1, "intensity": 1.0, "nits": 1000},
        "enable_color_wheels": True,
        "track_attribute": 0,
        "is_placeholder": False,
        "template_id": "",
        "enable_smart_color_adjust": False,
        "template_scene": "default",
        "common_keyframes": [],
        "caption_info": None,
        "responsive_layout": {
            "enable": False,
            "target_follow": "",
            "size_layout": 0,
            "horizontal_pos_layout": 0,
            "vertical_pos_layout": 0,
        },
        "enable_color_match_adjust": False,
        "enable_color_correct_adjust": False,
        "enable_adjust_mask": False,
        "raw_segment_id": "",
        "lyric_keyframes": None,
        "enable_video_mask": True,
        "digital_human_template_group_id": "",
        "color_correct_alg_result": "",
        "source": "segmentsourcenormal",
        "enable_mask_stroke": False,
        "enable_mask_shadow": False,
        "enable_color_adjust_pro": False,
    }


def append_tail(project_dir: Path, tail_path: Path) -> bool:
    """draft_content.json in-place 수정. 이미 tail 추가되어 있으면 skip.

    반환: 실제로 수정이 일어났으면 True.
    """
    draft = project_dir / "draft_content.json"
    if not draft.exists():
        logger.warning("append_tail skip: %s not found", draft)
        return False

    data = json.loads(draft.read_text(encoding="utf-8"))

    # idempotent 가드: 같은 파일명 + video 타입이 이미 있으면 skip
    tail_name = tail_path.name
    for v in data.get("materials", {}).get("videos", []):
        if v.get("material_name") == tail_name and v.get("type") == "video":
            logger.info(
                "append_tail skip: %s already in %s", tail_name, project_dir.name
            )
            return False

    duration_us, width, height = _probe_mp4(tail_path)
    current_duration = int(data.get("duration") or 0)

    material = _build_tail_material(tail_path, duration_us, width, height)
    segment = _build_tail_segment(material["id"], duration_us, current_duration)

    data.setdefault("materials", {}).setdefault("videos", []).append(material)

    tracks = data.setdefault("tracks", [])
    video_track = next((t for t in tracks if t.get("type") == "video"), None)
    if video_track is None:
        logger.warning("append_tail: no video track in %s", draft)
        return False
    video_track.setdefault("segments", []).append(segment)

    data["duration"] = current_duration + duration_us

    # 최초 수정 시 1회만 백업
    backup = draft.with_suffix(".json.bak")
    if not backup.exists():
        shutil.copy2(draft, backup)

    draft.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(
        "append_tail: %s + %s (%.2fs) → total %.2fs",
        project_dir.name, tail_name,
        duration_us / 1_000_000,
        (current_duration + duration_us) / 1_000_000,
    )
    return True


def maybe_append_campaign_tail(
    project_dir: Path,
    campaign_variant: str | None,
) -> bool:
    """campaign_variant에 대응하는 tail mp4가 PROJECT_ROOT에 있으면 append.

    반환: 실제로 수정이 일어났으면 True. 매핑 없음/파일 없음/예외 모두 False.
    """
    tail = _resolve_tail_file(campaign_variant)
    if tail is None:
        return False
    try:
        return append_tail(project_dir, tail)
    except Exception as e:
        logger.exception(
            "append_campaign_tail failed: project=%s variant=%s err=%s",
            project_dir, campaign_variant, e,
        )
        return False
