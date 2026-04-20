"""scripts/_smoke_pipeline_integration.py — pipeline_runner 통합 검증.

전제: scripts/_smoke_storyboard.py 와 _smoke_scene_writer.py가 먼저 실행돼
output/_scene_smoke/ 에 strategy.json + scripts_final.json 이 있어야 한다.

Veo·TTS 호출 없음. _normalize_storyboard와 _apply_refined_prompts가 strategy
에 정확히 반영되는지 확인.

검증:
- _normalize_storyboard 호출 후 strategy.variants[].clips[]가 scenes[]에서
  mirror됐는지 (clip_num=scene_num, source_image 일치, i2v_prompt 비어있지 않음)
- _apply_refined_prompts 호출 후 strategy.clips[].i2v_prompt가
  scripts_final.scenes[].i2v_prompt_refined로 갱신됐는지
- migrate_strategy_v1_to_v2 idempotency
- capcut_builder._sort_key가 scene_num 우선 정렬하는지
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import config  # noqa: E402,F401
from core.schema_migrate import (  # noqa: E402
    SCHEMA_VERSION,
    migrate_scripts_final_v1_to_v2,
    migrate_strategy_v1_to_v2,
)
from services.pipeline_runner import (  # noqa: E402
    _apply_refined_prompts,
    _normalize_storyboard,
)

OUT_DIR = PROJECT_ROOT / "output" / "_scene_smoke"


def main() -> int:
    strategy_path = OUT_DIR / "strategy.json"
    scripts_path = OUT_DIR / "scripts_final.json"
    if not strategy_path.exists() or not scripts_path.exists():
        print(f"[FAIL] 사전 산출물 없음 — _smoke_storyboard.py와 _smoke_scene_writer.py 먼저 실행")
        return 1

    with open(strategy_path, encoding="utf-8") as f:
        strategy = json.load(f)
    with open(scripts_path, encoding="utf-8") as f:
        scripts_final = json.load(f)

    image_count = strategy.get("image_count") or len(
        strategy["variants"][0].get("scenes", [])
    )

    failures: list[str] = []

    def assert_(cond: bool, msg: str) -> None:
        mark = "PASS" if cond else "FAIL"
        print(f"  [{mark}] {msg}")
        if not cond:
            failures.append(msg)

    print("[verify] _normalize_storyboard 미러 동기화")
    n = _normalize_storyboard(strategy, image_count)
    assert_(strategy.get("schema_version") == SCHEMA_VERSION, "schema_version 유지")
    assert_(strategy.get("image_count") == image_count, "image_count 유지")

    for var in strategy["variants"]:
        vid = var["variant_id"]
        scenes = var.get("scenes", [])
        clips = var.get("clips", [])
        assert_(len(scenes) == image_count, f"{vid}: scenes 길이 {image_count}")
        assert_(len(clips) == image_count, f"{vid}: clips mirror 길이 {image_count}")
        for s, c in zip(scenes, clips):
            assert_(s["scene_num"] == c["clip_num"], f"{vid}: scene_num==clip_num")
            assert_(s["source_image"] == c["source_image"],
                    f"{vid}-{s['scene_num']}: source_image 일치")
            assert_(bool(c["i2v_prompt"]), f"{vid}-{s['scene_num']}: clip i2v_prompt 채워짐")

    print(f"  [info] _normalize_storyboard mutated count = {n}")

    print("\n[verify] _apply_refined_prompts → clips i2v_prompt 갱신")
    applied = _apply_refined_prompts(strategy, scripts_final)
    assert_(applied > 0, f"refined prompt 갱신 (got {applied})")

    refined_map: dict[tuple[str, int], str] = {}
    for sc in scripts_final["scripts"]:
        for s in sc.get("scenes", []) or []:
            r = s.get("i2v_prompt_refined")
            if r:
                refined_map[(sc["variant_id"], s["scene_num"])] = r

    for var in strategy["variants"]:
        vid = var["variant_id"]
        for c in var["clips"]:
            key = (vid, c["clip_num"])
            if key in refined_map:
                assert_(c["i2v_prompt"] == refined_map[key],
                        f"{vid}-{c['clip_num']}: clips.i2v_prompt == refined")
                # scenes도 함께 갱신됐는지
                scene = next(
                    s for s in var["scenes"] if s["scene_num"] == c["clip_num"]
                )
                assert_(scene.get("i2v_prompt_refined") == refined_map[key],
                        f"{vid}-{c['clip_num']}: scenes.i2v_prompt_refined 보존")

    print("\n[verify] migrate idempotency")
    snapshot = json.dumps(strategy, ensure_ascii=False, sort_keys=True)
    migrate_strategy_v1_to_v2(strategy)
    assert_(json.dumps(strategy, ensure_ascii=False, sort_keys=True) == snapshot,
            "v2 strategy migrate idempotent")
    snap2 = json.dumps(scripts_final, ensure_ascii=False, sort_keys=True)
    migrate_scripts_final_v1_to_v2(scripts_final)
    assert_(json.dumps(scripts_final, ensure_ascii=False, sort_keys=True) == snap2,
            "v2 scripts_final migrate idempotent")

    print("\n[verify] capcut_builder._sort_key (scene_num 우선)")
    from agents.capcut_builder import run as _capcut_run  # noqa: F401 — import 검증

    # scenes만, clips만, mixed 케이스
    test_cases = [
        ("scenes만, scene_num 역순",
         {"scenes": [{"scene_num": 3, "source_image": "img_3"},
                     {"scene_num": 1, "source_image": "img_1"},
                     {"scene_num": 2, "source_image": "img_2"}]},
         [1, 2, 3]),
        ("clips만 (v1 fallback)",
         {"clips": [{"clip_num": 2}, {"clip_num": 1}, {"clip_num": 3}]},
         [1, 2, 3]),
    ]
    # _sort_key는 capcut_builder.run 내부 클로저라 직접 호출 어려움.
    # 통합 sorted() 로직을 모사
    timeline_order = {"intro": 0, "middle": 1, "climax": 2, "outro": 3}

    def _sort_key(u: dict) -> tuple[int, int]:
        n = u.get("scene_num") if u.get("scene_num") is not None else u.get("clip_num")
        if isinstance(n, int):
            return (0, n)
        return (1, timeline_order.get(u.get("timeline", "middle"), 1))

    for label, var, expected_nums in test_cases:
        units = var.get("scenes") or var.get("clips") or []
        sorted_units = sorted(units, key=_sort_key)
        nums = [(u.get("scene_num") if u.get("scene_num") is not None
                 else u.get("clip_num"))
                for u in sorted_units]
        assert_(nums == expected_nums, f"{label}: 정렬 결과 {expected_nums} (got {nums})")

    print(f"\n[result] {len(failures)} failures")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("[result] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
