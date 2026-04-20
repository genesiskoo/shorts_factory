"""선제적 상태 전이 검증.

사용자 증상: step6에서 "Veo 영상 생성 시작" 클릭해도 UI 반응 없음.
근본 원인: 라우트가 background task에만 상태 전이를 맡겨서 응답 직후
프론트의 GET 시점에는 DB가 아직 awaiting_user/review_prompts 상태.

이 테스트는 3개 transition에서 `POST /next` (또는 /build-capcut) 응답 즉시
DB가 running/generating_* 으로 전환되어 있는지 확인한다. 실제 Veo/ElevenLabs/
capcut 호출은 발생하지 않도록 pipeline_runner 함수들을 monkeypatch로 무력화.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_eager_transit.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from db import Task, TaskStatus, TaskStep, engine, init_db  # noqa: E402

init_db()

# monkeypatch: pipeline_runner의 background 작업을 no-op으로 대체
# routes/tasks.py가 이들을 직접 import하므로 그 모듈의 속성을 교체해야 함.
from services import pipeline_runner  # noqa: E402

def _noop_tts(task_id, selected_variant_ids):
    print(f"    [noop run_tts_generation] task_id={task_id}")

def _noop_video(task_id):
    print(f"    [noop run_video_generation] task_id={task_id}")

def _noop_capcut(task_id, template_assignments=None, campaign_variant=None):
    print(f"    [noop run_capcut_build] task_id={task_id}")

pipeline_runner.run_tts_generation = _noop_tts
pipeline_runner.run_video_generation = _noop_video
pipeline_runner.run_capcut_build = _noop_capcut

# routes.tasks는 from ... import 로 이미 바인딩되어 있으므로 그쪽도 교체
from routes import tasks as routes_tasks  # noqa: E402

routes_tasks.run_tts_generation = _noop_tts
routes_tasks.run_video_generation = _noop_video
routes_tasks.run_capcut_build = _noop_capcut

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from sqlmodel import Session  # noqa: E402


def _make_task(
    status: TaskStatus,
    current_step: TaskStep | None,
    selected_variant_ids: list[str] | None = None,
    selected_clips: dict[str, list[int]] | None = None,
) -> int:
    with Session(engine) as s:
        t = Task(
            product_name="__EAGER_TRANSIT__",
            images=json.dumps([], ensure_ascii=False),
            status=status,
            current_step=current_step,
            selected_variant_ids=json.dumps(selected_variant_ids or [], ensure_ascii=False),
            selected_clips=json.dumps(selected_clips or {}, ensure_ascii=False),
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


def _get_state(task_id: int) -> tuple[str | None, str | None]:
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if not t:
            return None, None
        step = t.current_step.value if t.current_step else None
        status = t.status.value if t.status else None
        return step, status


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: review_prompts → generating_video 즉시 전이 (step6 증상)
# ---------------------------------------------------------------------------
print("\n[test 1] review_prompts → generating_video 선제 전이")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.review_prompts,
    selected_variant_ids=["v1_informative"],
)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_prompts"})
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
step, status = _get_state(task_id)
check("current_step=generating_video (즉시)", step == "generating_video", f"step={step}")
check("status=running (즉시)", status == "running", f"status={status}")

# 재클릭 시 409 보존
res2 = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_prompts"})
check("재클릭 409", res2.status_code == 409, f"status={res2.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2: select_scripts → select_tts (awaiting_user 유지, TTS 미시작)
# ---------------------------------------------------------------------------
# 참고: 과거에는 select_scripts → generating_tts로 즉시 전이했으나,
# TTS provider 선택 step이 추가되면서 select_scripts는 select_tts로만 이동.
# 실제 선제적 running 전이는 test 2b의 select_tts 단계에서 수행.
print("\n[test 2] select_scripts → select_tts (awaiting_user 유지)")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.select_scripts)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={"step": "select_scripts", "selected_variant_ids": ["v1_informative", "v2_empathy"]},
)
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
step, status = _get_state(task_id)
check("current_step=select_tts", step == "select_tts", f"step={step}")
check("status=awaiting_user (TTS 미시작)", status == "awaiting_user", f"status={status}")
with Session(engine) as s:
    t = s.get(Task, task_id)
    svi = json.loads(t.selected_variant_ids or "[]")
check("selected_variant_ids 저장됨", svi == ["v1_informative", "v2_empathy"], f"got={svi}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2b: select_tts → generating_tts 즉시 전이 (새로운 선제 전이 지점)
# ---------------------------------------------------------------------------
print("\n[test 2b] select_tts → generating_tts 선제 전이")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    selected_variant_ids=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={
        "step": "select_tts",
        "tts_provider": "typecast",
        "tts_options": {"voice_id": "tc_x", "audio_format": "mp3"},
    },
)
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
step, status = _get_state(task_id)
check("current_step=generating_tts (즉시)", step == "generating_tts", f"step={step}")
check("status=running (즉시)", status == "running", f"status={status}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 3: build-capcut → building_capcut 즉시 전이 (잠복 fix)
# ---------------------------------------------------------------------------
print("\n[test 3] build-capcut → building_capcut 선제 전이")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_template,
    selected_variant_ids=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/build-capcut",
    json={"campaign_variant": "none", "template_assignments": {}},
)
check("status 200", res.status_code == 200, f"status={res.status_code}, body={res.text}")
step, status = _get_state(task_id)
check("current_step=building_capcut (즉시)", step == "building_capcut", f"step={step}")
check("status=running (즉시)", status == "running", f"status={status}")

# 재클릭 시 409
res2 = client.post(
    f"/api/tasks/{task_id}/build-capcut",
    json={"campaign_variant": "none", "template_assignments": {}},
)
check("재클릭 409", res2.status_code == 409, f"status={res2.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 4: 정상 전이(선제 없음)는 회귀 없는지 확인
# ---------------------------------------------------------------------------
print("\n[test 4] review_tts → review_prompts 회귀 확인 (status 유지)")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.review_tts)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_tts"})
check("status 200", res.status_code == 200)
step, status = _get_state(task_id)
check("current_step=review_prompts", step == "review_prompts", f"step={step}")
check("status=awaiting_user (running 전환 없음)", status == "awaiting_user", f"status={status}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 5: running 상태 재호출 시 409 (기존 가드 무결성)
# ---------------------------------------------------------------------------
print("\n[test 5] running 상태에 POST /next → 409")

task_id = _make_task(TaskStatus.running, TaskStep.generating_video)
res = client.post(f"/api/tasks/{task_id}/next", json={"step": "review_prompts"})
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
