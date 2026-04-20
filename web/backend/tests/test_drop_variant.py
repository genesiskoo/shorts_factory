"""POST /api/tasks/{id}/drop-variant 검증.

사용자 요구: step5~10 사이에서 선택된 variant를 제외할 수 있어야 함.
pipeline_runner는 selected_variant_ids로 필터링하므로 이 배열 수정만으로 충분.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_drop_variant.py
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
    variants: list[str],
    clips_map: dict[str, list[int]] | None = None,
) -> int:
    with Session(engine) as s:
        t = Task(
            product_name="__DROP_TEST__",
            images=json.dumps([], ensure_ascii=False),
            status=status,
            current_step=current_step,
            selected_variant_ids=json.dumps(variants, ensure_ascii=False),
            selected_clips=json.dumps(clips_map or {}, ensure_ascii=False),
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


def _get_task_state(task_id: int):
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if not t:
            return None
        return {
            "variants": json.loads(t.selected_variant_ids or "[]"),
            "clips": json.loads(t.selected_clips or "{}"),
            "status": t.status.value,
            "step": t.current_step.value if t.current_step else None,
        }


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: 정상 drop — review_tts에서 v3 제외
# ---------------------------------------------------------------------------
print("\n[test 1] review_tts에서 v3_scenario drop")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.review_tts,
    ["v1_informative", "v2_empathy", "v3_scenario"],
    {"v1_informative": [1, 2], "v3_scenario": [1, 3]},
)
res = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v3_scenario"})
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
body = res.json() if res.status_code == 200 else {}
check("dropped = v3_scenario", body.get("dropped") == "v3_scenario")
check("remaining 2개", body.get("remaining") == ["v1_informative", "v2_empathy"],
      f"remaining={body.get('remaining')}")

state = _get_task_state(task_id)
check("DB selected_variant_ids 갱신", state["variants"] == ["v1_informative", "v2_empathy"])
check("DB selected_clips에서 v3 키 제거", "v3_scenario" not in state["clips"])
check("v1_informative clips 보존", state["clips"].get("v1_informative") == [1, 2],
      f"clips={state['clips']}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2: 마지막 1개 drop 시도 → 400
# ---------------------------------------------------------------------------
print("\n[test 2] 최후 1개 drop → 400")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.review_prompts,
    ["v1_informative"],
)
res = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v1_informative"})
check("status 400", res.status_code == 400, f"status={res.status_code}")
state = _get_task_state(task_id)
check("DB 변경 없음", state["variants"] == ["v1_informative"])
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 3: 존재하지 않는 variant_id → 404
# ---------------------------------------------------------------------------
print("\n[test 3] 존재하지 않는 variant_id → 404")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_clips,
    ["v1_informative", "v2_empathy"],
)
res = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v99_nonexistent"})
check("status 404", res.status_code == 404, f"status={res.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 4: 화이트리스트 외 단계 → 409
# ---------------------------------------------------------------------------
print("\n[test 4] select_scripts 단계에서 drop → 409 (체크박스로 해결)")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_scripts,
    ["v1_informative", "v2_empathy"],
)
res = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v2_empathy"})
check("status 409", res.status_code == 409, f"status={res.status_code}")
detail = res.json().get("detail", "") if res.status_code == 409 else ""
check("화이트리스트 안내 포함", "허용" in detail and "review_tts" in detail, f"detail={detail!r}")
check(
    "Enum repr 유출 없음 (select_scripts 표기 정상)",
    "TaskStep" not in detail and "select_scripts" in detail,
)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 5: status=running → 409
# ---------------------------------------------------------------------------
print("\n[test 5] running 상태 drop → 409")

task_id = _make_task(
    TaskStatus.running,
    TaskStep.generating_video,
    ["v1_informative", "v2_empathy"],
)
res = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v2_empathy"})
check("status 409", res.status_code == 409, f"status={res.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 6: 없는 task_id → 404
# ---------------------------------------------------------------------------
print("\n[test 6] 없는 task_id → 404")

res = client.post("/api/tasks/9999999/drop-variant", json={"variant_id": "v1_informative"})
check("status 404", res.status_code == 404, f"status={res.status_code}")


# ---------------------------------------------------------------------------
# Test 7: 연속 drop — 2번 연달아 성공
# ---------------------------------------------------------------------------
print("\n[test 7] 연속 drop (5개 → 3개)")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.preview_timeline,
    ["v1_informative", "v2_empathy", "v3_scenario", "v4_review", "v5_comparison"],
)
res1 = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v4_review"})
check("첫 drop 200", res1.status_code == 200)
res2 = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v2_empathy"})
check("두 번째 drop 200", res2.status_code == 200)
state = _get_task_state(task_id)
check(
    "3개 남음",
    state["variants"] == ["v1_informative", "v3_scenario", "v5_comparison"],
    f"variants={state['variants']}",
)
# 같은 variant 재drop → 404
res3 = client.post(f"/api/tasks/{task_id}/drop-variant", json={"variant_id": "v4_review"})
check("동일 variant 재drop 404", res3.status_code == 404)
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
