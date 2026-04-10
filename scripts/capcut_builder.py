"""
capcut_builder.py — CapCut 프로젝트 JSON 빌더

템플릿 draft_content.json을 동적 데이터(영상 클립, TTS, SRT 자막, 상품명)로
치환하여 CapCut 데스크톱이 인식하는 프로젝트 폴더를 생성한다.

직접 JSON dict 조작 방식 (pyCapCut 불필요).
"""

import copy
import json
import shutil
import uuid
from pathlib import Path

CAPCUT_PROJECTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"

# Track 인덱스 상수
TRACK_VIDEO = 0       # 메인 영상 클립
TRACK_FIXED_START = 1 # 고정 요소 시작 (배너/CTA배경/로고/스티커)
TRACK_FIXED_END = 5   # 고정 요소 끝
TRACK_PRODUCT_NAME = 6
TRACK_CTA = 7
TRACK_HAEOEJIKGU = 8
TRACK_SUBTITLE = 9
TRACK_TTS = 10
TRACK_BGM = 11


def _new_id() -> str:
    """CapCut 형식의 대문자 UUID4를 반환한다."""
    return str(uuid.uuid4()).upper()


def _new_local_id() -> str:
    """CapCut local_material_id 형식의 소문자 UUID4를 반환한다."""
    return str(uuid.uuid4())


def _to_posix(path: Path) -> str:
    """Windows 경로를 CapCut이 인식하는 슬래시 형식으로 변환한다."""
    return path.as_posix()


def _update_text_material_content(
    material: dict,
    new_text: str,
    adjust_font_size: bool = False,
) -> None:
    """
    materials.texts 엔트리의 content(JSON 문자열)을 업데이트한다.

    - text 교체
    - styles[].range를 새 텍스트 길이에 맞게 재계산
      - 단일 스타일: range = [0, len(new_text)]
      - 다중 스타일: 마지막 style의 range[1]을 len(new_text)로 설정
    - adjust_font_size=True이고 새 텍스트가 원본 대비 1.5배 이상 길면
      모든 스타일의 size를 80%로 축소
    """
    content = json.loads(material["content"])
    original_text = content.get("text", "")
    content["text"] = new_text

    new_len = len(new_text)
    styles = content.get("styles", [])

    if styles:
        if len(styles) == 1:
            styles[0]["range"] = [0, new_len]
        else:
            # 다중 스타일: 마지막 style의 end만 새 길이로 맞춤
            styles[-1]["range"][1] = new_len

        if adjust_font_size and len(original_text) > 0:
            ratio = new_len / len(original_text)
            if ratio >= 1.5:
                for style in styles:
                    if "size" in style:
                        style["size"] = max(6, int(style["size"] * 0.8))

    material["content"] = json.dumps(content, ensure_ascii=False)


