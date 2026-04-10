"""
capcut_builder.py 테스트

기존 PoC 데이터(Sony XM5)를 사용하여 CapCut 프로젝트 생성.
생성된 프로젝트를 CapCut 데스크톱에서 열어서 정상 동작 확인.
"""

from pathlib import Path
from scripts.capcut_builder import build_capcut_project

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
TEMPLATE = ROOT / "templates" / "capcut_template"


def main():
    # 테스트용 파일 존재 여부 사전 체크 (없어도 JSON 생성은 진행)
    clips = [
        OUTPUT / "earbuds_zoom.mp4",
        OUTPUT / "earbuds_float.mp4",
        OUTPUT / "earbuds_reveal.mp4",
    ]
    tts = OUTPUT / "tts" / "sony_xm5.mp3"
    bgm = ROOT / "kornevmusic-epic-478847.mp3"

    for p in clips + [tts, bgm]:
        status = "OK" if p.exists() else "NOT FOUND (CapCut에서 오류 표시 가능)"
        print(f"  {'[OK]' if p.exists() else '[!!]'} {p.name}: {status}")

    print()

    result = build_capcut_project(
        template_dir=TEMPLATE,
        video_clips=clips,
        tts_path=tts,
        tts_duration_sec=18.0,
        srt_entries=[
            {"text": "테스트 자막 1", "start": 0.0,  "end": 3.0},
            {"text": "테스트 자막 2", "start": 3.0,  "end": 6.0},
            {"text": "테스트 자막 3", "start": 6.0,  "end": 9.0},
            {"text": "테스트 자막 4", "start": 9.0,  "end": 12.0},
            {"text": "테스트 자막 5", "start": 12.0, "end": 15.0},
            {"text": "테스트 자막 6", "start": 15.0, "end": 18.0},
        ],
        bgm_path=bgm,
        product_name="Sony WF-1000XM5 무선 이어폰",
        project_name="test_capcut_builder",
    )

    print(f"\n프로젝트 생성 완료: {result}")
    print("\n─── 검증 체크리스트 ───────────────────────────────────────")
    print("CapCut 데스크톱에서 'test_capcut_builder' 프로젝트를 열어서 확인:")
    checks = [
        "프로젝트가 목록에 나타나는가",
        "크래시 없이 정상 로드되는가",
        "영상 클립 3개가 타임라인에 순서대로 배치되어 있는가",
        "상품명 텍스트가 'Sony WF-1000XM5 무선 이어폰'으로 바뀌어 있는가",
        "SRT 자막 6개가 각각 올바른 시간대에 표시되는가",
        "TTS 오디오가 재생되는가 (파일 존재 시)",
        "BGM이 영상 전체 길이로 재생되는가 (파일 존재 시)",
        "배너/CTA/로고 등 고정 요소가 정상 표시되는가",
        "렌더링(내보내기) → MP4 정상 출력되는가",
    ]
    for i, c in enumerate(checks, 1):
        print(f"  {i}. [ ] {c}")

    # JSON 구조 기본 검증
    print("\n─── JSON 구조 자동 검증 ────────────────────────────────────")
    _verify_json(result)


def _verify_json(project_dir: Path):
    import json

    dc_path = project_dir / "draft_content.json"
    draft = json.loads(dc_path.read_text(encoding="utf-8"))

    errors = []

    # 루트 duration 확인 (18+2=20초 → 20_000_000)
    expected_total = int((18.0 + 2.0) * 1_000_000)
    if draft["duration"] != expected_total:
        errors.append(f"root duration 불일치: {draft['duration']} != {expected_total}")
    else:
        print(f"  [OK] root duration = {draft['duration']} μs")

    # Track 0: 3개 segments
    segs0 = draft["tracks"][0]["segments"]
    if len(segs0) != 3:
        errors.append(f"Track 0 segments count: {len(segs0)} != 3")
    else:
        print(f"  [OK] Track 0 segments = {len(segs0)}개")

    # Track 0 segments 시간 연속성 확인
    for i, seg in enumerate(segs0):
        tr = seg["target_timerange"]
        print(f"       Clip {i}: start={tr['start']} dur={tr['duration']}")

    # Track 9: 6개 자막 segments
    segs9 = draft["tracks"][9]["segments"]
    if len(segs9) != 6:
        errors.append(f"Track 9 segments count: {len(segs9)} != 6")
    else:
        print(f"  [OK] Track 9 (자막) segments = {len(segs9)}개")

    # Track 6 product name
    mid6 = draft["tracks"][6]["segments"][0]["material_id"]
    for t in draft["materials"]["texts"]:
        if t["id"] == mid6:
            import json as j
            content = j.loads(t["content"])
            if content["text"] == "Sony WF-1000XM5 무선 이어폰":
                print(f"  [OK] Track 6 상품명: '{content['text']}'")
            else:
                errors.append(f"Track 6 상품명 불일치: '{content['text']}'")
            break

    # Track 10 TTS
    seg10 = draft["tracks"][10]["segments"][0]
    tts_dur = int(18.0 * 1_000_000)
    if seg10["target_timerange"]["duration"] == tts_dur:
        print(f"  [OK] Track 10 TTS duration = {tts_dur} μs")
    else:
        errors.append(f"Track 10 duration 불일치: {seg10['target_timerange']['duration']} != {tts_dur}")

    # Track 11 BGM duration
    seg11 = draft["tracks"][11]["segments"][0]
    if seg11["target_timerange"]["duration"] == expected_total:
        print(f"  [OK] Track 11 BGM duration = {expected_total} μs")
    else:
        errors.append(f"Track 11 duration 불일치: {seg11['target_timerange']['duration']} != {expected_total}")

    if errors:
        print("\n[FAIL] 검증 실패:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("\n[PASS] 모든 JSON 구조 검증 통과!")


if __name__ == "__main__":
    main()
