"""agents/video_generator.py — ⑦ 영상팀 [Veo 3.1 via google-genai]

strategy.json의 clips 배열 → clips/ 디렉토리에 MP4 저장
- 중복 (source_image, i2v_prompt) 조합은 1회만 생성
- 비동기 폴링, 재시도 3회
"""

import logging
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from core.config import get_i2v_config

logger = logging.getLogger(__name__)

# 폴링 설정 (Veo는 평균 60~120초 소요)
POLL_INTERVAL = 10     # 초
MAX_POLL_TIME = 300    # 최대 5분
REQUEST_DELAY = 15.0   # 요청 간 딜레이 (Veo RPM 제한 보호 — preview 티어 ~2 RPM)


def _mime(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower().lstrip(".")
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")


def _generate_clip(
    client: genai.Client,
    model: str,
    image_path: str,
    i2v_prompt: str,
    output_path: Path,
) -> bool:
    """단일 클립 생성. 성공 시 True, 실패 시 False."""

    img_bytes = Path(image_path).read_bytes()
    mime = _mime(image_path)

    # 생성 요청 (재시도 3회, 429는 60초 대기)
    delays = [60, 90, 120]  # 429 RESOURCE_EXHAUSTED 대비 긴 대기
    operation = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            operation = client.models.generate_videos(
                model=model,
                prompt=i2v_prompt,
                image=genai_types.Image(image_bytes=img_bytes, mime_type=mime),
                config=genai_types.GenerateVideosConfig(
                    aspect_ratio="9:16",
                    number_of_videos=1,
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            is_429 = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            logger.warning(f"[video_generator] 생성 요청 attempt {attempt} 실패: {e}")
            if attempt < len(delays):
                wait = delay if is_429 else delay // 4
                logger.info(f"[video_generator] {wait}초 대기 후 재시도...")
                time.sleep(wait)
            else:
                return False

    if operation is None:
        return False

    # 폴링
    elapsed = 0
    interval = POLL_INTERVAL

    while elapsed < MAX_POLL_TIME:
        time.sleep(interval)
        elapsed += interval

        try:
            operation = client.operations.get(operation)
            logger.debug(f"[video_generator] done={operation.done} ({elapsed}s)")

            if operation.done:
                videos = operation.result.generated_videos
                if not videos:
                    logger.error("[video_generator] 결과 영상 없음")
                    return False
                video_bytes = client.files.download(file=videos[0].video)
                output_path.write_bytes(bytes(video_bytes))
                logger.info(f"[video_generator] 저장: {output_path.name}")
                return True

        except Exception as e:
            logger.warning(f"[video_generator] 폴링 에러: {e}")
            interval = min(interval * 1.5, 30)

    logger.error(f"[video_generator] 타임아웃 ({MAX_POLL_TIME}s)")
    return False


def run(
    strategy: dict,
    images: list[str],
    image_map: dict[str, str],
    output_dir: str,
) -> dict:
    """strategy.json clips → clips/ 디렉토리에 MP4 저장. 결과 dict 반환."""

    logger.info("[video_generator] 시작")
    cfg = get_i2v_config()
    api_key = cfg["api_key"]
    model = cfg.get("model", "veo-3.1-lite-generate-preview")

    client = genai.Client(api_key=api_key)

    clips_dir = Path(output_dir) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 중복 제거를 위한 캐시: (source_image_key, i2v_prompt) → 파일 경로
    cache: dict[tuple[str, str], str] = {}
    result: dict = {}

    variants = strategy.get("variants", [])

    for var in variants:
        variant_id = var.get("variant_id", "unknown")
        for clip in var.get("clips", []):
            clip_num = clip.get("clip_num", 0)
            source_image_key = clip.get("source_image", "img_1")
            i2v_prompt = clip.get("i2v_prompt", "")

            image_path = image_map.get(source_image_key)
            if not image_path:
                logger.warning(f"[video_generator] {source_image_key} 파일 없음, 스킵")
                continue

            clip_key = f"clip_{variant_id}_{clip_num}"
            cache_key = (source_image_key, i2v_prompt)

            # 중복 체크
            if cache_key in cache:
                existing_path = cache[cache_key]
                result[clip_key] = existing_path
                logger.info(f"[video_generator] {clip_key} — 캐시 재사용: {Path(existing_path).name}")
                continue

            output_path = clips_dir / f"{clip_key}.mp4"

            # 기존 파일 스킵 (체크포인트)
            if output_path.exists():
                logger.info(f"[video_generator] {clip_key} — 기존 파일 사용")
                cache[cache_key] = str(output_path)
                result[clip_key] = str(output_path)
                continue

            logger.info(f"[video_generator] {clip_key} 생성 시작: {source_image_key}")

            success = _generate_clip(client, model, image_path, i2v_prompt, output_path)

            if success:
                cache[cache_key] = str(output_path)
                result[clip_key] = str(output_path)
            else:
                result[clip_key] = None
                logger.error(f"[video_generator] {clip_key} 생성 실패")

            # 요청 간 딜레이
            time.sleep(REQUEST_DELAY)

    logger.info(f"[video_generator] 완료: {len(result)}개 클립")
    return result
