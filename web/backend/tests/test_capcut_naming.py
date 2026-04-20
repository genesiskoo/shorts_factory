"""capcut_builder 프로젝트명 규칙 및 mirror 경로 매칭 검증.

사용자 요구: `{product_name}_{variant_id}` 형식으로 CapCut UI에서 구분 가능해야 함.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_capcut_naming.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.capcut_builder import (  # noqa: E402
    _build_project_name,
    _sanitize_project_name,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: 기본 naming — product_name + variant_id
# ---------------------------------------------------------------------------
print("\n[test 1] 기본 naming 규칙")

cases = [
    (("샥즈 오픈닷 원 E310 오픈형", "v1_informative"),
     "샥즈 오픈닷 원 E310 오픈형_v1_informative"),
    (("Sony WF-1000XM5 무선 이어폰", "v2_empathy"),
     "Sony WF-1000XM5 무선 이어폰_v2_empathy"),
    (("엔커사운드코어", "v5_comparison"), "엔커사운드코어_v5_comparison"),
]
for (prod, vid), expected in cases:
    got = _build_project_name(prod, vid)
    check(f"{prod!r} + {vid!r}", got == expected, f"got={got!r}")


# ---------------------------------------------------------------------------
# Test 2: product_name 누락 — variant_id 폴백
# ---------------------------------------------------------------------------
print("\n[test 2] product_name 누락 시 variant_id만")

check("None → variant_id", _build_project_name(None, "v1_informative") == "v1_informative",
      f"got={_build_project_name(None, 'v1_informative')!r}")
check("빈 문자열 → variant_id", _build_project_name("", "v3_scenario") == "v3_scenario",
      f"got={_build_project_name('', 'v3_scenario')!r}")
check("공백만 → variant_id", _build_project_name("   ", "v4_review") == "v4_review",
      f"got={_build_project_name('   ', 'v4_review')!r}")


# ---------------------------------------------------------------------------
# Test 3: 경로 탈출 / 금지 문자 sanitize
# ---------------------------------------------------------------------------
print("\n[test 3] 금지 문자 / 경로 탈출 방어")

check(
    "../ path traversal 차단",
    "../" not in _build_project_name("../../etc/passwd", "v1_informative")
    and ".." not in _build_project_name("../../etc/passwd", "v1_informative"),
    f"got={_build_project_name('../../etc/passwd', 'v1_informative')!r}",
)
check(
    "Windows 금지 문자 치환",
    "/" not in _sanitize_project_name('a/b\\c:d*e?f"g<h>i|j'),
    f"got={_sanitize_project_name('a/b\\c:d*e?f\"g<h>i|j')!r}",
)
check(
    "백슬래시 제거",
    "\\" not in _sanitize_project_name("a\\b\\c"),
    f"got={_sanitize_project_name('a\\b\\c')!r}",
)


# ---------------------------------------------------------------------------
# Test 4: 길이 상한 80자
# ---------------------------------------------------------------------------
print("\n[test 4] 길이 80자 상한")

long_prod = "가" * 200
out = _sanitize_project_name(long_prod)
check(f"200자 → <=80자", len(out) <= 80, f"len={len(out)}")


# ---------------------------------------------------------------------------
# Test 5: pipeline_runner의 mirror 경로 매칭
# ---------------------------------------------------------------------------
print("\n[test 5] pipeline_runner mirror 경로 동기화")

import importlib
import sys as _sys
# web/backend를 sys.path에 추가
_sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))
import config  # noqa: E402,F401
pipeline_runner = importlib.import_module("services.pipeline_runner")

# 소스 문자열에서 mirror 로직이 _build_project_name을 참조하는지 확인
pr_src = Path(pipeline_runner.__file__).read_text(encoding="utf-8")
check(
    "pipeline_runner에 _build_project_name import 존재",
    "_build_project_name" in pr_src,
    "agents.capcut_builder._build_project_name 참조 확인",
)
check(
    "mirror src가 project_name 기반",
    "_CAPCUT_SYSTEM_PROJECTS / project_name" in pr_src,
    "variant_id 직접이 아닌 project_name 기반 src 경로",
)


# ---------------------------------------------------------------------------
# Test 6: 과거 variant_id-only 폴더와 충돌 없음
# ---------------------------------------------------------------------------
print("\n[test 6] 과거 variant_id-only 폴더와 이름 분리")

new_name = _build_project_name("샥즈 오픈닷 원 E310 오픈형", "v1_informative")
check(
    "새 이름이 variant_id와 다름",
    new_name != "v1_informative" and new_name.endswith("_v1_informative"),
    f"new_name={new_name!r}",
)


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
