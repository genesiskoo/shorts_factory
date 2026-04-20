"""PATCH /api/tasks/{id}/edit-script — scene_num 옵션 검증.

scene_num 지정 시 scenes[scene_num].script_segment만 갱신하고 full_text를
hook + segments + outro로 재조립한다. scene_num 없으면 기존 동작
(script_text 전체 치환).

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_scene_edit.py
"""
from __future__ import annotations

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
from sqlmodel import Session  # noqa: E402

init_db()


def _scripts_v2(variant_id: str = "v1_informative") -> dict:
    return {
        "schema_version": 2,
        "scripts": [
            {
                "variant_id": variant_id,
                "title": "테스트",
                "hook_text": "훅.",
                "outro_text": "끝.",
                "hook_attached_to": 1,
                "outro_attached_to": 2,
                "scenes": [
                    {
                        "scene_num": 1,
                        "script_segment": "원본 1번.",
                        "i2v_prompt_refined": "scene 1 prompt",
                    },
                    {
                        "scene_num": 2,
                        "script_segment": "원본 2번.",
                        "i2v_prompt_refined": "scene 2 prompt",
                    },
                ],
                "full_text": "훅. 원본 1번. 원본 2번. 끝.",
                "script_text": "훅. 원본 1번. 원본 2번. 끝.",
            }
        ],
    }


def _scripts_v1(variant_id: str = "v1_informative") -> dict:
    return {
        "scripts": [
            {
                "variant_id": variant_id,
                "title": "v1 테스트",
                "script_text": "v1 monolithic 대본 텍스트입니다.",
            }
        ]
    }


def _make_task(
    out_dir: Path,
    scripts_payload: dict,
    step: TaskStep = TaskStep.select_scripts,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scripts_final.json").write_text(
        json.dumps(scripts_payload, ensure_ascii=False),
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


def _read_script(out_dir: Path, variant_id: str) -> dict:
    data = json.loads((out_dir / "scripts_final.json").read_text(encoding="utf-8"))
    return next(
        (s for s in data["scripts"] if s["variant_id"] == variant_id),
        {},
    )


client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: scene_num 지정 → scenes[].script_segment 갱신 + full_text 재조립
# ---------------------------------------------------------------------------
print("\n[test 1] scene_num 지정 PATCH")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t1"
    tid = _make_task(out, _scripts_v2())
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 1,
                "script_text": "수정된 1번.",
            },
        )
        check("status 200", r.status_code == 200, f"got={r.status_code} body={r.text[:120]}")
        body = r.json() if r.status_code == 200 else {}
        check("response.scene_num=1", body.get("scene_num") == 1, f"got={body.get('scene_num')}")

        sc = _read_script(out, "v1_informative")
        scene1 = next(s for s in sc["scenes"] if s["scene_num"] == 1)
        scene2 = next(s for s in sc["scenes"] if s["scene_num"] == 2)
        check("scene 1 segment 갱신", scene1["script_segment"] == "수정된 1번.",
              f"got={scene1['script_segment']!r}")
        check("scene 2 segment 보존", scene2["script_segment"] == "원본 2번.",
              f"got={scene2['script_segment']!r}")
        check("scene 1 i2v_prompt_refined 보존",
              scene1.get("i2v_prompt_refined") == "scene 1 prompt", "")
        check("full_text 재조립",
              sc["full_text"] == "훅. 수정된 1번. 원본 2번. 끝.",
              f"got={sc['full_text']!r}")
        check("script_text == full_text",
              sc["script_text"] == sc["full_text"], "")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 2: scene_num 미지정 → 기존 script_text 전체 치환
# ---------------------------------------------------------------------------
print("\n[test 2] scene_num 미지정 PATCH (legacy 동작)")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t2"
    tid = _make_task(out, _scripts_v2())
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "script_text": "전체 치환된 새 대본 텍스트입니다.",
            },
        )
        check("status 200", r.status_code == 200, f"got={r.status_code} body={r.text[:120]}")
        body = r.json() if r.status_code == 200 else {}
        check("response.scene_num is None", body.get("scene_num") is None, f"got={body.get('scene_num')}")

        sc = _read_script(out, "v1_informative")
        check("script_text 전체 치환",
              sc["script_text"] == "전체 치환된 새 대본 텍스트입니다.",
              f"got={sc['script_text']!r}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 3: 존재하지 않는 scene_num → 404
# ---------------------------------------------------------------------------
print("\n[test 3] 존재하지 않는 scene_num → 404")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t3"
    tid = _make_task(out, _scripts_v2())
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 99,
                "script_text": "x",
            },
        )
        check("status 404", r.status_code == 404, f"got={r.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 4: v1 데이터(scenes 비어있음) + scene_num 지정 → 404
# ---------------------------------------------------------------------------
print("\n[test 4] v1 scripts에 scene_num 지정 → 404 (scenes 비어있음)")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t4"
    tid = _make_task(out, _scripts_v1())
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 1,
                "script_text": "x",
            },
        )
        check("status 404", r.status_code == 404, f"got={r.status_code}")
        # v1 task에서도 scene_num 없이는 정상 동작해야 함
        r2 = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "script_text": "v1 전체 치환 OK.",
            },
        )
        check("v1: scene_num 없으면 200", r2.status_code == 200, f"got={r2.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 5: scene_num 지정 시 1자 segment도 허용 (기존 5자 제한 우회)
# ---------------------------------------------------------------------------
print("\n[test 5] scene segment는 짧아도 OK (1자 이상)")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t5"
    tid = _make_task(out, _scripts_v2())
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 2,
                "script_text": "와우.",
            },
        )
        check("status 200 (3자 segment)", r.status_code == 200, f"got={r.status_code}")
        # 빈 문자열은 거부
        r2 = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 2,
                "script_text": "",
            },
        )
        check("빈 문자열은 400", r2.status_code == 400, f"got={r2.status_code}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 6: review_tts 단계에서 scene 편집 → TTS mp3/srt 삭제
# ---------------------------------------------------------------------------
print("\n[test 6] review_tts 단계 scene 편집 시 TTS stale 처리")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t6"
    tid = _make_task(out, _scripts_v2(), step=TaskStep.review_tts)
    audio = out / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    mp3 = audio / "v1_informative.mp3"
    srt = audio / "v1_informative.srt"
    mp3.write_bytes(b"\xff\xfb")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n", encoding="utf-8")
    try:
        r = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 1,
                "script_text": "review에서 수정.",
            },
        )
        check("status 200", r.status_code == 200, f"got={r.status_code}")
        check("mp3 삭제됨", not mp3.exists(), f"exists={mp3.exists()}")
        check("srt 삭제됨", not srt.exists(), f"exists={srt.exists()}")
    finally:
        _cleanup(tid)


# ---------------------------------------------------------------------------
# Test 7: scene_num=0/음수 → 422 (Pydantic Field(ge=1))
# ---------------------------------------------------------------------------
print("\n[test 7] scene_num<1 → 422 선차단")

with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "_t7"
    tid = _make_task(out, _scripts_v2())
    try:
        r0 = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": 0,
                "script_text": "x",
            },
        )
        check("scene_num=0 → 422", r0.status_code == 422, f"got={r0.status_code}")
        rneg = client.patch(
            f"/api/tasks/{tid}/edit-script",
            json={
                "variant_id": "v1_informative",
                "scene_num": -1,
                "script_text": "x",
            },
        )
        check("scene_num=-1 → 422", rneg.status_code == 422, f"got={rneg.status_code}")
    finally:
        _cleanup(tid)


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
