"""pipeline.py — shorts_factory v3 메인 오케스트레이터"""

import argparse
import concurrent.futures
import io
import logging
import os
import sys
from pathlib import Path

# Windows CP949 터미널에서 유니코드(한글, em dash 등) 깨짐 방지
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.checkpoint import load_or_run, save_json
from agents import (
    product_analyzer,
    pd_strategist,
    storyboard_designer,
    hook_writer,
    scriptwriter,
    scene_writer,
    script_reviewer,
    tts_generator,
    video_generator,
)

# Scene 기반 v2 파이프라인 (default). SHORTS_USE_LEGACY_AGENTS=1 → 기존 v1.
_USE_LEGACY = os.getenv("SHORTS_USE_LEGACY_AGENTS", "").strip() in ("1", "true", "yes")
_strategy_agent = pd_strategist if _USE_LEGACY else storyboard_designer
_script_agent = scriptwriter if _USE_LEGACY else scene_writer

# capcut_builder는 agents/ 또는 scripts/ 어느 쪽에 있어도 임포트
try:
    from agents import capcut_builder
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
    import capcut_builder  # type: ignore

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline.log", encoding="utf-8", delay=True),
    ],
)
# 외부 라이브러리 노이즈 억제
for _noisy in ("httpx", "httpcore", "urllib3", "google.auth",
               "google.api_core", "urllib3.connectionpool"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def run(
    product_name: str,
    images: list[str],
    price_info: str | None = None,
    detail_text: str | None = None,
    seller_memo: str | None = None,
    skip_video: bool = False,
    skip_tts: bool = False,
) -> None:
    """메인 파이프라인. end-to-end 실행."""

    out = f"./output/{product_name}"
    os.makedirs(out, exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # 이미지 인덱스 매핑 (전 에이전트 공유)
    image_map: dict[str, str] = {f"img_{i+1}": path for i, path in enumerate(images)}

    logger.info(f"=== 파이프라인 시작: {product_name} ===")
    logger.info(f"이미지: {images}")

    # ① 리서처 [Flash]
    profile = load_or_run(
        f"{out}/product_profile.json",
        product_analyzer.run,
        product_name, images, price_info, detail_text, seller_memo,
    )
    logger.info(f"[①] product_profile 완료: type={profile.get('product_type')}")

    # ② PD [Pro] — v2: storyboard_designer (scenes[]) / v1 legacy: pd_strategist (clips[])
    logger.info("[②] %s (legacy=%s)", _strategy_agent.__name__, _USE_LEGACY)
    strategy = load_or_run(
        f"{out}/strategy.json",
        _strategy_agent.run,
        profile, images,
    )
    logger.info(f"[②] strategy 완료: variants={len(strategy.get('variants', []))}개")

    # ③~⑤ 대본 체인 [Flash] — 미달 시 hook_writer부터 재생성 (최대 2회)
    MAX_RETRIES = 2
    scripts_final = None
    prev_feedback: list = []

    for attempt in range(MAX_RETRIES + 1):
        suffix = f"_v{attempt}" if attempt > 0 else ""

        hooks = load_or_run(
            f"{out}/hooks{suffix}.json",
            hook_writer.run,
            strategy, profile,
        )

        scripts = load_or_run(
            f"{out}/scripts{suffix}.json",
            _script_agent.run,
            hooks, strategy, profile,
            review_feedback=prev_feedback if attempt > 0 else None,
        )

        review_result = script_reviewer.run(scripts, profile)

        if review_result.get("all_passed") or attempt == MAX_RETRIES:
            scripts_final = {"scripts": review_result.get("scripts", scripts.get("scripts", []))}
            save_json(f"{out}/scripts_final.json", scripts_final)
            logger.info(f"[③⑤] 대본 확정 (attempt {attempt}): {len(scripts_final.get('scripts', []))}개")
            break

        prev_feedback = review_result.get("feedback", [])
        logger.info(f"[③⑤] 대본 미달 — 재생성 {attempt + 1}/{MAX_RETRIES}")
        # 미달 시 다음 루프에서 새 파일명으로 재생성 (기존 파일 덮어쓰지 않음)

    # ⑥⑦ 병렬 실행
    audio_result: dict = {}
    clips_result: dict = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}

        if not skip_tts:
            futures["audio"] = executor.submit(
                tts_generator.run, scripts_final, out
            )
        if not skip_video:
            futures["clips"] = executor.submit(
                video_generator.run, strategy, images, image_map, out
            )

        if "audio" in futures:
            audio_result = futures["audio"].result()
            logger.info(f"[⑥] TTS 완료: {len(audio_result)}개")
            failed_tts = [vid for vid, v in audio_result.items() if v.get("mp3") is None]
            if failed_tts:
                logger.warning(f"[⑥] TTS 실패 variant: {failed_tts}")

        if "clips" in futures:
            clips_result = futures["clips"].result()
            logger.info(f"[⑦] 영상 완료: {len(clips_result)}개 클립")

    # ⑧ 편집자 [로컬]
    try:
        capcut_builder.run(
            audio_dir=f"{out}/audio",
            clips_dir=f"{out}/clips",
            scripts=scripts_final,
            strategy=strategy,
            output_dir=f"{out}/capcut_drafts",
        )
        logger.info("[⑧] capcut_builder 완료")
    except Exception as e:
        logger.error(f"[⑧] capcut_builder 실패: {e}")

    logger.info(f"=== 파이프라인 완료: {out}/capcut_drafts/ ===")
    print(f"\n완료: {out}/capcut_drafts/ 에 프로젝트 생성됨")
    print("→ CapCut 데스크톱에서 열어서 렌더링하세요")


def main():
    parser = argparse.ArgumentParser(description="shorts_factory v3 파이프라인")
    parser.add_argument("--product", required=True, help="상품명")
    parser.add_argument("--images", nargs="+", required=True, help="이미지 경로 3~4개")
    parser.add_argument("--price", default=None, help="가격 정보 (선택)")
    parser.add_argument("--detail", default=None, help="상세 설명 (선택)")
    parser.add_argument("--memo", default=None, help="판매자 메모 (선택)")
    parser.add_argument("--skip-video", action="store_true", help="영상 생성 스킵")
    parser.add_argument("--skip-tts", action="store_true", help="TTS 생성 스킵")

    args = parser.parse_args()
    run(
        product_name=args.product,
        images=args.images,
        price_info=args.price,
        detail_text=args.detail,
        seller_memo=args.memo,
        skip_video=args.skip_video,
        skip_tts=args.skip_tts,
    )


if __name__ == "__main__":
    main()
