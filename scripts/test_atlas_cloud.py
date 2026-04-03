"""
Atlas Cloud API 비교 테스트
모델: Seedance 1.5 Fast / Hailuo 02 Standard (i2v)
상품 3종 x 모델 2종 = 6개 클립
파일명: {product}_{model_short}.mp4
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

ATLAS_API_KEY = os.getenv("ATLAS_API_KEY")
if not ATLAS_API_KEY:
    print("[ERROR] ATLAS_API_KEY가 .env에 없습니다.")
    sys.exit(1)

BASE_URL = "https://api.atlascloud.ai/api/v1/model"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {ATLAS_API_KEY}",
}

# 상품 3종 (Grok 테스트와 동일한 이미지 + 잘 나온 프롬프트 1종씩)
PRODUCTS = {
    "gamepad": {
        "name": "Xbox Core Wireless Controller",
        "image_url": "https://m.media-amazon.com/images/I/61YNiiJizXL._SL1500_.jpg",
        "prompt": (
            "Cinematic product reveal with dramatic lighting, shallow depth of field, "
            "subtle lens flare, high-end commercial photography feel"
        ),
    },
    "speaker": {
        "name": "JBL Flip 6 Bluetooth Speaker",
        "image_url": "https://m.media-amazon.com/images/I/614f5R8ReXL._AC_SL1500_.jpg",
        "prompt": (
            "Product gently floating with subtle light rays, soft bokeh background, "
            "warm natural lighting, premium advertising aesthetic"
        ),
    },
    "earbuds": {
        "name": "Sony WF-1000XM5 Earbuds",
        "image_url": "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
        "prompt": (
            "Slowly zoom in on the product with soft studio lighting, "
            "elegant product showcase, smooth camera movement, premium commercial feel"
        ),
    },
}

# 테스트 모델 2종
MODELS = {
    "seedance_fast": "bytedance/seedance-v1.5-pro/image-to-video-fast",
    "hailuo_standard": "minimax/hailuo-02/i2v-standard",
}


def _unwrap(resp_json: dict) -> dict:
    """Atlas Cloud 응답은 { code, data: {...} } 래퍼 구조"""
    if "data" in resp_json:
        return resp_json["data"]
    return resp_json


def request_video(model_id: str, image_url: str, prompt: str, label: str) -> str:
    """영상 생성 요청 → prediction id 반환"""
    resp = requests.post(
        f"{BASE_URL}/generateVideo",
        headers=HEADERS,
        json={
            "model": model_id,
            "prompt": prompt,
            "image_url": image_url,
            "duration": 6,
            "aspect_ratio": "9:16",
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = _unwrap(resp.json())
    pred_id = data.get("id") or data.get("request_id")
    if not pred_id:
        raise ValueError(f"prediction id 없음. 응답: {data}")
    print(f"  [{label}] id: {pred_id}")
    return pred_id


def poll_video(pred_id: str, label: str, poll_interval: int = 8, timeout: int = 600) -> str:
    """폴링 → 완료 시 video URL 반환"""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        result = requests.get(
            f"{BASE_URL}/prediction/{pred_id}",
            headers={"Authorization": f"Bearer {ATLAS_API_KEY}"},
            timeout=15,
        )
        if not result.ok:
            raise RuntimeError(f"폴링 HTTP {result.status_code}: {result.text[:200]}")
        data = _unwrap(result.json())
        status = data.get("status", "unknown")
        print(f"  [{label}] 폴링 #{attempt} - {status}")

        if status in ("completed", "succeeded"):
            outputs = data.get("outputs") or []
            if outputs:
                return outputs[0]
            video_url = data.get("video_url") or data.get("url")
            if video_url:
                return video_url
            raise ValueError(f"video URL 없음. 응답: {data}")
        elif status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"생성 실패: {data.get('error', data)}")

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
    combos = [(pk, mk) for pk in PRODUCTS for mk in MODELS]

    print("=" * 65)
    print(f"Atlas Cloud API 모델 비교 테스트 — 총 {len(combos)}개")
    print(f"상품 {len(PRODUCTS)}종 x 모델 {len(MODELS)}종")
    for mk, mid in MODELS.items():
        print(f"  {mk}: {mid}")
    print("=" * 65)

    results = {}

    for idx, (pk, mk) in enumerate(combos, 1):
        label = f"{pk}_{mk}"
        product = PRODUCTS[pk]
        model_id = MODELS[mk]
        filename = f"{label}.mp4"

        print(f"\n[{idx}/{len(combos)}] {product['name']} / {mk}")
        print(f"  모델: {model_id}")
        try:
            pred_id = request_video(model_id, product["image_url"], product["prompt"], label)
            video_url = poll_video(pred_id, label)
            out_path = download_video(video_url, filename)
            results[label] = {"status": "OK", "path": str(out_path)}
        except Exception as e:
            print(f"  [ERROR] {e}")
            results[label] = {"status": "ERROR", "error": str(e)}

    print("\n" + "=" * 65)
    print("결과 요약")
    print("=" * 65)
    ok = 0
    for label, info in results.items():
        pk, mk = label.rsplit("_", 1)
        name = PRODUCTS.get(pk, {}).get("name", pk)
        if info["status"] == "OK":
            print(f"  [OK]   {name} / {mk}")
            ok += 1
        else:
            print(f"  [FAIL] {name} / {mk} -- {info['error']}")

    print(f"\n총 {ok}/{len(combos)}개 성공")


if __name__ == "__main__":
    main()
