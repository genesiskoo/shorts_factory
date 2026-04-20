"""scripts/_smoke_scene_writer.py — scene_writer 단독 dry-run.

전제: scripts/_smoke_storyboard.py를 먼저 실행해 output/_scene_smoke/strategy.json
이 존재해야 한다.

추가로 hook_writer를 호출해 hooks.json을 만든 다음 scene_writer를 돌린다.
TTS·Veo 호출 없음. Gemini Flash 2~3회 호출.

사용법:
    python scripts/_smoke_scene_writer.py [--force]

검증 항목:
- schema_version=2
- scripts 5개
- 각 script.scenes 길이 = strategy.scenes 길이
- scene_num 1..N 연속, 입력 strategy와 일치
- 모든 script_segment 비어있지 않음
- i2v_prompt_refined ASCII (영문)
- full_text == hook_text + segments + outro_text 결정적 조립
- script_text == full_text (legacy 호환)
- 합산 글자수 ∈ [target*0.8, target*1.2]
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from agents import hook_writer, scene_writer  # noqa: E402
from core.schema_migrate import assemble_full_text  # noqa: E402

OUT_DIR = PROJECT_ROOT / "output" / "_scene_smoke"
PROFILE_PATH = PROJECT_ROOT / "output" / "LED버섯무드등_테스트" / "product_profile.json"
TARGET_CHAR = 250


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    strategy_path = OUT_DIR / "strategy.json"
    if not strategy_path.exists():
        print(f"[FAIL] strategy 없음 — 먼저 _smoke_storyboard.py 실행: {strategy_path}")
        return 1

    with open(strategy_path, encoding="utf-8") as f:
        strategy = json.load(f)
    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = json.load(f)

    hooks_path = OUT_DIR / "hooks.json"
    if hooks_path.exists() and not args.force:
        print(f"[cache] hooks 재사용: {hooks_path}")
        with open(hooks_path, encoding="utf-8") as f:
            hooks = json.load(f)
    else:
        print("[run] hook_writer 호출...")
        hooks = hook_writer.run(strategy, profile)
        with open(hooks_path, "w", encoding="utf-8") as f:
            json.dump(hooks, f, ensure_ascii=False, indent=2)
        print(f"[saved] {hooks_path}")

    scripts_path = OUT_DIR / "scripts_final.json"
    if scripts_path.exists() and not args.force:
        print(f"[cache] scripts_final 재사용: {scripts_path}")
        with open(scripts_path, encoding="utf-8") as f:
            scripts_final = json.load(f)
    else:
        print("[run] scene_writer 호출...")
        scripts_final = scene_writer.run(hooks, strategy, profile, target_char_count=TARGET_CHAR)
        with open(scripts_path, "w", encoding="utf-8") as f:
            json.dump(scripts_final, f, ensure_ascii=False, indent=2)
        print(f"[saved] {scripts_path}")

    # ---------------------------------------------------------------
    # 검증
    # ---------------------------------------------------------------
    failures: list[str] = []

    def assert_(cond: bool, msg: str) -> None:
        mark = "PASS" if cond else "FAIL"
        print(f"  [{mark}] {msg}")
        if not cond:
            failures.append(msg)

    print("\n[verify]")
    assert_(scripts_final.get("schema_version") == 2,
            f"schema_version=2 (got {scripts_final.get('schema_version')})")

    scripts = scripts_final.get("scripts", [])
    assert_(len(scripts) == 5, f"scripts 5개 (got {len(scripts)})")

    expected_by_vid: dict[str, list[int]] = {
        v.get("variant_id"): [s.get("scene_num") for s in (v.get("scenes") or [])]
        for v in strategy.get("variants", [])
    }

    char_min = int(TARGET_CHAR * 0.8)
    char_max = int(TARGET_CHAR * 1.2)

    for sc in scripts:
        vid = sc.get("variant_id", "?")
        scenes = sc.get("scenes", []) or []
        expected = expected_by_vid.get(vid, [])

        assert_(len(scenes) == len(expected),
                f"{vid}: scenes 길이 = strategy ({len(expected)}, got {len(scenes)})")
        nums = [s.get("scene_num") for s in scenes]
        assert_(nums == expected, f"{vid}: scene_num 순서 일치 ({expected} got {nums})")

        for s in scenes:
            sn = s.get("scene_num")
            seg = (s.get("script_segment") or "").strip()
            assert_(bool(seg), f"{vid}-{sn}: script_segment 비어있지 않음")
            refined = s.get("i2v_prompt_refined", "") or ""
            assert_(bool(refined), f"{vid}-{sn}: i2v_prompt_refined 비어있지 않음")
            assert_(refined.isascii() if refined else True,
                    f"{vid}-{sn}: i2v_prompt_refined ASCII")

        assembled = assemble_full_text(sc)
        full = (sc.get("full_text") or "").strip()
        assert_(full == assembled.strip(),
                f"{vid}: full_text == 결정적 조립 (got len {len(full)}, expected {len(assembled.strip())})")

        assert_(sc.get("script_text") == sc.get("full_text"),
                f"{vid}: script_text == full_text (legacy 호환)")

        actual_len = len(full)
        assert_(char_min <= actual_len <= char_max,
                f"{vid}: 글자수 {actual_len} ∈ [{char_min}, {char_max}]")

    print(f"\n[result] {len(failures)} failures")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("[result] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
