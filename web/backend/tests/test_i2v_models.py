"""i2v 모델 카탈로그 + 폴백 체인 + 라우트 검증.

Veo 호출 없음.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_i2v_models.py
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

client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: normalize_chain — primary가 카탈로그에 있으면 맨 앞
# ---------------------------------------------------------------------------
print("\n[test 1] normalize_chain primary 우선")

from services.i2v_models import (  # noqa: E402
    DEFAULT_FALLBACK_CHAIN,
    I2V_CATALOG,
    normalize_chain,
)

chain = normalize_chain("veo-3.1-lite-generate-preview")
check("primary 첫 자리", chain[0] == "veo-3.1-lite-generate-preview", f"got={chain[0]}")
check("primary 중복 없음", chain.count("veo-3.1-lite-generate-preview") == 1, f"chain={chain}")
check("DEFAULT 잔여 모두 포함",
      set(chain) == set(DEFAULT_FALLBACK_CHAIN), f"chain set={set(chain)}")

# 모든 모델이 카탈로그에 등록돼 있어야 함
for m in chain:
    check(f"{m} 카탈로그 등록", m in I2V_CATALOG, "")


# ---------------------------------------------------------------------------
# Test 2: normalize_chain — primary None이면 DEFAULT 그대로
# ---------------------------------------------------------------------------
print("\n[test 2] primary=None")

chain_default = normalize_chain(None)
check("DEFAULT 그대로", chain_default == DEFAULT_FALLBACK_CHAIN, f"got={chain_default}")

chain_unknown = normalize_chain("not-a-real-model")
check("미등록 primary는 DEFAULT", chain_unknown == DEFAULT_FALLBACK_CHAIN,
      f"got={chain_unknown}")


# ---------------------------------------------------------------------------
# Test 3: GET /api/config/i2v-models
# ---------------------------------------------------------------------------
print("\n[test 3] GET /api/config/i2v-models")

r = client.get("/api/config/i2v-models")
check("status 200", r.status_code == 200, f"got={r.status_code}")
body = r.json() if r.status_code == 200 else {}
check("models 6개", len(body.get("models", [])) == 6,
      f"got={len(body.get('models', []))}")
check("default_chain 있음", "default_chain" in body and len(body["default_chain"]) > 0, "")
check("config_default 있음", "config_default" in body, "")

# 각 모델이 메타데이터를 모두 가지고 있는지
for m in body.get("models", [])[:3]:
    check(f"{m['model']} family 채워짐", bool(m.get("family")), "")
    check(f"{m['model']} expected_sec_per_clip int",
          isinstance(m.get("expected_sec_per_clip"), int), "")


# ---------------------------------------------------------------------------
# Test 4: review_prompts /next 에 i2v_model 전달 → DB 저장
# ---------------------------------------------------------------------------
print("\n[test 4] /next review_prompts + i2v_model 저장")

# Mock background task to avoid actually running video_generator
import services.pipeline_runner as pr
import routes.tasks as rt


def _noop_video(task_id: int) -> None:
    pass


pr.run_video_generation = _noop_video  # type: ignore[assignment]
rt.run_video_generation = _noop_video  # type: ignore[assignment]


with Session(engine) as s:
    t = Task(
        product_name="__I2V_TEST__",
        images=json.dumps([], ensure_ascii=False),
        status=TaskStatus.awaiting_user,
        current_step=TaskStep.review_prompts,
        selected_variant_ids=json.dumps(["v1_informative"], ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    s.add(t)
    s.commit()
    s.refresh(t)
    tid = t.id

try:
    r = client.post(
        f"/api/tasks/{tid}/next",
        json={
            "step": "review_prompts",
            "i2v_model": "veo-3.1-fast-generate-preview",
        },
    )
    check("status 200", r.status_code == 200, f"got={r.status_code} body={r.text[:120]}")

    with Session(engine) as s:
        t = s.get(Task, tid)
        check("DB.i2v_model 저장됨",
              t.i2v_model == "veo-3.1-fast-generate-preview",
              f"got={t.i2v_model}")
finally:
    with Session(engine) as s:
        t = s.get(Task, tid)
        if t:
            s.delete(t)
            s.commit()


# ---------------------------------------------------------------------------
# Test 5: 미등록 i2v_model → 400
# ---------------------------------------------------------------------------
print("\n[test 5] 미등록 i2v_model → 400")

with Session(engine) as s:
    t = Task(
        product_name="__I2V_BAD__",
        images=json.dumps([], ensure_ascii=False),
        status=TaskStatus.awaiting_user,
        current_step=TaskStep.review_prompts,
        selected_variant_ids=json.dumps(["v1_informative"], ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    s.add(t)
    s.commit()
    s.refresh(t)
    tid = t.id

try:
    r = client.post(
        f"/api/tasks/{tid}/next",
        json={"step": "review_prompts", "i2v_model": "fake-model-id"},
    )
    check("status 400", r.status_code == 400, f"got={r.status_code}")
finally:
    with Session(engine) as s:
        t = s.get(Task, tid)
        if t:
            s.delete(t)
            s.commit()


# ---------------------------------------------------------------------------
# Test 6: i2v_model 미지정 (None)도 정상 — DB null 유지
# ---------------------------------------------------------------------------
print("\n[test 6] i2v_model 미지정 OK (default 폴백)")

with Session(engine) as s:
    t = Task(
        product_name="__I2V_NULL__",
        images=json.dumps([], ensure_ascii=False),
        status=TaskStatus.awaiting_user,
        current_step=TaskStep.review_prompts,
        selected_variant_ids=json.dumps(["v1_informative"], ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    s.add(t)
    s.commit()
    s.refresh(t)
    tid = t.id

try:
    r = client.post(
        f"/api/tasks/{tid}/next",
        json={"step": "review_prompts"},
    )
    check("status 200", r.status_code == 200, f"got={r.status_code}")

    with Session(engine) as s:
        t = s.get(Task, tid)
        check("DB.i2v_model null 유지", t.i2v_model is None, f"got={t.i2v_model}")
finally:
    with Session(engine) as s:
        t = s.get(Task, tid)
        if t:
            s.delete(t)
            s.commit()


# ---------------------------------------------------------------------------
# Test 7: TaskDetailResp에 i2v_models_chain 노출
# ---------------------------------------------------------------------------
print("\n[test 7] GET /tasks/{id} → i2v_models_chain")

with Session(engine) as s:
    t = Task(
        product_name="__I2V_DETAIL__",
        images=json.dumps([], ensure_ascii=False),
        status=TaskStatus.awaiting_user,
        current_step=TaskStep.review_prompts,
        i2v_model="veo-3.1-fast-generate-preview",
        created_at=datetime.utcnow(),
    )
    s.add(t)
    s.commit()
    s.refresh(t)
    tid = t.id

try:
    r = client.get(f"/api/tasks/{tid}")
    check("status 200", r.status_code == 200, f"got={r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    check("i2v_model 노출", body.get("i2v_model") == "veo-3.1-fast-generate-preview",
          f"got={body.get('i2v_model')}")
    chain = body.get("i2v_models_chain", [])
    check("chain 첫 자리 = primary",
          chain and chain[0] == "veo-3.1-fast-generate-preview",
          f"got={chain[:2]}")
    check("chain 길이 == DEFAULT 길이",
          len(chain) == len(DEFAULT_FALLBACK_CHAIN), f"len={len(chain)}")
finally:
    with Session(engine) as s:
        t = s.get(Task, tid)
        if t:
            s.delete(t)
            s.commit()


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
