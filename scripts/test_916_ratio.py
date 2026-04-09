"""
Hailuo 02 i2v-standard 9:16 비율 테스트

Method A: Pillow로 1080x1920 리사이즈 → base64 인코딩 → API 호출
Method B: 원본 이미지 URL + aspect_ratio="9:16" 파라미터 → API 호출

출력 클립의 실제 해상도를 ffprobe로 측정해서 어느 방식이 9:16인지 확인
"""

import os, sys, time, base64, subprocess, requests
from io import BytesIO
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).parent.parent / ".env")
KEY  = os.getenv("ATLAS_API_KEY")
BASE = "https://api.atlascloud.ai/api/v1/model"
OUT  = Path(__file__).parent.parent / "output"
OUT.mkdir(exist_ok=True)

HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}
MODEL   = "minimax/hailuo-02/i2v-standard"

FFPROBE = (
    r"C:\Users\FORYOUCOM\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffprobe.exe"
)

# 테스트 상품 1개 (gamepad)
PRODUCT_NAME = "Xbox Core Wireless Controller"
IMAGE_URL    = "https://m.media-amazon.com/images/I/61YNiiJizXL._SL1500_.jpg"
PROMPT       = (
    "Cinematic product reveal with dramatic lighting, "
    "shallow depth of field, subtle lens flare, high-end commercial feel"
)


# ── 유틸 ──────────────────────────────────────────────────────────────────

def _unwrap(j: dict) -> dict:
    return j["data"] if "data" in j else j

def to_916_base64(url: str) -> str:
    """이미지 URL → 1080x1920 pad → base64 data URI"""
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    img = Image.open(BytesIO(r.content)).convert("RGB")
    w, h = img.size

    # 9:16 pad (원본 비율 유지, 여백은 테두리 평균색)
    import numpy as np
    target_w, target_h = 1080, 1920
    scale  = min(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = img.resize((nw, nh), Image.LANCZOS)

    arr    = np.array(resized)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    bg     = tuple(int(c) for c in border.mean(axis=0))

    canvas = Image.new("RGB", (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - nw) // 2, (target_h - nh) // 2))

    buf = BytesIO()
    canvas.save(buf, "JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()
    print(f"  [전처리] {w}x{h} -> {target_w}x{target_h} (pad, {len(b64)//1024}KB base64)")
    return f"data:image/jpeg;base64,{b64}"

def request_video(payload: dict, label: str) -> str:
    r = requests.post(f"{BASE}/generateVideo", headers=HEADERS,
                      json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    d = _unwrap(r.json())
    pid = d.get("id")
    if not pid:
        raise ValueError(f"id 없음: {d}")
    print(f"  [{label}] id={pid}")
    return pid

def poll_and_download(pid: str, label: str, timeout: int = 300) -> Path:
    deadline = time.time() + timeout
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        r = requests.get(f"{BASE}/prediction/{pid}",
                         headers={"Authorization": f"Bearer {KEY}"}, timeout=15)
        d = _unwrap(r.json())
        status = d.get("status", "?")
        print(f"  [{label}] #{attempt} {status}")
        if status in ("completed", "succeeded"):
            url = (d.get("outputs") or [None])[0] or d.get("video_url")
            if not url:
                raise ValueError(f"URL 없음: {d}")
            fname = OUT / f"ratio_test_{label}.mp4"
            n = 0
            with requests.get(url, stream=True, timeout=120) as dl:
                dl.raise_for_status()
                with open(fname, "wb") as f:
                    for chunk in dl.iter_content(65536):
                        f.write(chunk); n += len(chunk)
            print(f"  [{label}] -> {fname.name} ({n/1024/1024:.1f}MB)")
            return fname
        elif status in ("failed", "error", "cancelled"):
            raise RuntimeError(d.get("error", status))
        time.sleep(8)
    raise TimeoutError(f"{timeout}s 초과")

def probe_resolution(path: Path) -> str:
    """ffprobe로 실제 해상도 측정"""
    try:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10
        )
        out = result.stdout.strip()
        if out:
            parts = out.split(",")
            w, h = parts[0], parts[1]
            dur  = parts[2] if len(parts) > 2 else "?"
            ratio = float(h) / float(w) if float(w) > 0 else 0
            return f"{w}x{h} (비율 {ratio:.3f}, 9:16={16/9:.3f}) dur={dur}s"
    except Exception as e:
        return f"probe 실패: {e}"
    return "unknown"


# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Hailuo 02 9:16 비율 테스트")
    print(f"상품: {PRODUCT_NAME}")
    print("=" * 60)

    results = {}

    # ── Method A: Pillow 전처리 → base64 ──
    print("\n[Method A] Pillow 1080x1920 → base64")
    try:
        b64_uri = to_916_base64(IMAGE_URL)
        pid_a = request_video({
            "model":     MODEL,
            "prompt":    PROMPT,
            "image_url": b64_uri,
            "duration":  5,
        }, "A_pillow_base64")
        path_a = poll_and_download(pid_a, "A_pillow_base64")
        results["A_pillow_base64"] = probe_resolution(path_a)
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["A_pillow_base64"] = f"FAIL: {e}"

    # ── Method B: 원본 URL + aspect_ratio 파라미터 ──
    print("\n[Method B] 원본 URL + aspect_ratio=9:16")
    try:
        pid_b = request_video({
            "model":        MODEL,
            "prompt":       PROMPT,
            "image_url":    IMAGE_URL,
            "duration":     5,
            "aspect_ratio": "9:16",
        }, "B_param_ratio")
        path_b = poll_and_download(pid_b, "B_param_ratio")
        results["B_param_ratio"] = probe_resolution(path_b)
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["B_param_ratio"] = f"FAIL: {e}"

    print("\n" + "=" * 60)
    print("결과 요약")
    print("=" * 60)
    for method, res in results.items():
        print(f"  {method}: {res}")


if __name__ == "__main__":
    main()
