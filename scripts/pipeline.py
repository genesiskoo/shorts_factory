"""
풀 파이프라인: 상품 정보 → 대본 → TTS + SRT → 숏폼 mp4

실행:
    python scripts/pipeline.py
"""

import os, sys, re, base64, json, logging, time
from pathlib import Path
from dotenv import load_dotenv

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ["FFMPEG_BINARY"] = (
    r"C:\Users\FORYOUCOM\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

GEMINI_KEY    = os.getenv("GEMINI_API_KEY")
ELEVEN_KEY    = os.getenv("ELEVENLABS_API_KEY", "").strip()
OUTPUT_DIR    = ROOT / "output"
TTS_DIR       = OUTPUT_DIR / "tts"
BGM_FILE      = ROOT / "kornevmusic-epic-478847.mp3"
TTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 로깅 설정 ─────────────────────────────────────────────────────────────────
TOTAL_STEPS = 5

logger = logging.getLogger("pipeline")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


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


_costs: dict[str, float] = {}


def add_cost(api: str, amount: float) -> None:
    _costs[api] = _costs.get(api, 0.0) + amount


# ── 상품 설정 ─────────────────────────────────────────────────────────────────
PRODUCT = {
    "name":  "Sony WF-1000XM5 무선 이어폰",
    "price": "$279.99",
    "clips": [
        OUTPUT_DIR / "earbuds_zoom.mp4",
        OUTPUT_DIR / "earbuds_float.mp4",
        OUTPUT_DIR / "earbuds_reveal.mp4",
    ],
    "channel": "@해외직구연구소",
    "cta":     "지금 최저가로 구매하기 →",
}

VOICE_ID  = "XrExE9yKIg1WjnnlVkGX"   # Matilda (eleven_v3, KO narration)
TTS_MODEL = "eleven_v3"


# ════════════════════════════════════════════════════════════════════════════
# Step 1: Gemini 대본 생성
# ════════════════════════════════════════════════════════════════════════════

def generate_script(product_name: str, price: str) -> str:
    from google import genai

    prompt = (
        f"상품명: {product_name}\n"
        f"가격: {price}\n\n"
        "해외직구 숏폼 광고 대본을 작성해줘. "
        "조건: 한국어, 15~20초 분량(최대 100자 이내), 상품 특징 3가지 포함, 마지막에 CTA 문구. "
        "대본 텍스트만 출력. 번호나 설명 없이 말할 내용만."
    )

    step = StepTimer(1, "대본 생성 중... (Gemini API)")

    client = genai.Client(api_key=GEMINI_KEY)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    script = resp.text.strip()

    # 비용 추정: Gemini 2.5 Flash — input $0.15/1M tokens, output $0.60/1M tokens (1토큰≈3자)
    input_tokens  = len(prompt) / 3
    output_tokens = len(script) / 3
    cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000
    add_cost("Gemini", cost)

    sentence_count = len([s for s in re.split(r"[.!?。]", script) if s.strip()])
    step.done(f"대본 생성 완료 — {len(script)}자, {sentence_count}문장")
    return script


# ════════════════════════════════════════════════════════════════════════════
# Step 2: ElevenLabs TTS + character timestamps
# ════════════════════════════════════════════════════════════════════════════

def generate_tts(script: str, out_mp3: Path) -> dict:
    """TTS 호출 → mp3 저장 + alignment dict 반환"""
    import requests

    step = StepTimer(2, "TTS 생성 중... (ElevenLabs API)")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/with-timestamps"
    resp = requests.post(
        url,
        headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"},
        json={
            "text": script,
            "model_id": TTS_MODEL,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.80},
        },
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"ElevenLabs HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    audio_bytes = base64.b64decode(data["audio_base64"])
    out_mp3.write_bytes(audio_bytes)

    alignment = data["alignment"]
    ends = alignment.get("character_end_times_seconds", [])
    tts_duration = ends[-1] if ends else 0.0

    # 비용 추정: ElevenLabs Flash v2.5 — $0.30 / 1,000자
    cost = len(script) * 0.30 / 1000
    add_cost("ElevenLabs", cost)

    step.done(
        f"TTS 완료 — {tts_duration:.1f}초, "
        f"{out_mp3.relative_to(ROOT).as_posix()}"
    )
    return alignment


# ════════════════════════════════════════════════════════════════════════════
# Step 3: character timestamps → word-level SRT
# ════════════════════════════════════════════════════════════════════════════

def _ts(sec: float) -> str:
    """초 → SRT 타임코드 HH:MM:SS,mmm"""
    ms  = int(round(sec * 1000))
    h   = ms // 3_600_000;  ms %= 3_600_000
    m   = ms // 60_000;     ms %= 60_000
    s   = ms // 1_000;      ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def alignment_to_srt(alignment: dict, out_srt: Path,
                     max_chars: int = 20) -> list[dict]:
    """
    문자 단위 타임스탬프 → 어절(공백 기준) 그룹 → 자막 라인 묶기
    max_chars: 한 자막 라인 최대 글자 수 (초과 시 다음 줄)
    """
    step = StepTimer(3, "SRT 생성 중...")

    chars  = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends   = alignment["character_end_times_seconds"]

    # ── 어절 분리 (공백/마침표/쉼표 경계) ──
    words: list[dict] = []
    buf_chars, buf_start, buf_end = [], None, None

    def flush():
        nonlocal buf_chars, buf_start, buf_end
        text = "".join(buf_chars).strip()
        if text and buf_start is not None:
            words.append({"text": text, "start": buf_start, "end": buf_end})
        buf_chars, buf_start, buf_end = [], None, None

    for ch, s, e in zip(chars, starts, ends):
        if ch in (" ", "\n"):
            flush()
        else:
            if buf_start is None:
                buf_start = s
            buf_end = e
            buf_chars.append(ch)
    flush()

    # ── 자막 라인 묶기 (max_chars 기준) ──
    subs: list[dict] = []
    line_buf: list[dict] = []
    line_len = 0

    def flush_line():
        nonlocal line_buf, line_len
        if line_buf:
            text  = " ".join(w["text"] for w in line_buf)
            start = line_buf[0]["start"]
            end   = line_buf[-1]["end"]
            subs.append({"text": text, "start": start, "end": end})
        line_buf, line_len = [], 0

    for w in words:
        wlen = len(w["text"])
        if line_len + wlen > max_chars and line_buf:
            flush_line()
        line_buf.append(w)
        line_len += wlen + 1
    flush_line()

    # ── SRT 파일 작성 ──
    lines = []
    for i, sub in enumerate(subs, 1):
        lines.append(str(i))
        lines.append(f"{_ts(sub['start'])} --> {_ts(sub['end'])}")
        lines.append(sub["text"])
        lines.append("")
    out_srt.write_text("\n".join(lines), encoding="utf-8")

    step.done(
        f"SRT 완료 — {len(subs)}개 자막, "
        f"{out_srt.relative_to(ROOT).as_posix()}"
    )
    return subs


