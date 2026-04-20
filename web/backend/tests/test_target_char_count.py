"""대본 목표 글자수 검증 — 폼 입력 → DB → script_reviewer 하드체크 범위.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_target_char_count.py
"""
from __future__ import annotations

import io
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


# --- Mock background task to avoid actually running LLM ---
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


def _fake_image_bytes() -> bytes:
    # 최소 JPEG 파일 (header only) — 실제 이미지 필요 없음, backend는 MIME만 확인
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


def _post_task(target: int | None, product_name: str) -> dict:
    data = {"product_name": product_name}
    if target is not None:
        data["target_char_count"] = str(target)
    files = [
        ("images", (f"img{i}.jpg", io.BytesIO(_fake_image_bytes()), "image/jpeg"))
        for i in range(3)
    ]
    res = client.post("/api/tasks", data=data, files=files)
    return {"status": res.status_code, "body": res.json() if res.status_code < 500 else None, "raw": res.text}


# ---------------------------------------------------------------------------
# Test 1: target=180 저장
# ---------------------------------------------------------------------------
print("\n[test 1] 3장 업로드 + target=140 → DB에 140 저장")
# 3 images 상한 147 → 140은 허용
r = _post_task(140, "__TARGET_T1__")
check("status 201", r["status"] == 201, f"body={r['raw'][:200]}")
if r["status"] == 201:
    tid = r["body"]["task_id"]
    with Session(engine) as s:
        t = s.get(Task, tid)
        check("target_char_count=140 저장됨", t.target_char_count == 140, f"got={t.target_char_count}")
    _delete_task(tid)


# ---------------------------------------------------------------------------
# Test 2: target 미제공 → image_count 기반 기본값 저장 (3이미지 → 135)
# ---------------------------------------------------------------------------
print("\n[test 2] target 미제공 → image_count*45 기본값 저장")
r = _post_task(None, "__TARGET_T2__")
check("status 201", r["status"] == 201)
if r["status"] == 201:
    tid = r["body"]["task_id"]
    with Session(engine) as s:
        t = s.get(Task, tid)
        # 3 images × 45 = 135
        check("target=135 저장 (3×45)",
              t.target_char_count == 135,
              f"got={t.target_char_count}")
    _delete_task(tid)


# ---------------------------------------------------------------------------
# Test 3: 전역 범위 이탈 → 400 (MIN=100, MAX=500)
# ---------------------------------------------------------------------------
print("\n[test 3] target 범위 이탈")
# 99 (하한 미만)
r = _post_task(99, "__TARGET_T3a__")
check("target=99 → 400", r["status"] == 400)
# 600 (상한 초과)
r = _post_task(600, "__TARGET_T3b__")
check("target=600 → 400", r["status"] == 400)


# ---------------------------------------------------------------------------
# Test 4: GET /api/tasks/{id} 응답에 target 노출
# ---------------------------------------------------------------------------
print("\n[test 4] GET /api/tasks/{id} target_char_count 노출")
r = _post_task(300, "__TARGET_T4__")
if r["status"] == 201:
    tid = r["body"]["task_id"]
    gres = client.get(f"/api/tasks/{tid}")
    check("GET 200", gres.status_code == 200)
    if gres.status_code == 200:
        body = gres.json()
        check(
            "응답.target_char_count=300",
            body.get("target_char_count") == 300,
            f"got={body.get('target_char_count')}",
        )
    _delete_task(tid)


# ---------------------------------------------------------------------------
# Test 5: script_reviewer 하드체크 — 범위 벗어난 대본 강제 fail
# ---------------------------------------------------------------------------
print("\n[test 5] script_reviewer 하드체크 범위")

# LLM 호출 회피: GeminiClient.call을 stub해 feedback만 반환
from core import llm_client as _llm  # noqa: E402
from agents import script_reviewer  # noqa: E402

_orig_call = getattr(_llm.GeminiClient, "call", None)


def _fake_call(self, prompt, json_mode=False):
    # LLM이 전 variant를 일단 pass로 반환했다고 가정 → 하드체크가 뒤집는지 확인
    return {
        "all_passed": True,
        "scripts": [],
        "feedback": [
            {"variant_id": "v1_informative", "hook_score": 8, "char_count": 0,
             "no_forbidden_violation": True, "differentiation_score": 7,
             "tts_score": 9, "keyword_duplication": False, "passed": True},
            {"variant_id": "v2_empathy", "hook_score": 8, "char_count": 0,
             "no_forbidden_violation": True, "differentiation_score": 7,
             "tts_score": 9, "keyword_duplication": False, "passed": True},
            {"variant_id": "v3_scenario", "hook_score": 8, "char_count": 0,
             "no_forbidden_violation": True, "differentiation_score": 7,
             "tts_score": 9, "keyword_duplication": False, "passed": True},
        ],
    }


_llm.GeminiClient.call = _fake_call  # type: ignore[method-assign]

scripts_input = {
    "scripts": [
        {"variant_id": "v1_informative", "script_text": "가" * 180},  # 180자 (허용)
        {"variant_id": "v2_empathy", "script_text": "가" * 100},      # 100자 (미달)
        {"variant_id": "v3_scenario", "script_text": "가" * 300},     # 300자 (초과)
    ]
}

try:
    result = script_reviewer.run(scripts_input, {"forbidden_expressions": []}, target_char_count=200)
    fb_by = {f["variant_id"]: f for f in result.get("feedback", [])}
    check("v1_informative (180자, 허용) passed=True",
          fb_by.get("v1_informative", {}).get("passed") is True,
          f"fb={fb_by.get('v1_informative')}")
    check("v2_empathy (100자, 미달) passed=False",
          fb_by.get("v2_empathy", {}).get("passed") is False)
    check("v3_scenario (300자, 초과) passed=False",
          fb_by.get("v3_scenario", {}).get("passed") is False)
    check("all_passed=False", result.get("all_passed") is False)
    check(
        "v2 char_count 반영",
        fb_by.get("v2_empathy", {}).get("char_count") == 100,
    )
    check(
        "v3 char_count 반영",
        fb_by.get("v3_scenario", {}).get("char_count") == 300,
    )
finally:
    if _orig_call is not None:
        _llm.GeminiClient.call = _orig_call  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Test 6: script_reviewer 기본값 (target_char_count 생략 → 250)
# ---------------------------------------------------------------------------
print("\n[test 6] reviewer 기본 target=250 (허용 200~300)")

_llm.GeminiClient.call = _fake_call  # type: ignore[method-assign]
try:
    scripts_input2 = {
        "scripts": [
            {"variant_id": "v1_informative", "script_text": "가" * 250},  # 허용
        ]
    }
    # 기본 250 — feedback은 v1 하나만 반환하도록 맞춤
    _real_fake = _fake_call
    def _only_v1(self, prompt, json_mode=False):
        return {
            "all_passed": True,
            "scripts": [],
            "feedback": [{"variant_id": "v1_informative", "hook_score": 8, "char_count": 0,
                          "no_forbidden_violation": True, "differentiation_score": 7,
                          "tts_score": 9, "keyword_duplication": False, "passed": True}],
        }
    _llm.GeminiClient.call = _only_v1  # type: ignore[method-assign]
    res = script_reviewer.run(scripts_input2, {"forbidden_expressions": []})  # 기본 target
    check(
        "기본 target=250, 250자 script → passed",
        res["feedback"][0]["passed"] is True,
        f"fb={res['feedback'][0]}",
    )
finally:
    if _orig_call is not None:
        _llm.GeminiClient.call = _orig_call  # type: ignore[method-assign]


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
