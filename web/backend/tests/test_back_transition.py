"""POST /api/tasks/{id}/back 역방향 전이 검증.

사용자 요구: step6(review_prompts)에서 "← 이전" 클릭 시 step5(review_tts)로 복귀.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_back_transition.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from db import Task, TaskStatus, TaskStep, engine, init_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from sqlmodel import Session  # noqa: E402

init_db()


def _make_task(status: TaskStatus, current_step: TaskStep | None) -> int:
    with Session(engine) as s:
        t = Task(
            product_name="__BACK_TRANSIT__",
            images=json.dumps([], ensure_ascii=False),
            status=status,
            current_step=current_step,
            created_at=datetime.utcnow(),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        return t.id


def _delete_task(task_id: int) -> None:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if t:
            s.delete(t)
            s.commit()


def _get_step(task_id: int) -> str | None:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        return t.current_step.value if t and t.current_step else None


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: 정상 역방향 — review_prompts → review_tts
# ---------------------------------------------------------------------------
print("\n[test 1] review_prompts → review_tts")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.review_prompts)
res = client.post(f"/api/tasks/{task_id}/back")
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
body = res.json() if res.status_code == 200 else {}
check("next_step = review_tts", body.get("next_step") == "review_tts", f"body={body}")
check("DB current_step 실제 변경", _get_step(task_id) == "review_tts",
      f"actual={_get_step(task_id)}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2: 화이트리스트 외 단계 → 409
# ---------------------------------------------------------------------------
print("\n[test 2] 화이트리스트 외 (select_scripts) → 409")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.select_scripts)
res = client.post(f"/api/tasks/{task_id}/back")
check("status 409", res.status_code == 409, f"status={res.status_code}")
detail = res.json().get("detail", "") if res.status_code == 409 else ""
check(
    "Enum repr 유출 없음 (select_scripts 표기 정상)",
    "TaskStep" not in detail and "select_scripts" in detail,
    f"detail={detail!r}",
)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 3: running 상태 → 409
# ---------------------------------------------------------------------------
print("\n[test 3] status=running → 409")

task_id = _make_task(TaskStatus.running, TaskStep.review_prompts)
res = client.post(f"/api/tasks/{task_id}/back")
check("status 409", res.status_code == 409, f"status={res.status_code}")
detail = res.json().get("detail", "") if res.status_code == 409 else ""
check(
    "Enum repr 유출 없음 (running 표기 정상)",
    "TaskStatus" not in detail and "running" in detail,
    f"detail={detail!r}",
)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 4: 없는 task_id → 404
# ---------------------------------------------------------------------------
print("\n[test 4] 없는 task_id → 404")

res = client.post("/api/tasks/9999999/back")
check("status 404", res.status_code == 404, f"status={res.status_code}")


# ---------------------------------------------------------------------------
# Test 5: current_step=None → 409 (전이 대상 없음)
# ---------------------------------------------------------------------------
print("\n[test 5] current_step=None → 409")

task_id = _make_task(TaskStatus.awaiting_user, None)
res = client.post(f"/api/tasks/{task_id}/back")
check("status 409", res.status_code == 409, f"status={res.status_code}")
_delete_task(task_id)


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
