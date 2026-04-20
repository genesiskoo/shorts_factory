"""DELETE /api/tasks/{id} 엔드포인트 실사용 검증 스크립트.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_delete_task.py

확인 범위:
1. 정상 삭제 (awaiting_user) → DB row + uploads + output_dir 정리
2. 존재하지 않는 task_id → 404
3. running 상태 삭제 → warning 문구 반환
4. 경로 탈출 시도 (output_dir이 PROJECT_ROOT/output 밖) → 삭제 안 됨
5. uploads 밖의 경로가 images에 섞여 있어도 삭제 안 됨
6. 삭제 후 list 응답에서 사라졌는지
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401 — sys.path + ensure dirs
from config import OUTPUT_DIR, UPLOADS_DIR  # noqa: E402
from db import Task, TaskStatus, TaskStep, engine, init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from sqlmodel import Session  # noqa: E402

init_db()


def _make_task(
    product_name: str,
    status: TaskStatus = TaskStatus.awaiting_user,
    current_step: TaskStep | None = TaskStep.select_scripts,
    images: list[str] | None = None,
    output_dir: str | None = None,
) -> int:
    with Session(engine) as s:
        t = Task(
            product_name=product_name,
            images=json.dumps(images or [], ensure_ascii=False),
            status=status,
            current_step=current_step,
            output_dir=output_dir,
            created_at=datetime.utcnow(),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        return t.id


def _create_fake_uploads(task_id: int, count: int) -> list[str]:
    """UPLOADS_DIR 안에 실제 파일 생성 후 절대경로 리스트 반환."""
    paths: list[str] = []
    for i in range(count):
        p = UPLOADS_DIR / f"{task_id}_{i}_delete_test.jpg"
        p.write_bytes(b"fake jpg bytes")
        paths.append(str(p.resolve()))
    return paths


def _create_fake_output(product_name: str) -> Path:
    d = OUTPUT_DIR / product_name
    (d / "audio").mkdir(parents=True, exist_ok=True)
    (d / "clips").mkdir(parents=True, exist_ok=True)
    (d / "scripts_final.json").write_text("{}", encoding="utf-8")
    (d / "audio" / "v1_informative.mp3").write_bytes(b"fake mp3")
    (d / "clips" / "clip_v1_informative_1.mp4").write_bytes(b"fake mp4")
    return d.resolve()


def _task_exists(task_id: int) -> bool:
    with Session(engine) as s:
        return s.get(Task, task_id) is not None


results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}: {detail}")


# ---------------------------------------------------------------------------
# Test 1: 정상 삭제 (awaiting_user)
# ---------------------------------------------------------------------------
print("\n[test 1] 정상 삭제 (awaiting_user)")

client = TestClient(app)
product = "__DELTEST_normal__"
out_dir = _create_fake_output(product)
task_id = _make_task(
    product,
    status=TaskStatus.awaiting_user,
    current_step=TaskStep.select_scripts,
    output_dir=str(out_dir),
)
img_paths = _create_fake_uploads(task_id, 3)
with Session(engine) as s:
    t = s.get(Task, task_id)
    t.images = json.dumps(img_paths, ensure_ascii=False)
    s.add(t)
    s.commit()

res = client.delete(f"/api/tasks/{task_id}")
check("status 200", res.status_code == 200, f"status={res.status_code}")
body = res.json()
check("removed_images=3", body.get("removed_images") == 3, f"body={body}")
check("output_removed=True", body.get("output_removed") is True)
check("was_running=False", body.get("was_running") is False)
check("warning=None", body.get("warning") is None)
check("DB row 삭제됨", not _task_exists(task_id))
check(
    "업로드 파일 전부 삭제됨",
    all(not Path(p).exists() for p in img_paths),
)
check("output_dir 삭제됨", not out_dir.exists())


# ---------------------------------------------------------------------------
# Test 2: 없는 task_id → 404
# ---------------------------------------------------------------------------
print("\n[test 2] 존재하지 않는 task_id")

res = client.delete("/api/tasks/9999999")
check("status 404", res.status_code == 404, f"status={res.status_code}")


# ---------------------------------------------------------------------------
# Test 3: running 상태 → warning 포함
# ---------------------------------------------------------------------------
print("\n[test 3] running 상태 삭제 → warning 필드")

product = "__DELTEST_running__"
out_dir = _create_fake_output(product)
task_id = _make_task(
    product,
    status=TaskStatus.running,
    current_step=TaskStep.generating_video,
    output_dir=str(out_dir),
)
img_paths = _create_fake_uploads(task_id, 2)
with Session(engine) as s:
    t = s.get(Task, task_id)
    t.images = json.dumps(img_paths, ensure_ascii=False)
    s.add(t)
    s.commit()

res = client.delete(f"/api/tasks/{task_id}")
body = res.json()
check("status 200", res.status_code == 200)
check("was_running=True", body.get("was_running") is True)
check(
    "warning 문구 존재",
    bool(body.get("warning")) and "취소되지" in (body.get("warning") or ""),
    f"warning={body.get('warning')}",
)
check("DB row 삭제됨", not _task_exists(task_id))


# ---------------------------------------------------------------------------
# Test 4: 경로 탈출 방어 (output_dir이 PROJECT_ROOT/output 밖)
# ---------------------------------------------------------------------------
print("\n[test 4] output_dir 경로 탈출 시도")

# 시스템 다른 폴더에 가짜 파일 생성
tmp_evil = Path(tempfile.mkdtemp(prefix="__DELTEST_evil__"))
(tmp_evil / "precious.txt").write_text("do not delete me")
evil_file = tmp_evil / "precious.txt"

task_id = _make_task(
    "__DELTEST_evil_output__",
    status=TaskStatus.failed,
    output_dir=str(tmp_evil),  # output 폴더 밖!
)

res = client.delete(f"/api/tasks/{task_id}")
body = res.json()
check("status 200", res.status_code == 200)
check(
    "OUTPUT_DIR 외부 경로는 삭제 거부",
    evil_file.exists(),
    f"output_removed={body.get('output_removed')}, evil_survived={evil_file.exists()}",
)
check(
    "output_removed=False (가드로 차단)",
    body.get("output_removed") is False,
)
check(
    "DB row는 그래도 삭제됨",
    not _task_exists(task_id),
)
# cleanup
if tmp_evil.exists():
    shutil.rmtree(tmp_evil, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 5: UPLOADS 밖의 경로가 images에 섞여도 삭제 안 됨
# ---------------------------------------------------------------------------
print("\n[test 5] UPLOADS 밖의 이미지 경로는 삭제 거부")

outside_dir = Path(tempfile.mkdtemp(prefix="__DELTEST_outside_img__"))
outside_img = outside_dir / "outside.jpg"
outside_img.write_bytes(b"outside")

task_id = _make_task(
    "__DELTEST_outside_img__",
    status=TaskStatus.failed,
    images=[str(outside_img.resolve())],
)

res = client.delete(f"/api/tasks/{task_id}")
body = res.json()
check("status 200", res.status_code == 200)
check(
    "outside 이미지 보존 (uploads 외)",
    outside_img.exists(),
    f"removed_images={body.get('removed_images')}",
)
check(
    "removed_images=0",
    body.get("removed_images") == 0,
)
shutil.rmtree(outside_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 6: list 응답에서 사라졌는지
# ---------------------------------------------------------------------------
print("\n[test 6] list 응답 확인")

task_id = _make_task(
    "__DELTEST_list__",
    status=TaskStatus.awaiting_user,
    current_step=TaskStep.select_scripts,
)
res_before = client.get("/api/tasks")
ids_before = {t["id"] for t in res_before.json()["tasks"]}
check("task_id 생성 직후 리스트에 포함", task_id in ids_before)

client.delete(f"/api/tasks/{task_id}")
res_after = client.get("/api/tasks")
ids_after = {t["id"] for t in res_after.json()["tasks"]}
check("삭제 후 리스트에서 제거", task_id not in ids_after)


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
            print(f"  FAIL  {name}  ({detail})")
    sys.exit(1)
