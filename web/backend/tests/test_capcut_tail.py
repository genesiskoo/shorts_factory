"""services/capcut_tail.py 검증.

실제 draft_content.json(과거 빌드 산출물) 복사본에 append_tail을 돌려
- tail material 추가
- tail segment 추가
- duration 증가
- idempotent(재실행 시 중복 추가 없음)
를 확인한다. ffprobe가 PATH에 있어야 하며, 프로젝트 루트에
`faimly_month.mp4`가 존재해야 함.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_capcut_tail.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from config import PROJECT_ROOT  # noqa: E402

from services import capcut_tail  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Setup: 기존 draft_content.json 찾아 tmp에 복사
# ---------------------------------------------------------------------------
SAMPLE_DRAFT = None
for p in (PROJECT_ROOT / "output").rglob("draft_content.json"):
    SAMPLE_DRAFT = p
    break

TAIL_FILE = capcut_tail._resolve_tail_file("family_month")


# ---------------------------------------------------------------------------
# Test 1: _resolve_tail_file — family_month 탐색
# ---------------------------------------------------------------------------
print("\n[test 1] _resolve_tail_file")

check("family_month → 파일 존재", TAIL_FILE is not None and TAIL_FILE.is_file(),
      f"path={TAIL_FILE}")
check("none → None", capcut_tail._resolve_tail_file("none") is None)
check("None → None", capcut_tail._resolve_tail_file(None) is None)
check("unknown → None", capcut_tail._resolve_tail_file("unknown_campaign") is None)


# ---------------------------------------------------------------------------
# Test 2: _probe_mp4
# ---------------------------------------------------------------------------
print("\n[test 2] _probe_mp4")

if TAIL_FILE:
    duration_us, width, height = capcut_tail._probe_mp4(TAIL_FILE)
    check("duration > 0", duration_us > 0, f"us={duration_us}")
    check("width = 1080", width == 1080, f"w={width}")
    check("height = 1920", height == 1920, f"h={height}")
else:
    check("tail mp4 missing", False, "skip: TAIL_FILE resolve failed")


# ---------------------------------------------------------------------------
# Test 3: append_tail on real draft copy
# ---------------------------------------------------------------------------
print("\n[test 3] append_tail on real draft")

if SAMPLE_DRAFT and TAIL_FILE:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_proj = Path(tmp) / "fake_project"
        tmp_proj.mkdir()
        dst_draft = tmp_proj / "draft_content.json"
        shutil.copy2(SAMPLE_DRAFT, dst_draft)

        orig_data = json.loads(dst_draft.read_text(encoding="utf-8"))
        orig_duration = int(orig_data.get("duration") or 0)
        orig_video_mats = len(orig_data["materials"]["videos"])
        orig_first_video_track_segs = len(
            next(t for t in orig_data["tracks"] if t.get("type") == "video")
            ["segments"]
        )

        modified = capcut_tail.append_tail(tmp_proj, TAIL_FILE)
        check("첫 append 반환=True", modified is True)

        new_data = json.loads(dst_draft.read_text(encoding="utf-8"))
        new_duration = int(new_data["duration"])
        new_video_mats = len(new_data["materials"]["videos"])
        new_first_video_track_segs = len(
            next(t for t in new_data["tracks"] if t.get("type") == "video")
            ["segments"]
        )

        tail_us, _, _ = capcut_tail._probe_mp4(TAIL_FILE)

        check(
            "duration 증가량 일치",
            new_duration == orig_duration + tail_us,
            f"orig={orig_duration} new={new_duration} tail={tail_us}",
        )
        check("video material +1", new_video_mats == orig_video_mats + 1)
        check(
            "첫 video 트랙 segment +1",
            new_first_video_track_segs == orig_first_video_track_segs + 1,
        )

        # 새 material이 마지막에 들어갔는지 + 속성 확인
        last_mat = new_data["materials"]["videos"][-1]
        check("last material type=video", last_mat.get("type") == "video")
        check(
            "last material name 일치",
            last_mat.get("material_name") == TAIL_FILE.name,
        )
        check("last material has_audio=True", last_mat.get("has_audio") is True)

        # 새 segment가 마지막에 들어갔고 target_timerange.start == orig_duration
        new_video_track = next(
            t for t in new_data["tracks"] if t.get("type") == "video"
        )
        last_seg = new_video_track["segments"][-1]
        check(
            "last segment material_id == new material id",
            last_seg.get("material_id") == last_mat.get("id"),
        )
        check(
            "last segment target start == orig duration",
            last_seg.get("target_timerange", {}).get("start") == orig_duration,
        )
        check(
            "last segment volume=1.0",
            last_seg.get("volume") == 1.0,
        )

        # 백업 파일
        check(
            "draft_content.json.bak 생성됨",
            (dst_draft.with_suffix(".json.bak")).exists(),
        )

        # Test 4: idempotent
        print("\n[test 4] idempotent (2nd call)")
        modified2 = capcut_tail.append_tail(tmp_proj, TAIL_FILE)
        check("2회차 append 반환=False", modified2 is False)
        re_data = json.loads(dst_draft.read_text(encoding="utf-8"))
        check(
            "duration 재증가 없음",
            int(re_data["duration"]) == new_duration,
            f"expected={new_duration} got={int(re_data['duration'])}",
        )
        check(
            "material 개수 유지",
            len(re_data["materials"]["videos"]) == new_video_mats,
        )
else:
    print("  SKIP: 필요 파일 누락")
    check("prerequisites", False, f"SAMPLE_DRAFT={SAMPLE_DRAFT}, TAIL={TAIL_FILE}")


# ---------------------------------------------------------------------------
# Test 5: maybe_append_campaign_tail — campaign=none
# ---------------------------------------------------------------------------
print("\n[test 5] maybe_append_campaign_tail 가드")

if SAMPLE_DRAFT:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_proj = Path(tmp) / "fake_project"
        tmp_proj.mkdir()
        dst_draft = tmp_proj / "draft_content.json"
        shutil.copy2(SAMPLE_DRAFT, dst_draft)
        before = dst_draft.read_text(encoding="utf-8")

        for variant in (None, "none", "", "unknown_campaign"):
            applied = capcut_tail.maybe_append_campaign_tail(tmp_proj, variant)
            check(f"variant={variant!r} → False", applied is False)

        after = dst_draft.read_text(encoding="utf-8")
        check("draft 변경 없음", before == after)

        # 실제 적용 variant
        if TAIL_FILE:
            applied = capcut_tail.maybe_append_campaign_tail(tmp_proj, "family_month")
            check("variant=family_month → True", applied is True)


# ---------------------------------------------------------------------------
# Test 6: append_tail — draft_content.json 없으면 False
# ---------------------------------------------------------------------------
print("\n[test 6] empty project dir")

with tempfile.TemporaryDirectory() as tmp:
    tmp_proj = Path(tmp)
    if TAIL_FILE:
        applied = capcut_tail.append_tail(tmp_proj, TAIL_FILE)
        check("draft 없음 → False", applied is False)


# ---------------------------------------------------------------------------
# 총평
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"TOTAL: {passed}/{total} PASS")
if passed != total:
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    sys.exit(1)