# ════════════════════════════════════════════════════════════════════════════
# Step 4–5: build_shorts.py 연동
# ════════════════════════════════════════════════════════════════════════════

def build_video(tts_mp3: Path, srt_path: Path, out_mp4: Path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_shorts

    build_shorts.build({
        "clips":   PRODUCT["clips"],
        "tts":     tts_mp3,
        "srt":     srt_path,
        "output":  out_mp4,
        "product": PRODUCT["name"],
        "price":   PRODUCT["price"],
        "cta":     PRODUCT["cta"],
        "channel": PRODUCT["channel"],
        "bgm":     BGM_FILE,
    })


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

def main():
    slug = "sony_xm5"
    tts_mp3 = TTS_DIR / f"{slug}.mp3"
    tts_srt = TTS_DIR / f"{slug}.srt"
    out_mp4 = OUTPUT_DIR / f"shorts_{slug}.mp4"

    _costs.clear()
    pipeline_start = time.perf_counter()

    logger.info("=" * 60)
    logger.info("풀 파이프라인 테스트")
    logger.info(f"상품: {PRODUCT['name']}")
    logger.info("=" * 60)

    script    = generate_script(PRODUCT["name"], PRODUCT["price"])
    alignment = generate_tts(script, tts_mp3)
    alignment_to_srt(alignment, tts_srt, max_chars=18)
    build_video(tts_mp3, tts_srt, out_mp4)

    total_elapsed = time.perf_counter() - pipeline_start
    size_mb = out_mp4.stat().st_size / 1024 / 1024

    logger.info("")
    logger.info(f"총 소요시간: {total_elapsed:.0f}초")
    if _costs:
        cost_parts = " + ".join(f"{k} ${v:.3f}" for k, v in _costs.items())
        total_cost = sum(_costs.values())
        logger.info(f"API 비용: {cost_parts} = ${total_cost:.3f}")
    logger.info(f"출력: {out_mp4.relative_to(ROOT).as_posix()} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
