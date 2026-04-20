"""v6_promotion 활성 조건 + 할인률 계산 검증.

Plan 결정: campaign_variant ≠ 'none' + sale_price 모두 채워졌을 때만 활성.
storyboard_designer.run(promotion=...)로 6번째 variant 추가 생성.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_promotion_variant.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))

import config  # noqa: E402,F401
from services.pipeline_runner import _build_promotion  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


def make_task(**kwargs) -> SimpleNamespace:
    defaults = {
        "campaign_variant": None,
        "original_price": None,
        "sale_price": None,
    }
    return SimpleNamespace(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# Test 1: campaign=none + price 둘 다 → None (비활성)
# ---------------------------------------------------------------------------
print("\n[test 1] campaign='none' → 비활성")
t = make_task(campaign_variant="none", original_price=122000, sale_price=36600)
check("None 반환", _build_promotion(t) is None)


# ---------------------------------------------------------------------------
# Test 2: campaign=family_month + price 미입력 → None
# ---------------------------------------------------------------------------
print("\n[test 2] campaign 설정 + 가격 누락 → 비활성")
t = make_task(campaign_variant="family_month", original_price=None, sale_price=None)
check("None 반환", _build_promotion(t) is None)

t = make_task(campaign_variant="family_month", original_price=122000, sale_price=None)
check("sale_price 단독 누락 → None", _build_promotion(t) is None)

t = make_task(campaign_variant="family_month", original_price=None, sale_price=36600)
check("original_price 단독 누락 → None", _build_promotion(t) is None)


# ---------------------------------------------------------------------------
# Test 3: 정상 활성 — 70% 할인 (이솝 케이스)
# ---------------------------------------------------------------------------
print("\n[test 3] 정상 활성 — 70% 할인")
t = make_task(
    campaign_variant="family_month",
    original_price=122000,
    sale_price=36600,
)
promo = _build_promotion(t)
check("dict 반환", promo is not None)
check("campaign 정확", promo["campaign"] == "family_month")
check("original_price 정확", promo["original_price"] == 122000)
check("sale_price 정확", promo["sale_price"] == 36600)
check("discount_rate=70%", promo["discount_rate"] == 70, f"got={promo['discount_rate']}")


# ---------------------------------------------------------------------------
# Test 4: 다양한 할인률 계산
# ---------------------------------------------------------------------------
print("\n[test 4] 할인률 반올림 검증")
cases = [
    (10000, 9000, 10),  # 10%
    (10000, 5000, 50),  # 50%
    (10000, 3333, 67),  # 66.67% → 67
    (10000, 1, 100),    # 99.99% → 100
    (10000, 10000, 0),  # 0% (sale==original)
]
for orig, sale, expected in cases:
    t = make_task(campaign_variant="fast_delivery", original_price=orig, sale_price=sale)
    promo = _build_promotion(t)
    check(
        f"{orig}→{sale} = {expected}%",
        promo is not None and promo["discount_rate"] == expected,
        f"got={promo['discount_rate'] if promo else None}",
    )


# ---------------------------------------------------------------------------
# Test 5: 대문자/공백 campaign normalization
# ---------------------------------------------------------------------------
print("\n[test 5] campaign 정규화")
t = make_task(campaign_variant="  Family_Month  ", original_price=10000, sale_price=5000)
promo = _build_promotion(t)
check("trim+lowercase", promo and promo["campaign"] == "family_month")


# ---------------------------------------------------------------------------
# Test 6: storyboard_designer 시그니처 호환 — promotion=None 옵션 인자
# ---------------------------------------------------------------------------
print("\n[test 6] storyboard_designer 시그니처")
from agents.storyboard_designer import _v6_prompt_section, run  # noqa: E402
import inspect
sig = inspect.signature(run)
check("run에 promotion 인자 존재", "promotion" in sig.parameters)
check("promotion 기본값 None", sig.parameters["promotion"].default is None)
check("v6 섹션 영문 일부 포함", "v6_promotion" in _v6_prompt_section())


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


def test_promotion_variant() -> None:
    """pytest entry."""
    assert all(ok for _, ok, _ in results), [n for n, ok, _ in results if not ok]
