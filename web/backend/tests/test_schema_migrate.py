"""schema v1 → v2 마이그레이션 검증.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_schema_migrate.py
또는:
    cd web/backend && venv_web/Scripts/python.exe -m pytest tests/test_schema_migrate.py -v
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))

import config  # noqa: E402,F401
from core.schema_migrate import (  # noqa: E402
    SCHEMA_VERSION,
    assemble_full_text,
    migrate_scripts_final_v1_to_v2,
    migrate_strategy_v1_to_v2,
)
from services.file_ops import patch_script_segment  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: strategy v1 → v2 정상 변환
# ---------------------------------------------------------------------------
print("\n[test 1] strategy v1 → v2 정상 변환")

v1_strategy = {
    "variants": [
        {
            "variant_id": "v1_informative",
            "hook_type": "informative",
            "direction": "정보형",
            "clips": [
                {
                    "clip_num": 1,
                    "scene": "제품 첫인상",
                    "source_image": "img_1",
                    "i2v_prompt": "Slow zoom in on white background",
                    "timeline": "intro",
                },
                {
                    "clip_num": 2,
                    "scene": "사용 장면",
                    "source_image": "img_2",
                    "i2v_prompt": "Hand demonstrating the product",
                    "timeline": "middle",
                },
            ],
        }
    ]
}

migrated = migrate_strategy_v1_to_v2(copy.deepcopy(v1_strategy))
check("schema_version=2 마킹", migrated.get("schema_version") == SCHEMA_VERSION,
      f"got={migrated.get('schema_version')}")
v0 = migrated["variants"][0]
check("scenes 길이 = clips 길이", len(v0["scenes"]) == 2, f"got={len(v0['scenes'])}")
s0 = v0["scenes"][0]
check("scene_num 보존", s0["scene_num"] == 1, f"got={s0['scene_num']}")
check("source_image 보존", s0["source_image"] == "img_1", f"got={s0['source_image']}")
check("scene_intent ← clip.scene", s0["scene_intent"] == "제품 첫인상",
      f"got={s0['scene_intent']!r}")
check("i2v_prompt_baseline ← clip.i2v_prompt",
      s0["i2v_prompt_baseline"] == "Slow zoom in on white background",
      f"got={s0['i2v_prompt_baseline']!r}")
check("timeline 보존", s0["timeline"] == "intro", f"got={s0['timeline']}")
check("expected_duration_sec 기본 7",
      s0["expected_duration_sec"] == 7, f"got={s0['expected_duration_sec']}")
check("image_count 자동 추론", migrated.get("image_count") == 2,
      f"got={migrated.get('image_count')}")


# ---------------------------------------------------------------------------
# Test 2: idempotent — v2 입력은 그대로
# ---------------------------------------------------------------------------
print("\n[test 2] v2 입력 idempotent")

already_v2 = {
    "schema_version": 2,
    "image_count": 1,
    "variants": [
        {
            "variant_id": "v1_informative",
            "scenes": [
                {
                    "scene_num": 1,
                    "source_image": "img_1",
                    "scene_intent": "이미 v2",
                    "i2v_prompt_baseline": "Already v2 prompt",
                }
            ],
        }
    ],
}
out = migrate_strategy_v1_to_v2(copy.deepcopy(already_v2))
check("v2 그대로 반환", out["variants"][0]["scenes"][0]["scene_intent"] == "이미 v2",
      f"got={out['variants'][0]['scenes'][0]['scene_intent']!r}")
check("scenes 재생성 안 됨", len(out["variants"][0]["scenes"]) == 1,
      f"got len={len(out['variants'][0]['scenes'])}")


# ---------------------------------------------------------------------------
# Test 3: clips 비어있는 빈 케이스
# ---------------------------------------------------------------------------
print("\n[test 3] clips=[] 빈 케이스")

empty = {"variants": [{"variant_id": "v1_informative", "clips": []}]}
out = migrate_strategy_v1_to_v2(copy.deepcopy(empty))
check("scenes 빈 배열", out["variants"][0]["scenes"] == [], "ok")
check("schema_version=2", out.get("schema_version") == SCHEMA_VERSION, "ok")


# ---------------------------------------------------------------------------
# Test 4: 실제 파일 — output/LED버섯무드등_테스트/strategy.json
# ---------------------------------------------------------------------------
print("\n[test 4] 실제 v1 파일 라운드트립")

real_path = PROJECT_ROOT / "output" / "LED버섯무드등_테스트" / "strategy.json"
if real_path.exists():
    with open(real_path, encoding="utf-8") as f:
        real_v1 = json.load(f)
    real_clip_count = len(real_v1["variants"][0]["clips"])
    real_v2 = migrate_strategy_v1_to_v2(copy.deepcopy(real_v1))
    check("실제 파일 schema_version=2", real_v2.get("schema_version") == SCHEMA_VERSION, "")
    check(
        "실제 파일 scenes 길이 = clips 길이",
        len(real_v2["variants"][0]["scenes"]) == real_clip_count,
        f"clips={real_clip_count} scenes={len(real_v2['variants'][0]['scenes'])}",
    )
    check(
        "실제 파일 두 번 변환 idempotent",
        migrate_strategy_v1_to_v2(real_v2) == real_v2,
        "ok",
    )
else:
    check("실제 파일 존재", False, f"missing: {real_path}")


# ---------------------------------------------------------------------------
# Test 5: scripts_final v1 → v2
# ---------------------------------------------------------------------------
print("\n[test 5] scripts_final v1 → v2")

v1_scripts = {
    "scripts": [
        {
            "variant_id": "v1_informative",
            "script_text": "이것이 v1 대본입니다. 짧지만 의미 있어요.",
            "title": "v1 제목",
            "hashtags": ["#a", "#b"],
        }
    ]
}
out = migrate_scripts_final_v1_to_v2(copy.deepcopy(v1_scripts))
check("schema_version=2", out.get("schema_version") == SCHEMA_VERSION, "")
s = out["scripts"][0]
check("full_text 추가됨", s.get("full_text") == "이것이 v1 대본입니다. 짧지만 의미 있어요.",
      f"got={s.get('full_text')!r}")
check("script_text 보존", s.get("script_text") == s.get("full_text"), "")
check("hook_text 빈 문자열", s.get("hook_text") == "", f"got={s.get('hook_text')!r}")
check("scenes 빈 배열", s.get("scenes") == [], "")
check("title 보존", s.get("title") == "v1 제목", "")


# ---------------------------------------------------------------------------
# Test 6: assemble_full_text — hook + segments + outro
# ---------------------------------------------------------------------------
print("\n[test 6] assemble_full_text 결정적 조립")

script = {
    "hook_text": "헤드라인.",
    "scenes": [
        {"scene_num": 1, "script_segment": "첫 문장."},
        {"scene_num": 2, "script_segment": "둘째 문장."},
    ],
    "outro_text": "마무리.",
}
full = assemble_full_text(script)
check("조립 결과", full == "헤드라인. 첫 문장. 둘째 문장. 마무리.", f"got={full!r}")

# 빈 hook/outro 케이스
script2 = {"scenes": [{"scene_num": 1, "script_segment": "단독."}]}
check("hook/outro 없으면 segment만",
      assemble_full_text(script2) == "단독.", f"got={assemble_full_text(script2)!r}")


# ---------------------------------------------------------------------------
# Test 7: patch_script_segment — full_text 자동 재조립
# ---------------------------------------------------------------------------
print("\n[test 7] patch_script_segment + 재조립")

import tempfile

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "scripts_final.json"
    src = {
        "schema_version": 2,
        "scripts": [
            {
                "variant_id": "v1_informative",
                "hook_text": "훅.",
                "outro_text": "끝.",
                "scenes": [
                    {"scene_num": 1, "script_segment": "원본1."},
                    {"scene_num": 2, "script_segment": "원본2."},
                ],
                "full_text": "훅. 원본1. 원본2. 끝.",
                "script_text": "훅. 원본1. 원본2. 끝.",
            }
        ],
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(src, f, ensure_ascii=False)

    updated = patch_script_segment(p, "v1_informative", 2, "수정됨2.")
    s = updated["scripts"][0]
    check(
        "scene 2 segment 갱신",
        s["scenes"][1]["script_segment"] == "수정됨2.",
        f"got={s['scenes'][1]['script_segment']!r}",
    )
    check(
        "full_text 재조립",
        s["full_text"] == "훅. 원본1. 수정됨2. 끝.",
        f"got={s['full_text']!r}",
    )
    check(
        "script_text 동일값 갱신",
        s["script_text"] == s["full_text"],
        "ok",
    )

    # v1 데이터(scenes 비어있음) → KeyError
    legacy = {
        "scripts": [
            {
                "variant_id": "v1_informative",
                "script_text": "v1 대본",
            }
        ]
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(legacy, f, ensure_ascii=False)
    try:
        patch_script_segment(p, "v1_informative", 1, "x")
        check("v1 scenes 빈 배열에 대해 KeyError", False, "no error raised")
    except KeyError:
        check("v1 scenes 빈 배열에 대해 KeyError", True, "raised as expected")


# ---------------------------------------------------------------------------
# Test 8: source_image 정상 변환 (실제 v1 데이터의 중복은 normalize 단계 책임)
# ---------------------------------------------------------------------------
print("\n[test 8] source_image 누락 시 fallback img_N")

missing_src = {
    "variants": [
        {
            "variant_id": "v1_informative",
            "clips": [
                {"clip_num": 1, "scene": "x"},  # source_image 누락
                {"clip_num": 2, "scene": "y"},
            ],
        }
    ]
}
out = migrate_strategy_v1_to_v2(copy.deepcopy(missing_src))
check("누락 시 img_1 fallback",
      out["variants"][0]["scenes"][0]["source_image"] == "img_1",
      f"got={out['variants'][0]['scenes'][0]['source_image']}")
check("누락 시 img_2 fallback",
      out["variants"][0]["scenes"][1]["source_image"] == "img_2",
      f"got={out['variants'][0]['scenes'][1]['source_image']}")


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
