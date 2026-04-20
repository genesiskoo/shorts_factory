"""GET /api/config/models 응답 검증.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_model_info.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: GET /api/config/models 200 + 필수 필드
# ---------------------------------------------------------------------------
print("\n[test 1] GET /api/config/models 스키마")

res = client.get("/api/config/models")
check("status 200", res.status_code == 200, f"body={res.text[:200]}")

body = res.json() if res.status_code == 200 else {}
i2v = body.get("i2v", {})

check("i2v.provider 존재", isinstance(i2v.get("provider"), str))
check("i2v.model 존재", isinstance(i2v.get("model"), str))
check("i2v.family 존재", isinstance(i2v.get("family"), str))
check("i2v.label 존재", isinstance(i2v.get("label"), str))
check("i2v.notes 존재", isinstance(i2v.get("notes"), str))
check("i2v.expected_sec_per_clip 존재", isinstance(i2v.get("expected_sec_per_clip"), int))


# ---------------------------------------------------------------------------
# Test 2: config.yaml 기본값(veo-3.1-lite-generate-preview) 매핑 확인
# ---------------------------------------------------------------------------
print("\n[test 2] 기본 model → Veo 3.1 Lite 메타")

# config.yaml의 기본값을 가정한 검증
if i2v.get("model") == "veo-3.1-lite-generate-preview":
    check("label = 'Veo 3.1 Lite (preview)'", i2v.get("label") == "Veo 3.1 Lite (preview)",
          f"label={i2v.get('label')}")
    check("family = 'Veo 3.1'", i2v.get("family") == "Veo 3.1")
    check("daily_quota_estimate 존재", isinstance(i2v.get("daily_quota_estimate"), (int, type(None))))
else:
    print("  (config.yaml model이 기본값 아님 — 스키마 fallback 검증만)")
    check("fallback label = model ID", i2v.get("label") == i2v.get("model") or "Veo" in i2v.get("label", ""))


# ---------------------------------------------------------------------------
# Test 3: default_target_char_count 필드
# ---------------------------------------------------------------------------
print("\n[test 3] default_target_char_count")

check(
    "default_target_char_count=250",
    body.get("default_target_char_count") == 250,
    f"got={body.get('default_target_char_count')}",
)


# ---------------------------------------------------------------------------
# Test 4: 알려지지 않은 model ID fallback
# ---------------------------------------------------------------------------
print("\n[test 4] 미등록 model ID fallback → label=model")

from routes import config_info as ci

_orig_meta = ci._I2V_MODEL_META_FALLBACK
_orig_get = None
try:
    # core.config.get_i2v_config를 monkeypatch
    import core.config as _cc
    _orig_get = _cc.get_i2v_config
    _cc.get_i2v_config = lambda: {"provider": "veo", "model": "unknown-model-x"}  # type: ignore[assignment]

    res2 = client.get("/api/config/models")
    check("status 200 (fallback)", res2.status_code == 200)
    body2 = res2.json() if res2.status_code == 200 else {}
    i2v2 = body2.get("i2v", {})
    check("fallback label == model", i2v2.get("label") == "unknown-model-x")
    check("fallback daily_quota_estimate None", i2v2.get("daily_quota_estimate") is None)
finally:
    if _orig_get is not None:
        _cc.get_i2v_config = _orig_get  # type: ignore[assignment]


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
