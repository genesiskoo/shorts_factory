"""
Grok Imagine Video API 테스트 스크립트
- 이미지 URL → 6초 모션 클립 생성 (cinematic / dynamic / lifestyle)
- 비동기 폴링 → mp4 다운로드
"""

import os
import sys
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

# Windows cp949 인코딩 문제 해결
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 프로젝트 루트의 .env 로드
load_dotenv(Path(__file__).parent.parent / ".env")

XAI_API_KEY = os.getenv("XAI_API_KEY")
if not XAI_API_KEY:
    print("[ERROR] XAI_API_KEY가 .env에 없습니다.")
    sys.exit(1)

BASE_URL = "https://api.x.ai/v1"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {XAI_API_KEY}",
}

# 상품별 이미지 URL + 프롬프트 (각 1개씩)
# 이미지 출처: Amazon.com (hiRes CDN)
PRODUCTS = {
    "gamepad": {
        "name": "Xbox Core Wireless Controller Carbon Black",
        "image_url": "https://m.media-amazon.com/images/I/61YNiiJizXL._SL1500_.jpg",
        "prompt": (
            "Dynamic camera orbit around the gaming controller, energetic movement, "
            "vibrant lighting with subtle particle effects, eye-catching product reveal"
        ),
    },
    "speaker": {
        "name": "JBL Flip 6 Portable Bluetooth Speaker",
        "image_url": "https://m.media-amazon.com/images/I/614f5R8ReXL._AC_SL1500_.jpg",
        "prompt": (
            "Product gently floating with a soft bokeh background, "
            "warm natural lighting, lifestyle commercial aesthetic, inviting and aspirational mood"
        ),
    },
    "earbuds": {
        "name": "Sony WF-1000XM5 Wireless Earbuds",
        "image_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
        "prompt": (
            "Slowly zoom in on the earbuds with soft studio lighting, "
            "elegant product showcase, smooth camera movement, premium commercial feel"
        ),
    },
}


def request_video(key: str, image_url: str, prompt: str) -> str:
    """영상 생성 요청 → request_id 반환"""
    print(f"\n[{key}] 생성 요청 중...")
    resp = requests.post(
        f"{BASE_URL}/videos/generations",
        headers=HEADERS,
        json={
            "model": "grok-imagine-video",
            "prompt": prompt,
            "image": {"url": image_url},
            "duration": 6,
            "aspect_ratio": "9:16",
            "resolution": "720p",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    request_id = data.get("request_id") or data.get("id")
    if not request_id:
        raise ValueError(f"request_id 없음. 응답: {data}")
    print(f"  request_id: {request_id}")
    return request_id


def poll_video(request_id: str, prompt_name: str, poll_interval: int = 5, timeout: int = 300) -> str:
    """폴링 → 완료 시 video URL 반환"""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        result = requests.get(
            f"{BASE_URL}/videos/{request_id}",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            timeout=15,
        )
        result.raise_for_status()
        data = result.json()
        status = data.get("status", "unknown")
        print(f"  [{prompt_name}] 폴링 #{attempt} - status: {status}")

        if status == "done":
            # 응답 구조에 따라 URL 추출 시도
            video_url = (
                data.get("video", {}).get("url")
                or data.get("url")
                or data.get("output_url")
            )
            if not video_url:
                raise ValueError(f"video URL 없음. 응답: {data}")
            return video_url
        elif status == "error":
            raise RuntimeError(f"API 오류: {data.get('error', data)}")

        time.sleep(poll_interval)

    raise TimeoutError(f"{prompt_name}: {timeout}초 내 완료되지 않음")


def download_video(url: str, filename: str) -> Path:
    """mp4 다운로드"""
    out_path = OUTPUT_DIR / filename
    print(f"  다운로드 중 → {out_path}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                f.write(chunk)
                downloaded += len(chunk)
        size_mb = downloaded / 1024 / 1024
    print(f"  완료: {size_mb:.1f} MB")
    return out_path


def main():
    print("=" * 60)
    print("Grok Imagine Video API 상품 테스트")
    print("상품 3종 x 프롬프트 1개 = 총 3개 클립")
    print("=" * 60)

    results = {}

    for key, product in PRODUCTS.items():
        print(f"\n  상품: {product['name']}")
        print(f"  이미지: {product['image_url']}")
        try:
            request_id = request_video(key, product["image_url"], product["prompt"])
            video_url = poll_video(request_id, key)
            out_path = download_video(video_url, f"product_{key}.mp4")
            results[key] = {"status": "OK", "path": str(out_path)}
        except Exception as e:
            print(f"  [ERROR] {key}: {e}")
            results[key] = {"status": "ERROR", "error": str(e)}

    print("\n" + "=" * 60)
    print("결과 요약")
    print("=" * 60)
    for key, info in results.items():
        name = PRODUCTS[key]["name"]
        if info["status"] == "OK":
            print(f"  [OK]   {name}")
            print(f"         -> {info['path']}")
        else:
            print(f"  [FAIL] {name}")
            print(f"         -> {info['error']}")

    ok_count = sum(1 for v in results.values() if v["status"] == "OK")
    print(f"\n총 {ok_count}/{len(PRODUCTS)}개 성공")
    if ok_count == len(PRODUCTS):
        print("-> Day 2 진행 가능 (MoviePy 뼈대 + Pillow 텍스트)")
    else:
        print("-> 실패 항목 확인 필요")


if __name__ == "__main__":
    main()
