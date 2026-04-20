"""POST /api/tasks/{id}/upload-clip + clip_sources + regenerate-clip force 검증.

ffprobe 사용 가능 여부에 따라 일부 케이스는 skip-or-warn.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_upload_clip.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from db import Task, TaskStatus, TaskStep, engine, init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from services import clip_sources as _cs  # noqa: E402
from services.clip_validator import has_ffprobe  # noqa: E402
from sqlmodel import Session  # noqa: E402

init_db()

client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


def _make_task(out_dir: Path, step: TaskStep = TaskStep.select_clips) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    # 최소 strategy.json: variant 1개 + clip 1개
    (out_dir / "strategy.json").write_text(
        json.dumps({
            "variants": [
                {
                    "variant_id": "v1_informative",
                    "clips": [
                        {"clip_num": 1, "source_image": "img_1", "i2v_prompt": "x"},
                        {"clip_num": 2, "source_image": "img_2", "i2v_prompt": "y"},
                    ],
                }
            ]
        }),
        encoding="utf-8",
    )
    with Session(engine) as s:
        t = Task(
            product_name=out_dir.name,
            images=json.dumps([], ensure_ascii=False),
            status=TaskStatus.awaiting_user,
            current_step=step,
            output_dir=str(out_dir),
            created_at=datetime.utcnow(),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        return t.id


def _cleanup(task_id: int) -> None:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if t:
            s.delete(t)
            s.commit()


def _fake_mp4_bytes(size: int = 4096) -> bytes:
    # ffprobe가 거부할 수 있는 더미. validate_upload는 ffprobe 실패 시
    # 거부 사유를 반환하지 않고 통과시킨다 (probe 결과 None만 반환).
    # 따라서 ffprobe가 있어도 has_ffprobe=True + width/height/duration None →
    # rejects 비어있음 → 200 OK.
    return b"\x00\x00\x00\x20ftypmp42" + b"\x00" * (size - 16)


# ---------------------------------------------------------------------------
# Test 1: 정상 업로드 (가짜 mp4) → 200 + clip_sources 기록
# ---------------------------------------------------------------------------
print("\n[test 1] 정상 업로드")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t1"
    tid = _make_task(out)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "1"},
            files={"file": ("test.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("status 200", r.status_code == 200, f"got={r.status_code} body={r.text[:200]}")
        body = r.json() if r.status_code == 200 else {}
        check("saved_filename clip_v1_informative_1.mp4",
              body.get("saved_filename") == "clip_v1_informative_1.mp4",
              f"got={body.get('saved_filename')}")
        check("ffprobe_skipped boolean",
              isinstance(body.get("ffprobe_skipped"), bool), "")

        # clips 디렉토리에 파일 저장됐는지
        target = out / "clips" / "clip_v1_informative_1.mp4"
        check("mp4 파일 생성", target.exists(), f"path={target}")

        # clip_sources.json에 user 기록
        sources = _cs.load(out)
        entry = sources.get("v1_informative_1")
        check("clip_sources에 user 기록",
              entry is not None and entry.get("source") == "user",
              f"entry={entry}")
        check("original_filename 기록",
              entry and entry.get("original_filename") == "test.mp4",
              "")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 2: 잘못된 mime → 400
# ---------------------------------------------------------------------------
print("\n[test 2] 잘못된 mime → 400")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t2"
    tid = _make_task(out)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "1"},
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        check("status 400", r.status_code == 400, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 3: 존재하지 않는 variant_id → 404
# ---------------------------------------------------------------------------
print("\n[test 3] 존재하지 않는 variant_id → 404")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t3"
    tid = _make_task(out)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v99_unknown", "clip_num": "1"},
            files={"file": ("x.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("status 404", r.status_code == 404, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 4: 존재하지 않는 clip_num → 404
# ---------------------------------------------------------------------------
print("\n[test 4] 존재하지 않는 clip_num → 404")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t4"
    tid = _make_task(out)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "99"},
            files={"file": ("x.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("status 404", r.status_code == 404, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 5: clip_num <= 0 → 422 (Field(ge=1))
# ---------------------------------------------------------------------------
print("\n[test 5] clip_num=0 → 422")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t5"
    tid = _make_task(out)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "0"},
            files={"file": ("x.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("status 422", r.status_code == 422, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 6: 잘못된 단계(select_scripts)에서 업로드 → 409
# ---------------------------------------------------------------------------
print("\n[test 6] 단계 위반 → 409")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t6"
    tid = _make_task(out, step=TaskStep.select_scripts)
    try:
        r = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "1"},
            files={"file": ("x.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("status 409", r.status_code == 409, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 7: regenerate-clip이 user 클립을 force=False면 거부
# ---------------------------------------------------------------------------
print("\n[test 7] regenerate-clip user clip 보호")

# Mock background task to avoid actual Veo call
import services.pipeline_runner as pr
import routes.tasks as rt


def _noop_regen(task_id: int, variant_id: str, clip_num: int) -> None:
    pass


pr.regenerate_clip = _noop_regen  # type: ignore[assignment]
rt.regenerate_clip = _noop_regen  # type: ignore[assignment]


with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t7"
    tid = _make_task(out)
    try:
        # 먼저 user 업로드
        r0 = client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "1"},
            files={"file": ("user.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        check("upload 200", r0.status_code == 200, f"got={r0.status_code}")

        # regenerate force=False (기본) → 409
        r1 = client.post(
            f"/api/tasks/{tid}/regenerate-clip",
            json={"variant_id": "v1_informative", "clip_num": 1},
        )
        check("force=False 거부 409", r1.status_code == 409, f"got={r1.status_code}")
        check("error에 'user' 포함",
              "user" in (r1.json().get("detail", "") if r1.status_code == 409 else ""),
              "")

        # force=True → 200 (실제 재생성은 mock이라 실행 안 됨)
        r2 = client.post(
            f"/api/tasks/{tid}/regenerate-clip",
            json={"variant_id": "v1_informative", "clip_num": 1, "force": True},
        )
        check("force=True 허용 200", r2.status_code == 200, f"got={r2.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 8: clip_sources 모듈 단위
# ---------------------------------------------------------------------------
print("\n[test 8] clip_sources 모듈 단위")

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    check("미존재 시 빈 dict", _cs.load(p) == {}, "")

    e = _cs.mark_user_upload(
        p, "v2_empathy", 3,
        original_filename="hi.mp4",
        duration_sec=5.5, width=1080, height=1920,
    )
    check("mark_user_upload 결과", e["source"] == "user", f"got={e['source']}")
    check("is_user_clip True",
          _cs.is_user_clip(p, "v2_empathy", 3), "")
    check("is_user_clip 다른 클립 False",
          not _cs.is_user_clip(p, "v2_empathy", 4), "")

    _cs.mark_veo(p, "v2_empathy", 3, "veo-3.1-fast-generate-preview")
    check("mark_veo 덮어쓰기",
          not _cs.is_user_clip(p, "v2_empathy", 3),
          "user→veo 전환")

    loaded = _cs.load(p)
    check("저장 후 로드 일관성",
          loaded["v2_empathy_3"]["model"] == "veo-3.1-fast-generate-preview",
          "")


# ---------------------------------------------------------------------------
# Test 9: TaskDetailResp에 clip_sources 노출
# ---------------------------------------------------------------------------
print("\n[test 9] GET /tasks/{id} → clip_sources")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t9"
    tid = _make_task(out)
    try:
        # user 업로드로 sources 생성
        client.post(
            f"/api/tasks/{tid}/upload-clip",
            data={"variant_id": "v1_informative", "clip_num": "2"},
            files={"file": ("u.mp4", _fake_mp4_bytes(), "video/mp4")},
        )
        r = client.get(f"/api/tasks/{tid}")
        check("status 200", r.status_code == 200, f"got={r.status_code}")
        body = r.json() if r.status_code == 200 else {}
        sources = body.get("clip_sources", {})
        check("clip_sources 노출",
              "v1_informative_2" in sources and
              sources["v1_informative_2"].get("source") == "user",
              f"got={sources}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# 총평
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"ffprobe available: {has_ffprobe()}")
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"TOTAL: {passed}/{total} PASS")
if passed != total:
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    sys.exit(1)
