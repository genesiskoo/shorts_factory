"""
Grok Imagine Video API 프롬프트 비교 테스트
- 상품 3종 x 프롬프트 3종 = 9개 클립
- 파일명: {product}_{prompt}.mp4
"""

import os
import sys
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

PRODUCTS = {
    "gamepad": {
        "name": "Xbox Core Wireless Controller",
        "image_url": "https://m.media-amazon.com/images/I/61YNiiJizXL._SL1500_.jpg",
    },
    "speaker": {
        "name": "JBL Flip 6 Bluetooth Speaker",
        "image_url": "https://m.media-amazon.com/images/I/614f5R8ReXL._AC_SL1500_.jpg",
    },
    "earbuds": {
        "name": "Sony WF-1000XM5 Earbuds",
        "image_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
    },
}

PROMPTS = {
    "zoom": (
        "Slowly zoom in on the product with soft studio lighting, "
        "elegant product showcase, smooth camera movement, premium commercial feel"
    ),
    "float": (
        "Product gently floating with subtle light rays, soft bokeh background, "
        "warm natural lighting, premium advertising aesthetic"
    ),
    "reveal": (
        "Cinematic product reveal with dramatic lighting, shallow depth of field, "
        "subtle lens flare, high-end commercial photography feel"
    ),
}


def request_video(image_url: str, prompt: str, label: str) -> str:
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
    print(f"  [{label}] request_id: {request_id}")
    return request_id


def poll_video(request_id: str, label: str, poll_interval: int = 5, timeout: int = 300) -> str:
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
        print(f"  [{label}] 폴링 #{attempt} - {status}")

        if status == "done":
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

    raise TimeoutError(f"{label}: {timeout}초 내 완료되지 않음")


def download_video(url: str, filename: str) -> Path:
    out_path = OUTPUT_DIR / filename
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        downloaded = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                f.write(chunk)
                downloaded += len(chunk)
    size_mb = downloaded / 1024 / 1024
    print(f"  -> {out_path.name} ({size_mb:.1f} MB)")
    return out_path


def main():
    combos = [
        (pk, pp)
        for pk in PRODUCTS
        for pp in PROMPTS
    ]

    print("=" * 65)
    print(f"Grok Imagine 프롬프트 비교 테스트 — 총 {len(combos)}개")
    print(f"상품 {len(PRODUCTS)}종 x 프롬프트 {len(PROMPTS)}종")
    print("=" * 65)

    results = {}

    for idx, (pk, pp) in enumerate(combos, 1):
        label = f"{pk}_{pp}"
        product = PRODUCTS[pk]
        prompt = PROMPTS[pp]
        print(f"\n[{idx}/{len(combos)}] {product['name']} / {pp}")
        try:
            request_id = request_video(product["image_url"], prompt, label)
            video_url = poll_video(request_id, label)
            out_path = download_video(video_url, f"{label}.mp4")
            results[label] = {"status": "OK", "path": str(out_path)}
        except Exception as e:
            print(f"  [ERROR] {e}")
            results[label] = {"status": "ERROR", "error": str(e)}

    print("\n" + "=" * 65)
    print("결과 요약")
    print("=" * 65)
    ok_count = 0
    for label, info in results.items():
        pk, pp = label.rsplit("_", 1)
        name = PRODUCTS[pk]["name"]
        if info["status"] == "OK":
            print(f"  [OK]   {name} / {pp}")
            ok_count += 1
        else:
            print(f"  [FAIL] {name} / {pp} — {info['error']}")

    print(f"\n총 {ok_count}/{len(combos)}개 성공")


if __name__ == "__main__":
    main()