def build_capcut_project(
    template_dir: "str | Path",
    video_clips: "list[str | Path]",
    tts_path: "str | Path",
    tts_duration_sec: float,
    srt_entries: "list[dict]",
    bgm_path: "str | Path",
    product_name: str,
    project_name: str,
    cta_text: str = "구매링크는 프로필 링크 참고",
) -> Path:
    """
    CapCut 프로젝트 폴더를 생성하고 경로를 반환한다.

    Parameters
    ----------
    template_dir    : 템플릿 폴더 (draft_content.json 포함)
    video_clips     : I2V 클립 경로 리스트 (3~4개)
    tts_path        : TTS MP3 절대 경로
    tts_duration_sec: TTS 길이(초)
    srt_entries     : [{"text": str, "start": float, "end": float}, ...] (초 단위)
    bgm_path        : BGM MP3 절대 경로
    product_name    : 상품명 텍스트
    project_name    : CapCut 프로젝트명 (폴더명으로도 사용)
    cta_text        : CTA 텍스트 (Track 7)
    """
    template_dir = Path(template_dir)
    tts_path = Path(tts_path)
    bgm_path = Path(bgm_path)
    video_clips = [Path(c) for c in video_clips]

    if not video_clips:
        raise ValueError("video_clips는 최소 1개 이상이어야 합니다.")

    # ──────────────────────────────────────────────
    # 1. 템플릿 로드
    # ──────────────────────────────────────────────
    draft_json_path = template_dir / "draft_content.json"
    draft = json.loads(draft_json_path.read_text(encoding="utf-8"))

    # ──────────────────────────────────────────────
    # 2. 총 길이 계산 (μs)
    # ──────────────────────────────────────────────
    total_duration_us = int((tts_duration_sec + 2.0) * 1_000_000)
    tts_duration_us = int(tts_duration_sec * 1_000_000)

    # ──────────────────────────────────────────────
    # 3. Track 0: 비디오 클립 교체
    # ──────────────────────────────────────────────
    # 기존 Track 0 segments의 material_id 수집
    old_video_mat_ids = {
        seg["material_id"] for seg in draft["tracks"][TRACK_VIDEO]["segments"]
    }

    # 클론용 비디오 material 템플릿 확보 (제거 전에 저장)
    video_mat_template = None
    for v in draft["materials"]["videos"]:
        if v["id"] in old_video_mat_ids:
            video_mat_template = copy.deepcopy(v)
            break

    if video_mat_template is None:
        raise RuntimeError("Track 0에 대응하는 video material을 찾을 수 없습니다.")

    # 기존 클립 materials 제거 (로고 등 다른 video materials 유지)
    draft["materials"]["videos"] = [
        v for v in draft["materials"]["videos"]
        if v["id"] not in old_video_mat_ids
    ]

    # 클론용 세그먼트 템플릿 확보
    video_seg_template = copy.deepcopy(draft["tracks"][TRACK_VIDEO]["segments"][0])

    # Track 0 segments 비우기
    draft["tracks"][TRACK_VIDEO]["segments"] = []

    # 균등 분할 계산
    n_clips = len(video_clips)
    clip_dur_base = total_duration_us // n_clips
    remainder = total_duration_us - clip_dur_base * n_clips

    for i, clip_path in enumerate(video_clips):
        mat_id = _new_id()
        seg_id = _new_id()

        # 마지막 클립에 나머지 시간 추가
        clip_dur = clip_dur_base + (remainder if i == n_clips - 1 else 0)
        start_us = i * clip_dur_base

        # 새 video material 생성
        new_mat = copy.deepcopy(video_mat_template)
        new_mat["id"] = mat_id
        new_mat["path"] = _to_posix(clip_path)
        new_mat["material_name"] = clip_path.name
        new_mat["duration"] = clip_dur
        new_mat["local_material_id"] = _new_local_id()
        new_mat["unique_id"] = ""
        new_mat["origin_material_id"] = ""
        new_mat["request_id"] = ""
        new_mat["aigc_history_id"] = ""
        new_mat["aigc_item_id"] = ""
        # video_algorithm의 time_range도 업데이트
        if isinstance(new_mat.get("video_algorithm"), dict):
            new_mat["video_algorithm"]["time_range"] = {"start": 0, "duration": clip_dur}

        draft["materials"]["videos"].append(new_mat)

        # 새 segment 생성
        new_seg = copy.deepcopy(video_seg_template)
        new_seg["id"] = seg_id
        new_seg["material_id"] = mat_id
        new_seg["target_timerange"] = {"start": start_us, "duration": clip_dur}
        new_seg["source_timerange"] = {"start": 0, "duration": clip_dur}
        new_seg["render_timerange"] = {"start": 0, "duration": 0}
        new_seg["extra_material_refs"] = []  # 새 클립은 기존 효과 refs 미적용

        draft["tracks"][TRACK_VIDEO]["segments"].append(new_seg)

    # ──────────────────────────────────────────────
    # 4. Track 6: 상품명 텍스트 치환
    # ──────────────────────────────────────────────
    product_name_mid = draft["tracks"][TRACK_PRODUCT_NAME]["segments"][0]["material_id"]
    for text_mat in draft["materials"]["texts"]:
        if text_mat["id"] == product_name_mid:
            _update_text_material_content(text_mat, product_name, adjust_font_size=True)
            break

    # ──────────────────────────────────────────────
    # 5. Track 7: CTA 텍스트 치환 (선택적)
    # ──────────────────────────────────────────────
    if cta_text and draft["tracks"][TRACK_CTA]["segments"]:
        cta_mid = draft["tracks"][TRACK_CTA]["segments"][0]["material_id"]
        for text_mat in draft["materials"]["texts"]:
            if text_mat["id"] == cta_mid:
                _update_text_material_content(text_mat, cta_text, adjust_font_size=True)
                break

    # ──────────────────────────────────────────────
    # 6. Track 9: SRT 자막 동적 생성
    # ──────────────────────────────────────────────
    # 기존 자막 material_id 수집
    old_sub_ids = {
        seg["material_id"] for seg in draft["tracks"][TRACK_SUBTITLE]["segments"]
    }

    # 클론용 자막 material/segment 템플릿 확보
    sub_mat_template = None
    for text_mat in draft["materials"]["texts"]:
        if text_mat["id"] in old_sub_ids:
            sub_mat_template = copy.deepcopy(text_mat)
            break

    if sub_mat_template is None:
        raise RuntimeError("Track 9에 대응하는 자막 text material을 찾을 수 없습니다.")

    sub_seg_template = copy.deepcopy(draft["tracks"][TRACK_SUBTITLE]["segments"][0])

    # 기존 자막 materials 제거
    draft["materials"]["texts"] = [
        t for t in draft["materials"]["texts"]
        if t["id"] not in old_sub_ids
    ]

    # Track 9 segments 비우기
    draft["tracks"][TRACK_SUBTITLE]["segments"] = []

    # srt_entries → 새 자막 segments/materials
    for entry in srt_entries:
        mat_id = _new_id()
        seg_id = _new_id()

        start_us = int(entry["start"] * 1_000_000)
        end_us = int(entry["end"] * 1_000_000)
        dur_us = end_us - start_us

        # 새 text material (폰트/스타일 유지, text + id만 교체)
        new_mat = copy.deepcopy(sub_mat_template)
        new_mat["id"] = mat_id
        new_mat["recognize_text"] = entry["text"]
        new_mat["words"] = []
        new_mat["current_words"] = []
        _update_text_material_content(new_mat, entry["text"])

        draft["materials"]["texts"].append(new_mat)

        # 새 segment
        new_seg = copy.deepcopy(sub_seg_template)
        new_seg["id"] = seg_id
        new_seg["material_id"] = mat_id
        new_seg["target_timerange"] = {"start": start_us, "duration": dur_us}
        new_seg["source_timerange"] = None

        draft["tracks"][TRACK_SUBTITLE]["segments"].append(new_seg)

    # ──────────────────────────────────────────────
    # 7. Track 10: TTS 오디오 교체
    # ──────────────────────────────────────────────
    tts_mid = draft["tracks"][TRACK_TTS]["segments"][0]["material_id"]
    for audio_mat in draft["materials"]["audios"]:
        if audio_mat["id"] == tts_mid:
            audio_mat["path"] = _to_posix(tts_path)
            audio_mat["name"] = tts_path.name
            audio_mat["duration"] = tts_duration_us
            break

    seg_tts = draft["tracks"][TRACK_TTS]["segments"][0]
    seg_tts["target_timerange"] = {"start": 0, "duration": tts_duration_us}
    seg_tts["source_timerange"] = {"start": 0, "duration": tts_duration_us}

    # ──────────────────────────────────────────────
    # 8. Track 11: BGM 오디오 교체
    # ──────────────────────────────────────────────
    bgm_mid = draft["tracks"][TRACK_BGM]["segments"][0]["material_id"]
    for audio_mat in draft["materials"]["audios"]:
        if audio_mat["id"] == bgm_mid:
            audio_mat["path"] = _to_posix(bgm_path)
            audio_mat["name"] = bgm_path.name
            # material duration은 실제 파일 길이 — 변경하지 않음
            break

    seg_bgm = draft["tracks"][TRACK_BGM]["segments"][0]
    seg_bgm["target_timerange"] = {"start": 0, "duration": total_duration_us}
    seg_bgm["source_timerange"] = {"start": 0, "duration": total_duration_us}

    # ──────────────────────────────────────────────
    # 9. 고정 요소 duration 일괄 업데이트 (Track 1~5, 7~8)
    # ──────────────────────────────────────────────
    fixed_tracks = list(range(TRACK_FIXED_START, TRACK_FIXED_END + 1)) + [TRACK_CTA, TRACK_HAEOEJIKGU]
    for track_idx in fixed_tracks:
        if track_idx >= len(draft["tracks"]):
            continue
        for seg in draft["tracks"][track_idx]["segments"]:
            seg["target_timerange"]["duration"] = total_duration_us
            if seg.get("source_timerange") is not None:
                seg["source_timerange"]["duration"] = total_duration_us

    # ──────────────────────────────────────────────
    # 10. 루트 duration 업데이트
    # ──────────────────────────────────────────────
    draft["duration"] = total_duration_us

    # ──────────────────────────────────────────────
    # 11. CapCut 프로젝트 폴더 저장
    # ──────────────────────────────────────────────
    project_dir = CAPCUT_PROJECTS / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # draft_content.json 저장
    (project_dir / "draft_content.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 부속 파일 복사
    aux_files = [
        "draft_meta_info.json",
        "draft_settings",
        "draft_virtual_store.json",
        "timeline_layout.json",
        "draft_biz_config.json",
        "draft_agency_config.json",
    ]
    for fname in aux_files:
        src = template_dir / fname
        if src.exists():
            shutil.copy2(src, project_dir / fname)

    # draft_meta_info.json 프로젝트명 업데이트
    meta_path = project_dir / "draft_meta_info.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["draft_name"] = project_name
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"[capcut_builder] 프로젝트 생성 완료: {project_dir}")
    return project_dir
