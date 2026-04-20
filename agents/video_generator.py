"""agents/video_generator.py — ⑦ 영상팀 [Veo via google-genai]

strategy.json의 clips 배열 → clips/ 디렉토리에 MP4 저장
- 중복 (source_image, i2v_prompt) 조합은 1회만 생성
- 비동기 폴링, 모델 단위 재시도 3회 + 폴백 체인 (다음 모델로 자동 전환)
"""

import logging
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types

from core.config import get_i2v_config

logger = logging.getLogger(__name__)

POLL_INTERVAL = 10
MAX_POLL_TIME = 300
REQUEST_DELAY = 15.0   # Veo RPM 제한 보호 (preview 티어 ~2 RPM)


def _mime(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower().lstrip(".")
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")


def _is_quota_error(err: Exception) -> bool:
    s = str(err)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "quota" in s.lower()


def _try_one_model(
    client: genai.Client,
    model: str,
    image_path: str,
    i2v_prompt: str,
    output_path: Path,
) -> tuple[bool, bool]:
    """단일 모델 1회 시도. 반환: (success, quota_exhausted).

    quota_exhausted=True면 같은 모델로 재시도해도 무용 → 호출자가 다음 폴백 모델로
    이동. False/False는 일시적 에러로 같은 모델 재시도 가능.
    """
    img_bytes = Path(image_path).read_bytes()
    mime = _mime(image_path)

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
    except Exception as e:
        quota = _is_quota_error(e)
        logger.warning("[video_generator] %s 요청 실패 (quota=%s): %s", model, quota, e)
        return False, quota

    elapsed = 0
    interval = POLL_INTERVAL
    while elapsed < MAX_POLL_TIME:
        time.sleep(interval)
        elapsed += interval
        try:
            operation = client.operations.get(operation)
            if operation.done:
                videos = operation.result.generated_videos
                if not videos:
                    logger.error("[video_generator] %s: 결과 영상 없음", model)
                    return False, False
                video_bytes = client.files.download(file=videos[0].video)
                output_path.write_bytes(bytes(video_bytes))
                logger.info("[video_generator] %s 저장: %s", model, output_path.name)
                return True, False
        except Exception as e:
            quota = _is_quota_error(e)
            logger.warning("[video_generator] %s 폴링 에러 (quota=%s): %s", model, quota, e)
            if quota:
                return False, True
            interval = min(interval * 1.5, 30)

    logger.error("[video_generator] %s 타임아웃 (%ds)", model, MAX_POLL_TIME)
    return False, False


def _generate_clip(
    client: genai.Client,
    models: list[str],
    image_path: str,
    i2v_prompt: str,
    output_path: Path,
) -> tuple[bool, str | None]:
    """폴백 체인. 모델별 최대 3회 시도 (429는 즉시 다음 모델로).

    반환: (success, used_model). 모든 모델 실패 시 (False, None).
    """
    if not models:
        logger.error("[video_generator] 폴백 체인 비어있음")
        return False, None

    delays = [60, 90, 120]  # 모델 내 일시 에러용
    for mi, model in enumerate(models):
        logger.info(
            "[video_generator] 시도 %d/%d: model=%s clip=%s",
            mi + 1, len(models), model, output_path.name,
        )
        for attempt, delay in enumerate(delays, start=1):
            success, quota_exhausted = _try_one_model(
                client, model, image_path, i2v_prompt, output_path,
            )
            if success:
                return True, model
            if quota_exhausted:
                logger.warning(
                    "[video_generator] %s quota 소진 → 다음 폴백 모델로", model,
                )
                break  # 같은 모델 재시도 무의미
            if attempt < len(delays):
                logger.info(
                    "[video_generator] %s attempt %d 일시 실패, %d초 대기",
                    model, attempt, delay // 2,
                )
                time.sleep(delay // 2)
        # 다음 모델 사이 짧은 cool-down (다른 모델 quota도 트리거 방지)
        if mi < len(models) - 1:
            time.sleep(REQUEST_DELAY)

    logger.error("[video_generator] 모든 폴백 모델 실패: %s", output_path.name)
    return False, None


def run(
    strategy: dict,
    images: list[str],
    image_map: dict[str, str],
    output_dir: str,
    models: list[str] | None = None,
) -> dict:
    """strategy.json clips → clips/ 디렉토리에 MP4 저장. 결과 dict 반환.

    models: 폴백 체인. None/[] 이면 config.yaml의 i2v.model 단일 사용
      (기존 호환). 카탈로그 기반 자동 폴백을 원하면 호출자(pipeline_runner)가
      services.i2v_models.normalize_chain(...) 결과를 전달.
    """

    logger.info("[video_generator] 시작 (models=%s)", models)
    cfg = get_i2v_config()
    api_key = cfg["api_key"]

    if not models:
        models = [cfg.get("model", "veo-3.1-lite-generate-preview")]

    client = genai.Client(api_key=api_key)

    clips_dir = Path(output_dir) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

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

            if cache_key in cache:
                existing_path = cache[cache_key]
                result[clip_key] = existing_path
                logger.info(f"[video_generator] {clip_key} — 캐시 재사용: {Path(existing_path).name}")
                continue

            output_path = clips_dir / f"{clip_key}.mp4"

            if output_path.exists():
                logger.info(f"[video_generator] {clip_key} — 기존 파일 사용")
                cache[cache_key] = str(output_path)
                result[clip_key] = str(output_path)
                continue

            logger.info(f"[video_generator] {clip_key} 생성 시작: {source_image_key}")

            success, used = _generate_clip(
                client, models, image_path, i2v_prompt, output_path,
            )

            if success:
                cache[cache_key] = str(output_path)
                result[clip_key] = str(output_path)
                logger.info("[video_generator] %s 성공 (model=%s)", clip_key, used)
            else:
                result[clip_key] = None
                logger.error(f"[video_generator] {clip_key} 생성 실패 (모든 폴백 모델 소진)")

            time.sleep(REQUEST_DELAY)

    logger.info(f"[video_generator] 완료: {len(result)}개 클립")
    return result
