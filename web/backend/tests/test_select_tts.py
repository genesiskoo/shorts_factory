"""select_tts 단계 + TTS provider 선택 검증.

플로우:
  select_scripts → /next(step=select_scripts, selected_variant_ids=[...]) → select_tts
  select_tts     → /next(step=select_tts, tts_provider, tts_options)     → generating_tts
  BACK: select_tts → select_scripts (이미 _BACK_TRANSITIONS 확장)
  DROP: select_tts에서도 허용

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_select_tts.py
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
    variants: list[str] | None = None,
    tts_provider: str | None = None,
    tts_options: dict | None = None,
) -> int:
    with Session(engine) as s:
        t = Task(
            product_name="__SELECT_TTS_TEST__",
            images=json.dumps([], ensure_ascii=False),
            status=status,
            current_step=current_step,
            selected_variant_ids=(
                json.dumps(variants, ensure_ascii=False)
                if variants is not None
                else None
            ),
            tts_provider=tts_provider,
            tts_options=(
                json.dumps(tts_options, ensure_ascii=False)
                if tts_options is not None
                else None
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


def _get_task(task_id: int) -> Task | None:
    with Session(engine) as s:
        return s.get(Task, task_id)


# --- Mock background TTS (실제 외부 호출 방지) ---------------------------------

import services.pipeline_runner as pr  # noqa: E402

_bg_calls: list[tuple[int, list[str]]] = []


def _fake_run_tts_generation(task_id: int, selected: list[str]) -> None:
    _bg_calls.append((task_id, selected))
    # 실제 호출은 하지 않고 DB만 review_tts로 전이 (UI 흐름 검증용)
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if t:
            t.status = TaskStatus.awaiting_user
            t.current_step = TaskStep.review_tts
            s.add(t)
            s.commit()


pr.run_tts_generation = _fake_run_tts_generation  # type: ignore[assignment]

# routes.tasks 모듈도 이미 import된 시점이므로 그곳의 참조도 교체
import routes.tasks as rt  # noqa: E402
rt.run_tts_generation = _fake_run_tts_generation  # type: ignore[assignment]


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: select_scripts → select_tts 전이 (TTS 미시작)
# ---------------------------------------------------------------------------
print("\n[test 1] select_scripts → select_tts (TTS 미시작)")

task_id = _make_task(TaskStatus.awaiting_user, TaskStep.select_scripts)
_bg_calls.clear()
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={
        "step": "select_scripts",
        "selected_variant_ids": ["v1_informative", "v2_empathy"],
    },
)
check("status 200", res.status_code == 200, f"body={res.text}")
body = res.json() if res.status_code == 200 else {}
check("next_step=select_tts", body.get("next_step") == "select_tts")

t = _get_task(task_id)
check("DB current_step=select_tts", t.current_step == TaskStep.select_tts)
check("DB status=awaiting_user", t.status == TaskStatus.awaiting_user)
check("selected_variant_ids 저장", json.loads(t.selected_variant_ids or "[]") == [
    "v1_informative", "v2_empathy"
])
check("background TTS 미호출", len(_bg_calls) == 0, f"calls={_bg_calls}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 2: select_tts + typecast → generating_tts 전이 + background task 등록
# ---------------------------------------------------------------------------
print("\n[test 2] select_tts + typecast → generating_tts")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
_bg_calls.clear()
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={
        "step": "select_tts",
        "tts_provider": "typecast",
        "tts_options": {
            "voice_id": "tc_test123",
            "model": "ssfm-v30",
            "emotion_type": "smart",
            "audio_tempo": 1.1,
            "audio_format": "mp3",
        },
    },
)
check("status 200", res.status_code == 200, f"body={res.text}")
body = res.json() if res.status_code == 200 else {}
check("next_step=generating_tts", body.get("next_step") == "generating_tts")

t = _get_task(task_id)
check("DB tts_provider=typecast", t.tts_provider == "typecast")
saved_opts = json.loads(t.tts_options or "{}")
check("DB tts_options.voice_id", saved_opts.get("voice_id") == "tc_test123")
check("DB tts_options.audio_tempo", saved_opts.get("audio_tempo") == 1.1)
check("background TTS 호출됨", len(_bg_calls) == 1, f"calls={_bg_calls}")
if _bg_calls:
    check("bg called with correct variants", _bg_calls[0][1] == ["v1_informative"])
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 3: select_tts + elevenlabs → 전이 OK (options 없어도 됨)
# ---------------------------------------------------------------------------
print("\n[test 3] select_tts + elevenlabs → generating_tts")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
_bg_calls.clear()
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={"step": "select_tts", "tts_provider": "elevenlabs"},
)
check("status 200", res.status_code == 200, f"body={res.text}")
t = _get_task(task_id)
check("DB tts_provider=elevenlabs", t.tts_provider == "elevenlabs")
check("bg 호출됨", len(_bg_calls) == 1)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 4: select_tts — provider 누락 → 400
# ---------------------------------------------------------------------------
print("\n[test 4] provider 누락 → 400")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={"step": "select_tts"},
)
check("status 400", res.status_code == 400, f"status={res.status_code}")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 5: typecast + voice_id 누락 → 400
# ---------------------------------------------------------------------------
print("\n[test 5] typecast + voice_id 누락 → 400")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={"step": "select_tts", "tts_provider": "typecast", "tts_options": {}},
)
check("status 400", res.status_code == 400, f"body={res.text}")
detail = res.json().get("detail", "") if res.status_code == 400 else ""
check("voice_id 요구 메시지", "voice_id" in detail)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 6: typecast + tempo 범위 벗어남 → 400
# ---------------------------------------------------------------------------
print("\n[test 6] audio_tempo 3.0 → 400 (0.5~2.0)")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={
        "step": "select_tts",
        "tts_provider": "typecast",
        "tts_options": {"voice_id": "tc_x", "audio_tempo": 3.0},
    },
)
check("status 400", res.status_code == 400)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 7: status=running → 409
# ---------------------------------------------------------------------------
print("\n[test 7] running 상태 → 409")

task_id = _make_task(
    TaskStatus.running,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/next",
    json={
        "step": "select_tts",
        "tts_provider": "typecast",
        "tts_options": {"voice_id": "tc_x"},
    },
)
check("status 409", res.status_code == 409)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 8: back — select_tts → select_scripts
# ---------------------------------------------------------------------------
print("\n[test 8] back: select_tts → select_scripts")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative", "v2_empathy"],
)
res = client.post(f"/api/tasks/{task_id}/back")
check("status 200", res.status_code == 200, f"body={res.text}")
body = res.json() if res.status_code == 200 else {}
check("next_step=select_scripts", body.get("next_step") == "select_scripts")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 9: drop-variant — select_tts 단계에서 허용
# ---------------------------------------------------------------------------
print("\n[test 9] drop-variant @ select_tts")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative", "v2_empathy", "v3_scenario"],
)
res = client.post(
    f"/api/tasks/{task_id}/drop-variant",
    json={"variant_id": "v2_empathy"},
)
check("status 200", res.status_code == 200, f"status={res.status_code}")
body = res.json() if res.status_code == 200 else {}
check("remaining = 2개", body.get("remaining") == ["v1_informative", "v3_scenario"])
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 10: GET /api/tasks/{id} 가 tts_provider / tts_options 노출
# ---------------------------------------------------------------------------
print("\n[test 10] GET /api/tasks/{id} 응답에 tts_provider/tts_options 포함")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
    tts_provider="typecast",
    tts_options={"voice_id": "tc_abc", "audio_tempo": 1.2},
)
res = client.get(f"/api/tasks/{task_id}")
check("status 200", res.status_code == 200)
body = res.json()
check("tts_provider=typecast", body.get("tts_provider") == "typecast")
opts = body.get("tts_options") or {}
check("tts_options dict", opts.get("voice_id") == "tc_abc")
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 11: voices 프록시 — elevenlabs 즉시 반환
# ---------------------------------------------------------------------------
print("\n[test 11] GET /api/tts/voices?provider=elevenlabs")

res = client.get("/api/tts/voices?provider=elevenlabs")
check("status 200", res.status_code == 200, f"body={res.text[:200]}")
body = res.json()
check("provider=elevenlabs", body.get("provider") == "elevenlabs")
voices = body.get("voices") or []
check("voices 1개", len(voices) == 1 and voices[0].get("voice_name") == "Matilda")


# ---------------------------------------------------------------------------
# Test 12: voices 프록시 — 알 수 없는 provider → 400
# ---------------------------------------------------------------------------
print("\n[test 12] voices unknown provider → 400")

res = client.get("/api/tts/voices?provider=foo")
check("status 400", res.status_code == 400)


# ---------------------------------------------------------------------------
# Test 13: preview — sample_text 초과 → 400
# ---------------------------------------------------------------------------
print("\n[test 13] preview sample_text 초과 400")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
long_text = "가" * 300
res = client.post(
    f"/api/tasks/{task_id}/tts-preview",
    json={
        "provider": "typecast",
        "options": {"voice_id": "tc_x"},
        "sample_text": long_text,
    },
)
check("status 400", res.status_code == 400)
_delete_task(task_id)


# ---------------------------------------------------------------------------
# Test 14: preview — elevenlabs 미지원 → 400
# ---------------------------------------------------------------------------
print("\n[test 14] preview provider=elevenlabs → 400 (MVP 미지원)")

task_id = _make_task(
    TaskStatus.awaiting_user,
    TaskStep.select_tts,
    variants=["v1_informative"],
)
res = client.post(
    f"/api/tasks/{task_id}/tts-preview",
    json={"provider": "elevenlabs", "options": {}, "sample_text": "hi"},
)
check("status 400", res.status_code == 400)
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
