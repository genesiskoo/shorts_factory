"""test_veo_lite.py — Veo 3.1 I2V 단독 검증 스크립트

사용법:
    python test_veo_lite.py <이미지경로>

모델 우선순위:
    veo-3.1-lite-generate-preview → 실패 시 veo-3.1-fast-generate-preview
"""

import io
import os
import sys
import time
from pathlib import Path

# Windows CP949 터미널에서 한글/유니코드 깨짐 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from google import genai
from google.genai import types as genai_types

# .env 로드 (python-dotenv 없어도 동작)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()

MODELS = [
    "veo-3.1-lite-generate-preview",
    "veo-3.1-fast-generate-preview",
]

PROMPT = "Slowly zoom in on the product with soft studio lighting, elegant product showcase, smooth camera movement, premium commercial feel"


def _mime(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")


def test_model(client, model: str, image_path: str) -> bool:
    print(f"\n[{model}] 시작...")

    img_bytes = Path(image_path).read_bytes()
    mime = _mime(image_path)

    try:
        operation = client.models.generate_videos(
            model=model,
            prompt=PROMPT,
            image=genai_types.Image(image_bytes=img_bytes, mime_type=mime),
            config=genai_types.GenerateVideosConfig(
                aspect_ratio="9:16",
                number_of_videos=1,
            ),
        )
    except Exception as e:
        print(f"[{model}] 생성 요청 실패: {e}")
        return False

    print(f"[{model}] 요청 수락됨 - 폴링 시작 (최대 5분)...")
    elapsed = 0
    interval = 10

    while elapsed < 300:
        time.sleep(interval)
        elapsed += interval

        try:
            operation = client.operations.get(operation)
            print(f"[{model}] done={operation.done} ({elapsed}s)", end="\r")

            if operation.done:
                print()
                videos = operation.result.generated_videos
                if not videos:
                    print(f"[{model}] 결과 영상 없음 (생성 실패)")
                    return False

                out_dir = Path("output")
                out_dir.mkdir(exist_ok=True)
                tag = "lite" if "lite" in model else "fast"
                out_path = out_dir / f"test_veo_{tag}.mp4"

                video_file = videos[0].video
                video_bytes = client.files.download(file=video_file)
                out_path.write_bytes(bytes(video_bytes))
                size_mb = out_path.stat().st_size / 1024 / 1024
                print(f"[{model}] SUCCESS -> {out_path} ({size_mb:.1f} MB)")
                return True

        except Exception as e:
            print(f"\n[{model}] 폴링 에러: {e}")
            interval = min(interval * 1.5, 30)

    print(f"\n[{model}] 타임아웃 (300s 초과)")
    return False


def main():
    if len(sys.argv) < 2:
        print("사용법: python test_veo_lite.py <이미지경로>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not Path(image_path).exists():
        print(f"이미지 파일 없음: {image_path}")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY 환경변수가 없습니다")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    for model in MODELS:
        if test_model(client, model, image_path):
            print(f"\n확정 모델: {model}")
            print("→ config.yaml의 i2v.model을 이 값으로 설정하세요")
            break
        else:
            if model != MODELS[-1]:
                print(f"→ {MODELS[MODELS.index(model) + 1]} 시도합니다...")
    else:
        print("\n모든 모델 실패. config.yaml 모델명 또는 API 키를 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
