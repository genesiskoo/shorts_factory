"""POST /api/tasks/{id}/next body {"step":"review_tts"} 정상성 검증.

사용자 증상: 프론트에서 step5 → step6 전이가 안 됨.
이 스크립트는 백엔드 단독으로 전이가 정상인지 확인 → 가설 확정용.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_review_tts_transition.py
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


def _make_task(
    status: TaskStatus,
    current_step: TaskStep | None,
) -> int:
    with Session(engine) as s:
        t = Task(
            product_name="__REVIEW_TTS_TRANSIT__",
            images=json.dumps([], ensure_ascii=False),
            status=status,
            current_step=current_step,
            selected_variant_ids=json.dumps(
                ["v1_informative"], ensure_ascii=False
            ),
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
    print(f"  [{mark}] {name}: {detail}")


# ---------------------------------------------------------------------------
# Test 1: review_tts → review_prompts (정상 흐름)
# ---------------------------------------------------------------------------
print("\n[test 1] review_tts → review_prompts")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.review_tts)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_tts"})
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
body = res.json() if res.status_code == 200 else {}
check(
    "next_step = review_prompts",
    body.get("next_step") == "review_prompts",
    f"next_step={body.get('next_step')}",
)
check(
    "DB current_step 변경됨",
    _get_step(task_id) == "review_prompts",
    f"actual={_get_step(task_id)}",
)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2: 잘못된 step value → 422 (Pydantic enum)
# ---------------------------------------------------------------------------
print("\n[test 2] 잘못된 step value → 422")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.review_tts)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "invalid_value"})
check("status 422", res.status_code == 422, f"status={res.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 3: status=running 일 때 호출 → 409 (_assert_status 가드)
# ---------------------------------------------------------------------------
print("\n[test 3] running 상태 호출 → 409")

task_id = _make_task(TaskStatus.running, TaskStep.review_tts)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_tts"})
check("status 409", res.status_code == 409, f"status={res.status_code}")
detail = res.json().get("detail", "") if res.status_code == 409 else ""
check(
    "Enum repr 유출 없음 (running 표기 정상)",
    "TaskStatus" not in detail and "running" in detail,
    f"detail={detail!r}",
)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 4: 응답 next_step 직렬화 (string)
# ---------------------------------------------------------------------------
print("\n[test 4] 응답 next_step 직렬화")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.review_tts)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_tts"})
raw = res.text
check(
    "JSON 응답에 'review_prompts' 문자열 존재",
    "\"next_step\":\"review_prompts\"" in raw,
    f"raw={raw}",
)
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
            print(f"  FAIL  {name}  ({detail})")
    sys.exit(1)
