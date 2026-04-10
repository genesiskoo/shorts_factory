"""agents/video_generator.py — ⑦ 영상팀 [Grok Imagine API]

strategy.json의 clips 배열 → clips/ 디렉토리에 MP4 저장
- 중복 (source_image, i2v_prompt) 조합은 1회만 생성
- 비동기 폴링, exponential backoff
"""

import logging
import time
from pathlib import Path

import requests

from core.config import get_i2v_config

logger = logging.getLogger(__name__)

GROK_VIDEO_URL = "https://api.x.ai/v1/videos/generations"
GROK_VIDEO_STATUS_URL = "https://api.x.ai/v1/videos/{request_id}"

# 폴링 설정
POLL_INTERVAL = 5      # 초
MAX_POLL_TIME = 300    # 최대 5분
REQUEST_DELAY = 2.5    # 요청 간 딜레이


def _generate_clip(
    api_key: str,
    image_path: str,
    i2v_prompt: str,
    output_path: Path,
) -> bool:
    """단일 클립 생성. 성공시 True, 실패시 False."""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    # 이미지를 base64로 인코딩
    import base64
    img_bytes = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    # 1. 생성 요청
    payload = {
        "model": "grok-imagine-video",
        "prompt": i2v_prompt,
        "image": {"b64_json": img_b64},
        "duration": 6,
        "aspect_ratio": "9:16",
        "resolution": "720p",
    }

    delays = [3, 6, 12]
    request_id = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            resp = requests.post(GROK_VIDEO_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            request_id = data.get("request_id") or data.get("id")
            if request_id:
                break
        except Exception as e:
            logger.warning(f"[video_generator] 생성 요청 실패 attempt {attempt}: {e}")
            if attempt < len(delays):
                time.sleep(delay)
            else:
                return False

    if not request_id:
        logger.error("[video_generator] request_id 획득 실패")
        return False

    # 2. 폴링
    elapsed = 0
    interval = POLL_INTERVAL

    while elapsed < MAX_POLL_TIME:
        time.sleep(interval)
        elapsed += interval

        try:
            status_resp = requests.get(
                GROK_VIDEO_STATUS_URL.format(request_id=request_id),
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            status = status_data.get("status", "")
            logger.debug(f"[video_generator] {request_id} 상태: {status} ({elapsed}s)")

            if status == "done" or status == "succeeded":
                video_url = (
                    status_data.get("video", {}).get("url")
                    or status_data.get("url")
                )
                if not video_url:
                    logger.error(f"[video_generator] video URL 없음: {status_data}")
                    return False

                # 다운로드
                dl = requests.get(video_url, timeout=120)
                dl.raise_for_status()
                output_path.write_bytes(dl.content)
                logger.info(f"[video_generator] 저장: {output_path.name}")
                return True

            elif status in ("error", "failed"):
                logger.error(f"[video_generator] 생성 실패: {status_data.get('error')}")
                return False

            # processing 중이면 interval 점진적 증가 (최대 15초)
            interval = min(interval * 1.2, 15)

        except Exception as e:
            logger.warning(f"[video_generator] 폴링 에러: {e}")
            interval = min(interval * 1.5, 20)

    logger.error(f"[video_generator] 타임아웃 ({MAX_POLL_TIME}s): {request_id}")
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

    clips_dir = Path(output_dir) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 중복 제거를 위한 캐시: (source_image, i2v_prompt) → 파일 경로
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

            # 기존 파일 스킵
            if output_path.exists():
                logger.info(f"[video_generator] {clip_key} — 기존 파일 사용")
                cache[cache_key] = str(output_path)
                result[clip_key] = str(output_path)
                continue

            logger.info(f"[video_generator] {clip_key} 생성 시작: {source_image_key}")

            success = _generate_clip(api_key, image_path, i2v_prompt, output_path)

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
