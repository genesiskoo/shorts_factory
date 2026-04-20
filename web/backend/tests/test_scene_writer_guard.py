"""scene_writer.MANDATORY_NEGATIVE_HINTS 강제 append 검증.

저비용 Veo 모델이 화면에 텍스트를 그리거나 상품을 변형하는 문제를 막기 위해
LLM 출력 i2v_prompt_refined에 가드 구문을 코드 레벨에서 강제로 append.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_scene_writer_guard.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.scene_writer import (  # noqa: E402
    MANDATORY_NEGATIVE_HINTS,
    _GUARD_SENTINEL,
    _ensure_negative_hints,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: 가드 미포함 prompt → suffix append
# ---------------------------------------------------------------------------
print("\n[test 1] 가드 미포함 → append")

p1 = "Slow zoom in rotation on white background, soft studio lighting"
out1 = _ensure_negative_hints(p1)
check("guard 포함됨", _GUARD_SENTINEL in out1.lower())
check("원본 보존됨", p1 in out1)
check("MANDATORY 전체 포함", MANDATORY_NEGATIVE_HINTS in out1)


# ---------------------------------------------------------------------------
# Test 2: 가드 이미 포함 → 그대로 (LLM이 이미 따른 경우)
# ---------------------------------------------------------------------------
print("\n[test 2] 가드 이미 포함 → 변경 없음")

p2 = "Soft slow zoom on product, no text on screen, preserve product unchanged"
out2 = _ensure_negative_hints(p2)
check("동일하게 유지", out2 == p2)
# 한 번만 append되어야 함
check("guard sentinel 1회만", out2.lower().count(_GUARD_SENTINEL) == 1)


# ---------------------------------------------------------------------------
# Test 3: 빈 prompt → 그대로 (빈 문자열에 가드 추가하지 않음)
# ---------------------------------------------------------------------------
print("\n[test 3] 빈 prompt → no-op")

check("빈 문자열 그대로", _ensure_negative_hints("") == "")
check("None 안전 (빈 문자열 처리)", _ensure_negative_hints(None) is None or _ensure_negative_hints(None) == "")


# ---------------------------------------------------------------------------
# Test 4: 대소문자 변형 — sentinel은 lowercase 비교
# ---------------------------------------------------------------------------
print("\n[test 4] 대소문자 변형 인식")

p4 = "Quick cut to detail, NO TEXT ON SCREEN, focus pull"
out4 = _ensure_negative_hints(p4)
check("대문자 포함도 인식 (변경 없음)", out4 == p4)


# ---------------------------------------------------------------------------
# Test 5: 끝에 마침표 있는 prompt → sep 없이 append (이중 . 방지)
# ---------------------------------------------------------------------------
print("\n[test 5] 끝 구두점 처리")

p5a = "Slow zoom on product."
out5a = _ensure_negative_hints(p5a)
check("마침표 끝 → sep 생략", "..," not in out5a and ", ," not in out5a)
check("guard append됨", _GUARD_SENTINEL in out5a.lower())

p5b = "Slow zoom on product,"
out5b = _ensure_negative_hints(p5b)
check("콤마 끝 → sep 생략", ",," not in out5b)


# ---------------------------------------------------------------------------
# Test 6: scene_writer 시뮬레이션 — 여러 scene 입력
# ---------------------------------------------------------------------------
print("\n[test 6] 다중 scene 시뮬레이션")

scenes = [
    {"scene_num": 1, "i2v_prompt_refined": "Slow zoom on white background"},
    {"scene_num": 2, "i2v_prompt_refined": "no text on screen, gentle pan"},
    {"scene_num": 3, "i2v_prompt_refined": ""},
    {"scene_num": 4, "i2v_prompt_refined": "Macro close-up of hand"},
]
for s in scenes:
    s["i2v_prompt_refined"] = _ensure_negative_hints(s["i2v_prompt_refined"])

check("scene 1 가드 추가됨", _GUARD_SENTINEL in scenes[0]["i2v_prompt_refined"].lower())
check("scene 2 가드 그대로 (1회만)", scenes[1]["i2v_prompt_refined"].lower().count(_GUARD_SENTINEL) == 1)
check("scene 3 빈 프롬프트는 빈 그대로", scenes[2]["i2v_prompt_refined"] == "")
check("scene 4 가드 추가됨", _GUARD_SENTINEL in scenes[3]["i2v_prompt_refined"].lower())


# ---------------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------------
print(f"\n========== {sum(1 for _, ok, _ in results if ok)}/{len(results)} PASS ==========")
fails = [(n, d) for n, ok, d in results if not ok]
if fails:
    print("FAIL details:")
    for n, d in fails:
        print(f"  - {n}: {d}")
    sys.exit(1)


def test_scene_writer_guard() -> None:
    """pytest entry."""
    assert all(ok for _, ok, _ in results), [n for n, ok, _ in results if not ok]
