"""
숏폼 파이프라인 빌더 (Day 2)
- 영상 클립 3개 연결 (720x1280 → 1080x1920 스케일)
- TTS mp3 + 더미 BGM 합성
- Pillow 한글 텍스트 오버레이 (상품명, 가격, CTA)
- SRT 자막 오버레이
- 상단 배너 + 하단 CTA 바

사용:
    python scripts/build_shorts.py
"""

import sys, re, os, logging, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# FFmpeg 경로 환경변수로 설정 (MoviePy 2.x는 ffmpeg_binary 파라미터 없음)
os.environ["FFMPEG_BINARY"] = (
    r"C:\Users\FORYOUCOM\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)

# ── 경로 ────────────────────────────────────────────────────────────────────
ROOT   = Path(__file__).parent.parent
OUTPUT = ROOT / "output"
TTS_DIR = OUTPUT / "tts"

FFMPEG_BIN = (
    r"C:\Users\FORYOUCOM\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)

# ── 영상 클립 3개 ─────────────────────────────────────────────────────────
CLIP_FILES = [
    OUTPUT / "earbuds_zoom.mp4",
    OUTPUT / "earbuds_float.mp4",
    OUTPUT / "earbuds_reveal.mp4",
]

TTS_FILE = TTS_DIR / "레드미.mp3"
SRT_FILE = TTS_DIR / "레드미.srt"
OUT_FILE = OUTPUT / "shorts_레드미.mp4"
BGM_FILE = ROOT / "kornevmusic-epic-478847.mp3"

# ── 영상 스펙 ────────────────────────────────────────────────────────────
TARGET_W, TARGET_H = 1080, 1920
FPS = 24

# ── 폰트 ─────────────────────────────────────────────────────────────────
FONT_BOLD   = r"C:\Windows\Fonts\malgunbd.ttf"
FONT_NORMAL = r"C:\Windows\Fonts\malgun.ttf"

# ── 상품 메타 ─────────────────────────────────────────────────────────────
PRODUCT_NAME  = "레드미 Buds 8 Pro"
PRICE_TEXT    = "₩ 49,900"
CTA_TEXT      = "지금 바로 구매하기 →"
CHANNEL_NAME  = "@해외직구연구소"

# ── 로깅 ─────────────────────────────────────────────────────────────────
TOTAL_STEPS = 5

logger = logging.getLogger("pipeline")


class StepTimer:
    """단계 시작/완료 로그 + 소요시간 측정"""
    def __init__(self, step: int, start_msg: str):
        self._step = step
        self._t0 = time.perf_counter()
        logger.info(f"[{step}/{TOTAL_STEPS}] {start_msg}")

    def done(self, msg: str) -> float:
        elapsed = time.perf_counter() - self._t0
        logger.info(f"[{self._step}/{TOTAL_STEPS}] {msg} ({elapsed:.1f}초)")
        return elapsed


# ════════════════════════════════════════════════════════════════════════════
# Pillow 유틸
# ════════════════════════════════════════════════════════════════════════════

def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def text_image(text: str, font_path: str, font_size: int,
               color: tuple, canvas_w: int, canvas_h: int,
               align: str = "center") -> np.ndarray:
    """투명 RGBA 캔버스에 텍스트 → numpy 배열"""
    img  = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_font(font_path, font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if align == "center":
        x = (canvas_w - tw) // 2
    elif align == "left":
        x = 24
    else:
        x = canvas_w - tw - 24
    y = (canvas_h - th) // 2

    # 그림자
    draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0, 160))
    draw.text((x,   y),   text, font=font, fill=color)
    return np.array(img)


def rect_image(w: int, h: int, color: tuple) -> np.ndarray:
    """단색 RGBA 사각형"""
    img = Image.new("RGBA", (w, h), color)
    return np.array(img)


def multiline_text_image(text: str, font_path: str, font_size: int,
                          color: tuple, canvas_w: int, canvas_h: int,
                          align: str = "center") -> np.ndarray:
    """줄바꿈 포함 텍스트"""
    img  = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = load_font(font_path, font_size)
    lines = text.split("\n")
    line_h = font_size + 6
    total_h = line_h * len(lines)
    y_start = (canvas_h - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        if align == "center":
            x = (canvas_w - tw) // 2
        elif align == "left":
            x = 24
        else:
            x = canvas_w - tw - 24
        y = y_start + i * line_h
        draw.text((x+2, y+2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x,   y),   line, font=font, fill=color)
    return np.array(img)


# ════════════════════════════════════════════════════════════════════════════
# SRT 파싱
# ════════════════════════════════════════════════════════════════════════════

def parse_srt(path: Path) -> list[dict]:
    """SRT → [{start, end, text}, ...] (초 단위)"""
    text   = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", text.strip())
    subs   = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        # timecode line
        tc = lines[1]
        m  = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", tc
        )
        if not m:
            continue
        g  = [int(x) for x in m.groups()]
        start = g[0]*3600 + g[1]*60 + g[2] + g[3]/1000
        end   = g[4]*3600 + g[5]*60 + g[6] + g[7]/1000
        txt   = "\n".join(lines[2:]).strip()
        subs.append({"start": start, "end": end, "text": txt})
    return subs


# ════════════════════════════════════════════════════════════════════════════
# MoviePy 조합
# ════════════════════════════════════════════════════════════════════════════

def load_bgm(path: Path, duration: float) -> "AudioClip":
    """BGM mp3 로드 → duration 길이로 루프/트림, 볼륨 0.12"""
    from moviepy import AudioFileClip, concatenate_audioclips
    from moviepy.audio.fx import MultiplyVolume

    raw = AudioFileClip(str(path))
    if raw.duration < duration:
        n = int(duration / raw.duration) + 1
        raw = concatenate_audioclips([raw] * n)
    return raw.with_duration(duration).with_effects([MultiplyVolume(0.12)])


def build(config: dict | None = None):
    from moviepy import (
        VideoFileClip, AudioFileClip, AudioClip,
        concatenate_videoclips, ImageClip, CompositeVideoClip,
        CompositeAudioClip,
    )
    from moviepy.video.fx import Resize

    cfg = config or {}
    clip_files   = cfg.get("clips",    CLIP_FILES)
    tts_file     = cfg.get("tts",      TTS_FILE)
    srt_file     = cfg.get("srt",      SRT_FILE)
    out_file     = cfg.get("output",   OUT_FILE)
    product_name = cfg.get("product",  PRODUCT_NAME)
    price        = cfg.get("price",    PRICE_TEXT)
    cta          = cfg.get("cta",      CTA_TEXT)
    channel      = cfg.get("channel",  CHANNEL_NAME)
    bgm_path     = cfg.get("bgm",      BGM_FILE)

    # ══════════════════════════════════════════════════════════════════════
    # Step 4: 영상 합성 (MoviePy) — 클립 로드 + 리사이즈 + TTS + BGM 믹싱
    # ══════════════════════════════════════════════════════════════════════
    step4 = StepTimer(4, "영상 합성 중... (MoviePy)")

    raw_clips = []
    for p in clip_files:
        c = VideoFileClip(str(p))
        c = c.with_effects([Resize((TARGET_W, TARGET_H))])
        raw_clips.append(c)
        logger.info(f"    {Path(p).name}: {c.size} {c.duration:.2f}s")

    video = concatenate_videoclips(raw_clips, method="compose")
    total_dur = video.duration

    tts = AudioFileClip(str(tts_file))
    tts_dur = tts.duration

    # 영상 길이 맞추기: TTS보다 짧으면 마지막 클립 반복
    if total_dur < tts_dur + 0.5:
        extra = int((tts_dur - total_dur) / 6) + 1
        raw_clips.extend([raw_clips[-1]] * extra)
        video = concatenate_videoclips(raw_clips, method="compose")
        total_dur = video.duration

    # TTS가 영상보다 길면 영상을 TTS 길이로 맞춤
    if tts_dur > total_dur:
        tts = tts.with_duration(total_dur)
    else:
        video = video.with_duration(tts_dur + 0.3)
        total_dur = video.duration

    bgm = load_bgm(bgm_path, total_dur)
    mixed_audio = CompositeAudioClip([bgm, tts])
    video = video.with_audio(mixed_audio)

    step4.done(f"영상 합성 완료 — {TARGET_W}x{TARGET_H}, {total_dur:.1f}초")

    # ══════════════════════════════════════════════════════════════════════
    # Step 5: 오버레이 적용 (Pillow) + 최종 렌더링
    # ══════════════════════════════════════════════════════════════════════
    step5 = StepTimer(5, "오버레이 적용 중... (Pillow)")

    # 상단 배너 (배경 + 채널명)
    banner_h = 80
    banner_bg = rect_image(TARGET_W, banner_h, (0, 0, 0, 180))
    banner_txt = text_image(channel, FONT_BOLD, 36,
                            (255, 255, 255, 255), TARGET_W, banner_h)
    banner_arr = banner_bg.copy()
    alpha = banner_txt[:, :, 3:4] / 255.0
    banner_arr[:, :, :3] = (
        banner_txt[:, :, :3] * alpha + banner_arr[:, :, :3] * (1 - alpha)
    ).astype(np.uint8)
    banner_arr[:, :, 3] = np.maximum(banner_arr[:, :, 3], banner_txt[:, :, 3])

    banner_clip = (
        ImageClip(banner_arr, transparent=True)
        .with_position(("center", 0))
        .with_duration(total_dur)
    )

    # 상품명 텍스트
    name_h = 110
    name_arr = text_image(product_name, FONT_BOLD, 68,
                          (255, 255, 255, 255), TARGET_W, name_h)
    name_clip = (
        ImageClip(name_arr, transparent=True)
        .with_position(("center", TARGET_H - 420))
        .with_duration(total_dur)
    )

    # 가격 텍스트 (금색 + 굵게 + 크게)
    price_h = 90
    price_arr = text_image(price, FONT_BOLD, 64,
                           (255, 215, 0, 255), TARGET_W, price_h)
    price_clip = (
        ImageClip(price_arr, transparent=True)
        .with_position(("center", TARGET_H - 310))
        .with_duration(total_dur)
    )

    # 하단 CTA 바 (높이 확대)
    cta_h = 150
    cta_bg = rect_image(TARGET_W, cta_h, (255, 69, 0, 240))
    cta_txt_arr = text_image(cta, FONT_BOLD, 48,
                              (255, 255, 255, 255), TARGET_W, cta_h)
    cta_bg_alpha = cta_bg.copy()
    alpha = cta_txt_arr[:, :, 3:4] / 255.0
    cta_bg_alpha[:, :, :3] = (
        cta_txt_arr[:, :, :3] * alpha + cta_bg_alpha[:, :, :3] * (1 - alpha)
    ).astype(np.uint8)
    cta_bg_alpha[:, :, 3] = np.maximum(cta_bg_alpha[:, :, 3], cta_txt_arr[:, :, 3])

    cta_clip = (
        ImageClip(cta_bg_alpha, transparent=True)
        .with_position(("center", TARGET_H - cta_h))
        .with_duration(total_dur)
    )

    # SRT 자막
    subs = parse_srt(srt_file)
    subtitle_clips = []
    sub_h = 120

    for sub in subs:
        if sub["end"] > total_dur:
            break
        txt = sub["text"].replace("\n", " ")
        if len(txt) > 20:
            mid = len(txt) // 2
            space_idx = txt.rfind(" ", 0, mid + 5)
            if space_idx > 0:
                txt = txt[:space_idx] + "\n" + txt[space_idx+1:]

        sub_arr = multiline_text_image(
            txt, FONT_BOLD, 38,
            (255, 255, 255, 255), TARGET_W, sub_h
        )
        bg = rect_image(TARGET_W, sub_h, (0, 0, 0, 200))
        alpha = sub_arr[:, :, 3:4] / 255.0
        bg[:, :, :3] = (
            sub_arr[:, :, :3] * alpha + bg[:, :, :3] * (1 - alpha)
        ).astype(np.uint8)
        bg[:, :, 3] = np.maximum(bg[:, :, 3], sub_arr[:, :, 3])

        sc = (
            ImageClip(bg, transparent=True)
            .with_start(sub["start"])
            .with_duration(sub["end"] - sub["start"])
            .with_position(("center", TARGET_H - cta_h - sub_h - 10))
        )
        subtitle_clips.append(sc)

    logger.info(
        f"    오버레이: 배너 + 상품명 + 가격 + CTA + 자막 {len(subtitle_clips)}개"
    )

    # 최종 합성 + 렌더링
    layers = [video, banner_clip, name_clip, price_clip, cta_clip] + subtitle_clips
    final = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H))
    final = final.with_duration(total_dur)

    final.write_videofile(
        str(out_file),
        fps=FPS,
        codec="h264_nvenc",
        audio_codec="aac",
        temp_audiofile=str(out_file.parent / "_tmp_audio.m4a"),
        remove_temp=True,
        ffmpeg_params=["-preset", "p4", "-rc:v", "vbr", "-cq:v", "20"],
        logger="bar",
    )

    # 정리
    for c in raw_clips:
        c.close()
    tts.close()
    final.close()

    size_mb = out_file.stat().st_size / 1024 / 1024
    step5.done(
        f"최종 출력: {out_file.relative_to(ROOT).as_posix()} ({size_mb:.1f}MB)"
    )


if __name__ == "__main__":
    # standalone 실행 시 로거 설정
    if not logger.handlers:
        _h = logging.StreamHandler(sys.stdout)
        _h.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(_h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    build()
