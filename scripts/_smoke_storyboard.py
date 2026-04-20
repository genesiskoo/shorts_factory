"""scripts/_smoke_storyboard.py — storyboard_designer 단독 dry-run.

Veo·TTS 호출 없음. Gemini Pro 1회 호출(이미지 4장 분석).

사용법:
    python scripts/_smoke_storyboard.py [--force]

기본은 output/_scene_smoke/strategy.json 캐시 활용. --force 지정 시 강제 재생성.
검증 항목:
- schema_version=2
- variants 5개
- 각 variant.scenes 길이 = image_count
- scene_num 1..N 연속
- variant 내 source_image 중복 없음
- 전 파일에서 (source_image, i2v_prompt_baseline) 유니크 조합 = image_count
- i2v_prompt_baseline ASCII (영문)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import io
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from agents import storyboard_designer  # noqa: E402

OUT_DIR = PROJECT_ROOT / "output" / "_scene_smoke"
PROFILE_PATH = PROJECT_ROOT / "output" / "LED버섯무드등_테스트" / "product_profile.json"

# 4장 사용 → variant당 scene 4개. task_id=1 업로드 PNG 활용
SAMPLE_IMAGES = sorted(
    (PROJECT_ROOT / "web" / "backend" / "uploads").glob("1_*.png")
)[:4]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시 후 재생성")
    args = parser.parse_args()

    if not PROFILE_PATH.exists():
        print(f"[FAIL] profile 없음: {PROFILE_PATH}")
        return 1

    images = []
    for p in SAMPLE_IMAGES:
        if not p.exists():
            print(f"[FAIL] 샘플 이미지 없음: {p}")
            return 1
        images.append(str(p))

    print(f"[setup] 이미지 {len(images)}장, profile={PROFILE_PATH.name}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    strategy_path = OUT_DIR / "strategy.json"

    if strategy_path.exists() and not args.force:
        print(f"[cache] 기존 결과 사용: {strategy_path}")
        with open(strategy_path, encoding="utf-8") as f:
            strategy = json.load(f)
    else:
        print("[run] storyboard_designer 호출 중 (Gemini Pro)...")
        with open(PROFILE_PATH, encoding="utf-8") as f:
            profile = json.load(f)
        strategy = storyboard_designer.run(profile, images, image_count=len(images))
        with open(strategy_path, "w", encoding="utf-8") as f:
            json.dump(strategy, f, ensure_ascii=False, indent=2)
        print(f"[saved] {strategy_path}")

    # ---------------------------------------------------------------
    # 검증
    # ---------------------------------------------------------------
    n = len(images)
    failures: list[str] = []

    def assert_(cond: bool, msg: str) -> None:
        mark = "PASS" if cond else "FAIL"
        print(f"  [{mark}] {msg}")
        if not cond:
            failures.append(msg)

    print("\n[verify]")
    assert_(strategy.get("schema_version") == 2,
            f"schema_version=2 (got {strategy.get('schema_version')})")
    assert_(strategy.get("image_count") == n,
            f"image_count={n} (got {strategy.get('image_count')})")

    variants = strategy.get("variants", [])
    assert_(len(variants) == 5, f"variants 5개 (got {len(variants)})")

    expected_ids = {"v1_informative", "v2_empathy", "v3_scenario", "v4_review", "v5_comparison"}
    got_ids = {v.get("variant_id") for v in variants}
    assert_(got_ids == expected_ids,
            f"variant_id 5종 (got {got_ids})")

    valid_imgs = {f"img_{i+1}" for i in range(n)}
    global_combos: set[tuple[str, str]] = set()

    for var in variants:
        vid = var.get("variant_id", "?")
        scenes = var.get("scenes", []) or []
        assert_(len(scenes) == n, f"{vid}: scenes 길이 {n} (got {len(scenes)})")

        nums = [s.get("scene_num") for s in scenes]
        assert_(nums == list(range(1, n + 1)),
                f"{vid}: scene_num 1..{n} 연속 (got {nums})")

        srcs = [s.get("source_image") for s in scenes]
        assert_(set(srcs) == valid_imgs,
                f"{vid}: source_image 모두 등장 + 중복 없음 (got {srcs})")

        for s in scenes:
            sid = s.get("source_image", "")
            prompt = s.get("i2v_prompt_baseline", "")
            assert_(bool(prompt), f"{vid}-{s.get('scene_num')}: i2v_prompt_baseline 비어있지 않음")
            assert_(prompt.isascii() if prompt else True,
                    f"{vid}-{s.get('scene_num')}: i2v_prompt_baseline ASCII (영문)")
            assert_(bool(s.get("scene_intent")),
                    f"{vid}-{s.get('scene_num')}: scene_intent 비어있지 않음")
            global_combos.add((sid, prompt))

    assert_(len(global_combos) == n,
            f"전 파일에서 유니크 (source_image, prompt) 조합 = {n} (got {len(global_combos)})")

    print(f"\n[result] {len(failures)} failures")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("[result] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
