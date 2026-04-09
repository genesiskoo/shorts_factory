"""
이미지 → 9:16 (1080×1920) 전처리 유틸리티
- 가로가 긴 이미지: 세로 맞춰 센터 크롭
- 세로가 긴 이미지: 가로 맞춰 상하 패딩 (배경색 자동 추출)
- 결과 assets/preprocessed/ 에 저장
"""

import sys
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

TARGET_W, TARGET_H = 1080, 1920  # 9:16


def dominant_edge_color(img: Image.Image) -> tuple:
    """이미지 테두리 픽셀의 평균색 → 패딩 배경색"""
    arr = np.array(img.convert("RGB"))
    top    = arr[0, :, :]
    bottom = arr[-1, :, :]
    left   = arr[:, 0, :]
    right  = arr[:, -1, :]
    edge   = np.concatenate([top, bottom, left, right], axis=0)
    return tuple(int(c) for c in edge.mean(axis=0))


def pad_to_ratio(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """원본 비율 유지하면서 target 캔버스에 센터 배치 + 테두리색 패딩"""
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    bg_color = dominant_edge_color(resized)
    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


def crop_to_ratio(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """짧은 쪽 꽉 채우고 긴 쪽 센터 크롭"""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    return resized.crop((x, y, x + target_w, y + target_h))


def preprocess(src_path: str | Path, out_dir: str | Path,
               mode: str = "pad") -> Path:
    """
    mode='pad'  : 원본 전체 보존, 여백 패딩
    mode='crop' : 여백 없이 꽉 채움, 일부 잘림
    """
    src = Path(src_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    img = Image.open(src).convert("RGB")
    w, h = img.size
    current_ratio = w / h
    target_ratio  = TARGET_W / TARGET_H

    if abs(current_ratio - target_ratio) < 0.01:
        result = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
        method = "resize"
    elif mode == "crop":
        result = crop_to_ratio(img, TARGET_W, TARGET_H)
        method = "crop"
    else:
        result = pad_to_ratio(img, TARGET_W, TARGET_H)
        method = "pad"

    out_path = out / f"{src.stem}_916.jpg"
    result.save(out_path, "JPEG", quality=92)

    ratio_str = f"{w}x{h} ({current_ratio:.2f}) -> {TARGET_W}x{TARGET_H} ({method})"
    print(f"  {src.name}: {ratio_str} -> {out_path.name}")
    return out_path


if __name__ == "__main__":
    import requests, tempfile

    PRODUCTS = {
        "gamepad":  "https://m.media-amazon.com/images/I/61YNiiJizXL._SL1500_.jpg",
        "speaker":  "https://m.media-amazon.com/images/I/614f5R8ReXL._AC_SL1500_.jpg",
        "earbuds":  "https://m.media-amazon.com/images/I/71o8Q5XJS5L._AC_SL1500_.jpg",
    }

    ASSETS_DIR = Path(__file__).parent.parent / "assets" / "preprocessed"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    print("이미지 전처리 (9:16 pad)")
    for name, url in PRODUCTS.items():
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        tmp = Path(tempfile.mktemp(suffix=".jpg"))
        tmp.write_bytes(r.content)
        preprocess(tmp, ASSETS_DIR, mode="pad")
        tmp.unlink()

    print(f"\n저장 완료: {ASSETS_DIR}")
    for f in ASSETS_DIR.glob("*.jpg"):
        img = Image.open(f)
        print(f"  {f.name}: {img.size}")
