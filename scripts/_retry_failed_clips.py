"""scripts/_retry_failed_clips.py — 실패한 클립을 폴백 체인으로 재시도.

특정 task 디렉토리에서 strategy.json 기반 예상 클립 파일 목록을 만들고,
누락된 클립만 video_generator.run에 폴백 체인 적용해 재호출.

사용:
    python scripts/_retry_failed_clips.py "output/샥즈 오픈핏 2+ T921" v1_informative

선택적 인자:
    --primary-model MODEL   폴백 체인 우선 모델 (default: 카탈로그 첫 모델)
    --variant-id VID        대상 variant_id (위치 인자로도 가능)
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
sys.path.insert(0, str(PROJECT_ROOT / "web" / "backend"))

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import config  # noqa: E402,F401  (web/backend/config.py side-effect)
from agents import video_generator  # noqa: E402
from services.i2v_models import normalize_chain  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", help="output/{product_name} 디렉토리 경로")
    parser.add_argument("variant_id", help="대상 variant_id (예: v1_informative)")
    parser.add_argument("--primary-model", default=None,
                        help="폴백 체인 우선 모델 ID")
    args = parser.parse_args()

    out = Path(args.task_dir).resolve()
    if not out.exists():
        print(f"[FAIL] task_dir 없음: {out}")
        return 1

    strategy_path = out / "strategy.json"
    if not strategy_path.exists():
        print(f"[FAIL] strategy.json 없음: {strategy_path}")
        return 1
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))

    variant = next(
        (v for v in strategy.get("variants", [])
         if v.get("variant_id") == args.variant_id),
        None,
    )
    if variant is None:
        print(f"[FAIL] variant_id={args.variant_id} 없음")
        return 1

    units = variant.get("clips") or variant.get("scenes") or []
    if not units:
        print(f"[FAIL] {args.variant_id}에 clips/scenes 없음")
        return 1

    clips_dir = out / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    missing_units: list[dict] = []
    for u in units:
        num = u.get("clip_num") or u.get("scene_num")
        mp4 = clips_dir / f"clip_{args.variant_id}_{num}.mp4"
        if mp4.exists():
            print(f"[skip] clip {num} 이미 존재")
        else:
            print(f"[todo] clip {num} 누락 → 재시도 대상")
            # video_generator는 clips[] 형식을 기대하므로 보강
            unit_clip = {
                "clip_num": num,
                "source_image": u.get("source_image"),
                "i2v_prompt": (
                    u.get("i2v_prompt")
                    or u.get("i2v_prompt_refined")
                    or u.get("i2v_prompt_baseline", "")
                ),
                "timeline": u.get("timeline", "middle"),
            }
            missing_units.append(unit_clip)

    if not missing_units:
        print("[result] 재시도 대상 없음. 모든 클립 존재.")
        return 0

    # 이미지 경로 — task 폴더 내에는 없으므로 web/backend/uploads에서 찾는다.
    # 우선 strategy의 src에서 사용된 키 (img_1, img_2, ...)를 task의 product_name에서 추출하기 어려움.
    # 대신 사용자가 task 디렉토리와 같은 product_name으로 web/backend/uploads/{task_id}_*.png를 찾도록 유도.
    # 여기서는 web/backend tasks DB에서 동일 product_name을 검색.
    image_map: dict[str, str] = {}
    try:
        from sqlmodel import Session, select  # type: ignore
        from db import Task, engine  # type: ignore
        with Session(engine) as s:
            stmt = select(Task).where(Task.product_name == out.name)
            t = s.exec(stmt).first()
            if t is not None:
                imgs = json.loads(t.images or "[]")
                for i, p in enumerate(imgs):
                    image_map[f"img_{i + 1}"] = str(Path(p).resolve())
                print(f"[setup] image_map (task_id={t.id}): {list(image_map.keys())}")
    except Exception as e:
        print(f"[warn] DB image lookup 실패: {e}")

    if not image_map:
        print("[FAIL] image_map 구성 실패. web/backend DB에 동일 product_name task가 없음.")
        return 1

    # variant subset (누락 클립만)
    strategy_subset = {
        **strategy,
        "variants": [{**variant, "clips": missing_units}],
    }
    images = [image_map[k] for k in sorted(image_map.keys())]

    chain = normalize_chain(args.primary_model)
    print(f"[setup] 폴백 체인: {chain}")
    print(f"[setup] 재시도 클립: {[u['clip_num'] for u in missing_units]}")
    print()

    result = video_generator.run(
        strategy_subset, images, image_map, str(out),
        models=chain,
    )

    print()
    print("[result]")
    success = 0
    for k, v in result.items():
        status = "OK" if v else "FAIL"
        print(f"  {k}: {status}  {v if v else ''}")
        if v:
            success += 1
    print(f"\n총 {success}/{len(result)} 성공")
    return 0 if success == len(result) else 2


if __name__ == "__main__":
    sys.exit(main())
