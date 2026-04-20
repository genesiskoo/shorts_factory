"""이미지=클립 1:1 규약 검증.

- /new POST: image_count × 49 초과 target → 400
- /new POST: target 미제공 → image_count × 45 저장
- pipeline_runner._normalize_strategy: 과다 클립 truncate + 중복 source_image 재할당
- pipeline_runner._materialize_canonical_clips: 캐시 중복 경로 → canonical 파일 복사

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_image_clip_sync.py
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from db import Task, engine, init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from sqlmodel import Session  # noqa: E402

init_db()


# --- Mock background task ---
import services.pipeline_runner as pr  # noqa: E402
import routes.tasks as rt  # noqa: E402


def _noop_script_gen(task_id: int) -> None:
    pass


pr.run_script_generation = _noop_script_gen  # type: ignore[assignment]
rt.run_script_generation = _noop_script_gen  # type: ignore[assignment]


def _delete_task(task_id: int) -> None:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if t:
            s.delete(t)
            s.commit()


def _fake_image() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


def _post_task(
    target: int | None,
    name: str,
    image_n: int,
) -> dict:
    data = {"product_name": name}
    if target is not None:
        data["target_char_count"] = str(target)
    files = [
        ("images", (f"img{i}.jpg", io.BytesIO(_fake_image()), "image/jpeg"))
        for i in range(image_n)
    ]
    res = client.post("/api/tasks", data=data, files=files)
    return {
        "status": res.status_code,
        "body": res.json() if res.status_code < 500 else None,
        "raw": res.text,
    }


# ---------------------------------------------------------------------------
# Test 1: 3 images + target=300 → 400 (147 상한 초과)
# ---------------------------------------------------------------------------
print("\n[test 1] 3 images + target=300 → 400 (상한 147 초과)")
r = _post_task(300, "__IMG_T1__", 3)
check("status 400", r["status"] == 400, f"body={r['raw'][:200]}")
if r["status"] == 400:
    detail = r["body"].get("detail", "")
    check("응답에 '147자' 포함", "147자" in detail, f"detail={detail[:100]}")


# ---------------------------------------------------------------------------
# Test 2: 3 images + target=140 → 201 저장
# ---------------------------------------------------------------------------
print("\n[test 2] 3 images + target=140 → 201 (상한 내)")
r = _post_task(140, "__IMG_T2__", 3)
check("status 201", r["status"] == 201, f"body={r['raw'][:200]}")
if r["status"] == 201:
    tid = r["body"]["task_id"]
    with Session(engine) as s:
        t = s.get(Task, tid)
        check("target=140 저장", t.target_char_count == 140)
    _delete_task(tid)


# ---------------------------------------------------------------------------
# Test 3: 4 images + target 미제공 → 180 기본값 (4×45)
# ---------------------------------------------------------------------------
print("\n[test 3] 4 images + target 미제공 → DB 180 (4×45)")
r = _post_task(None, "__IMG_T3__", 4)
check("status 201", r["status"] == 201)
if r["status"] == 201:
    tid = r["body"]["task_id"]
    with Session(engine) as s:
        t = s.get(Task, tid)
        check("target=180 저장 (image_count*45)",
              t.target_char_count == 180,
              f"got={t.target_char_count}")
    _delete_task(tid)


# ---------------------------------------------------------------------------
# Test 4: 5 images + target=245 → 201 (5×49=245 상한 정확히)
# ---------------------------------------------------------------------------
print("\n[test 4] 5 images + target=245 → 201 (상한 정확히)")
r = _post_task(245, "__IMG_T4__", 5)
check("status 201 (경계값)", r["status"] == 201, f"body={r['raw'][:200]}")
if r["status"] == 201:
    _delete_task(r["body"]["task_id"])


# ---------------------------------------------------------------------------
# Test 5: 5 images + target=246 → 400 (1자 초과)
# ---------------------------------------------------------------------------
print("\n[test 5] 5 images + target=246 → 400 (상한 1자 초과)")
r = _post_task(246, "__IMG_T5__", 5)
check("status 400", r["status"] == 400)


# ---------------------------------------------------------------------------
# Test 6: _normalize_strategy — 과다 클립 truncate
# ---------------------------------------------------------------------------
print("\n[test 6] _normalize_strategy truncate 5→3")

strategy = {
    "variants": [
        {
            "variant_id": "v1_informative",
            "clips": [
                {"clip_num": 1, "source_image": "img_1", "i2v_prompt": "a"},
                {"clip_num": 2, "source_image": "img_2", "i2v_prompt": "b"},
                {"clip_num": 3, "source_image": "img_3", "i2v_prompt": "c"},
                {"clip_num": 4, "source_image": "img_1", "i2v_prompt": "d"},
                {"clip_num": 5, "source_image": "img_2", "i2v_prompt": "e"},
            ],
        },
    ],
}
n = pr._normalize_strategy(strategy, image_count=3)
check("반환 mutated > 0", n > 0)
clips = strategy["variants"][0]["clips"]
check("clips 3개로 truncate", len(clips) == 3, f"got={len(clips)}")
check("clip_num 1,2,3 재번호", [c["clip_num"] for c in clips] == [1, 2, 3])
check("source_image 모두 다름",
      len({c["source_image"] for c in clips}) == 3,
      f"imgs={[c['source_image'] for c in clips]}")


# ---------------------------------------------------------------------------
# Test 7: _normalize_strategy — 중복 source_image 재할당
# ---------------------------------------------------------------------------
print("\n[test 7] _normalize_strategy 중복 img 재할당")

strategy2 = {
    "variants": [
        {
            "variant_id": "v2_empathy",
            "clips": [
                {"clip_num": 1, "source_image": "img_1", "i2v_prompt": "a"},
                {"clip_num": 2, "source_image": "img_1", "i2v_prompt": "b"},
                {"clip_num": 3, "source_image": "img_3", "i2v_prompt": "c"},
            ],
        },
    ],
}
n = pr._normalize_strategy(strategy2, image_count=3)
check("반환 mutated > 0", n > 0)
clips2 = strategy2["variants"][0]["clips"]
imgs = [c["source_image"] for c in clips2]
check("img_1 중복 해소", imgs.count("img_1") == 1, f"imgs={imgs}")
check("3개 고유 img 사용", set(imgs) == {"img_1", "img_2", "img_3"}, f"imgs={imgs}")


# ---------------------------------------------------------------------------
# Test 8: _normalize_strategy — 유효 strategy는 불변
# ---------------------------------------------------------------------------
print("\n[test 8] 유효 strategy 불변 (mutated=0)")

strategy3 = {
    "variants": [
        {
            "variant_id": "v1",
            "clips": [
                {"clip_num": 1, "source_image": "img_1", "i2v_prompt": "a"},
                {"clip_num": 2, "source_image": "img_2", "i2v_prompt": "b"},
                {"clip_num": 3, "source_image": "img_3", "i2v_prompt": "c"},
            ],
        },
    ],
}
n = pr._normalize_strategy(strategy3, image_count=3)
check("mutated = 0", n == 0, f"got={n}")
check("clips 3개 유지", len(strategy3["variants"][0]["clips"]) == 3)


# ---------------------------------------------------------------------------
# Test 9: _materialize_canonical_clips — 중복 경로 복사
# ---------------------------------------------------------------------------
print("\n[test 9] _materialize_canonical_clips 복사 동작")

with tempfile.TemporaryDirectory() as tmp:
    clips_dir = Path(tmp) / "clips"
    clips_dir.mkdir()
    src_file = clips_dir / "clip_v2_empathy_1.mp4"
    src_file.write_bytes(b"SRC")

    # video_generator가 clip 4에 clip 1 파일을 가리키도록 반환한 시나리오
    result = {
        "clip_v2_empathy_1": str(src_file),
        "clip_v2_empathy_4": str(src_file),  # 캐시 중복
    }
    created = pr._materialize_canonical_clips(result, tmp)
    check("created=1", created == 1, f"got={created}")
    dst = clips_dir / "clip_v2_empathy_4.mp4"
    check("canonical 파일 존재", dst.exists())
    check("내용 복사됨", dst.read_bytes() == b"SRC")


# ---------------------------------------------------------------------------
# Test 10: _materialize_canonical_clips — idempotent
# ---------------------------------------------------------------------------
print("\n[test 10] _materialize idempotent")

with tempfile.TemporaryDirectory() as tmp:
    clips_dir = Path(tmp) / "clips"
    clips_dir.mkdir()
    src_file = clips_dir / "clip_v1_1.mp4"
    src_file.write_bytes(b"X")
    dst_existing = clips_dir / "clip_v1_4.mp4"
    dst_existing.write_bytes(b"PREEXISTING")

    result = {
        "clip_v1_1": str(src_file),
        "clip_v1_4": str(src_file),
    }
    created = pr._materialize_canonical_clips(result, tmp)
    check("created=0 (기존 유지)", created == 0)
    check("기존 파일 불변",
          dst_existing.read_bytes() == b"PREEXISTING")


# ---------------------------------------------------------------------------
# Test 11: _materialize_canonical_clips — None/실패 result 스킵
# ---------------------------------------------------------------------------
print("\n[test 11] 실패한 clip (None) 스킵")

with tempfile.TemporaryDirectory() as tmp:
    result = {
        "clip_v1_1": None,
        "clip_v1_2": "nonexistent/path.mp4",
    }
    created = pr._materialize_canonical_clips(result, tmp)
    check("None/누락 경로 스킵 (created=0)", created == 0)


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
