"""
ElevenLabs 한국어 음성 탐색 + 광고/나레이션 스타일 TTS 비교

실행:
    python scripts/compare_ko_voices.py

결과:
    output/tts/voice_compare_<voice_id>.mp3  (3개)
    output/tts/voice_compare_report.txt

참고: API 키에 voices_read 권한이 없으면 내장 후보 목록으로 동작.
      권한 추가: https://elevenlabs.io/app/settings/api-keys
"""

import os, sys, json, base64, time
from pathlib import Path
from dotenv import load_dotenv
import requests

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
TTS_DIR = ROOT / "output" / "tts"
TTS_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "xi-api-key": ELEVEN_KEY,
    "Content-Type": "application/json",
}

# ── 테스트 문장 ────────────────────────────────────────────────────────────
TEST_SCRIPT = (
    "소니 WF-1000XM5, 업계 최고의 노이즈 캔슬링으로 "
    "완벽한 몰입감을 선사합니다. "
    "지금 바로 최저가로 구매하세요!"
)

TTS_MODEL = "eleven_flash_v2_5"   # multilingual, 한국어 지원


# ── 내장 한국어 지원 후보 목록 ─────────────────────────────────────────────
# eleven_flash_v2_5 / eleven_multilingual_v2 에서 한국어 품질이 검증된 음성.
# premade=True → 모든 플랜에서 API 사용 가능
# premade=False → 유료 플랜(Starter+) 필요
BUILTIN_CANDIDATES = [
    {
        "voice_id": "cgSgspJ2msm6clMCkdW9",
        "name":     "Rachel",
        "gender":   "female",
        "style":    "conversational / narration",
        "note":     "현재 pipeline.py 기준 음성. 밝고 명확한 여성 목소리.",
        "premade":  True,
    },
    {
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "name":     "Adam",
        "gender":   "male",
        "style":    "narration / advertisement",
        "note":     "깊고 권위있는 남성 목소리. 광고 나레이션에 적합.",
        "premade":  True,
    },
    {
        "voice_id": "ErXwobaYiN019PkySvjV",
        "name":     "Antoni",
        "gender":   "male",
        "style":    "well-rounded / narration",
        "note":     "균형잡힌 남성 목소리. 범용 나레이션에 적합.",
        "premade":  True,
    },
    {
        "voice_id": "AZnzlk1XvdvUeBnXmlld",
        "name":     "Domi",
        "gender":   "female",
        "style":    "strong / advertisement",
        "note":     "강하고 자신감 있는 여성 목소리. 에너지 넘치는 광고에 적합.",
        "premade":  True,
    },
    {
        "voice_id": "TxGEqnHWrfWFTfGW9XjX",
        "name":     "Josh",
        "gender":   "male",
        "style":    "deep / narration",
        "note":     "깊은 남성 목소리. 진지한 나레이션에 적합.",
        "premade":  True,
    },
    # 유료 플랜 전용 (라이브러리 음성) — Starter+ 계정에서 활성화됨
    {
        "voice_id": "XB0fDUnXU5powFXDhCwa",
        "name":     "Charlotte",
        "gender":   "female",
        "style":    "narration / lifestyle",
        "note":     "따뜻하고 자연스러운 여성 목소리. 라이프스타일 광고에 적합. (Starter+ 필요)",
        "premade":  False,
    },
    {
        "voice_id": "onwK4e9ZLuTAKqWW03F9",
        "name":     "Daniel",
        "gender":   "male",
        "style":    "narration / news",
        "note":     "뉴스 아나운서 스타일의 남성 목소리. (Starter+ 필요)",
        "premade":  False,
    },
]


# ════════════════════════════════════════════════════════════════════════════
# 1. 내 계정 보유 음성 목록 (GET /v1/voices)
# ════════════════════════════════════════════════════════════════════════════

def fetch_my_voices() -> list[dict]:
    print("\n[1] GET /v1/voices — 내 계정 음성 목록")
    resp = requests.get(
        "https://api.elevenlabs.io/v1/voices",
        headers=HEADERS,
        timeout=15
    )
    if resp.status_code == 401:
        perm = resp.json().get("detail", {}).get("message", "")
        print(f"    ⚠ 권한 없음 (voices_read 필요): {perm}")
        print("      → 권한 추가: https://elevenlabs.io/app/settings/api-keys")
        return []
    resp.raise_for_status()
    voices = resp.json().get("voices", [])
    print(f"    총 {len(voices)}개 음성 조회 성공")
    return voices


# ════════════════════════════════════════════════════════════════════════════
# 2. Voice Library 한국어 검색 (GET /v1/shared-voices)
# ════════════════════════════════════════════════════════════════════════════

def fetch_shared_ko_voices() -> list[dict]:
    print("\n[2] GET /v1/shared-voices — 한국어(ko) 공개 음성 검색")
    resp = requests.get(
        "https://api.elevenlabs.io/v1/shared-voices",
        headers=HEADERS,
        params={"language": "ko", "page_size": 30, "sort": "usage_character_count_1y"},
        timeout=15,
    )
    if resp.status_code == 401:
        print("    ⚠ 권한 없음 (voices_read 필요) — 공개 라이브러리 스킵")
        return []
    resp.raise_for_status()
    data = resp.json()
    voices = data.get("voices", [])
    total  = data.get("total", len(voices))
    print(f"    한국어 공개 음성: {total}개 중 {len(voices)}개 반환")
    _print_shared_table(voices[:10])
    return voices


def _print_shared_table(voices: list[dict]):
    print(f"\n  {'이름':<22} {'ID':<26} {'use_case':<20} {'score'}")
    print(f"  {'─'*22} {'─'*26} {'─'*20} {'─'*6}")
    for v in voices:
        vid   = (v.get("voice_id") or v.get("id", ""))[:24]
        name  = (v.get("name") or "")[:20]
        use   = (v.get("use_case") or "-")[:18]
        clone = v.get("cloned_by_count", 0)
        print(f"  {name:<22} {vid:<26} {use:<20} {clone:>5}클론")


# ════════════════════════════════════════════════════════════════════════════
# 3. 비교 대상 3개 선정
# ════════════════════════════════════════════════════════════════════════════

AD_KEYWORDS = {"advertisement", "narration", "commercial", "promo", "ads", "광고", "나레이션"}
MAX_COMPARE = 3


def pick_candidates(my_voices: list[dict], shared: list[dict]) -> list[dict]:
    """
    우선순위:
      1) 내 계정 보유 음성 중 한국어/multilingual 태그된 것
      2) 공개 라이브러리 광고/나레이션 스코어 상위
      3) 내장 후보 목록으로 보충
    """
    print("\n[3] 비교 후보 선정")

    picked: list[dict] = []
    seen_ids: set[str] = set()

    # ── 내 계정 음성 ──
    for v in my_voices:
        lang  = (v.get("fine_tuning", {}).get("language") or "").lower()
        lbl   = " ".join(str(x) for x in (v.get("labels") or {}).values()).lower()
        if "ko" in lang or "korean" in lbl or "multilingual" in lbl:
            picked.append({"voice_id": v["voice_id"], "name": v["name"],
                           "source": "my_voices"})
            seen_ids.add(v["voice_id"])

    # ── 공개 라이브러리 (광고/나레이션 키워드 우선) ──
    def ad_score(v):
        s = 0
        if any(kw in (v.get("use_case") or "").lower() for kw in AD_KEYWORDS):
            s += 3
        for lbl in (v.get("labels") or {}).values():
            if any(kw in str(lbl).lower() for kw in AD_KEYWORDS):
                s += 2
        s += min(v.get("cloned_by_count", 0) // 200, 2)
        return s

    for v in sorted(shared, key=ad_score, reverse=True):
        if len(picked) >= MAX_COMPARE:
            break
        vid = v.get("voice_id") or v.get("id", "")
        if vid and vid not in seen_ids:
            picked.append({"voice_id": vid, "name": v.get("name", vid),
                           "use_case": v.get("use_case", "-"), "source": "library"})
            seen_ids.add(vid)

    # ── 내장 후보로 보충 (premade 우선, 유료 음성은 자리 남을 때만) ──
    for b in sorted(BUILTIN_CANDIDATES, key=lambda x: (not x.get("premade", True))):
        if len(picked) >= MAX_COMPARE:
            break
        if b["voice_id"] not in seen_ids:
            picked.append({**b, "source": "builtin"})
            seen_ids.add(b["voice_id"])

    for c in picked:
        src   = c.get("source", "")
        style = c.get("style", c.get("use_case", "-"))
        note  = c.get("note", "")
        print(f"    ✓ [{src:8}] {c['name']:<20} {c['voice_id']}  {style}")
        if note:
            print(f"               {note}")

    return picked[:MAX_COMPARE]


# ════════════════════════════════════════════════════════════════════════════
# 4. TTS 생성
# ════════════════════════════════════════════════════════════════════════════

def generate_tts(voice_id: str, out_mp3: Path) -> dict:
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech"
        f"/{voice_id}/with-timestamps"
    )
    resp = requests.post(
        url,
        headers=HEADERS,
        json={
            "text": TEST_SCRIPT,
            "model_id": TTS_MODEL,
            "language_code": "ko",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.80},
        },
        timeout=60,
    )
    if not resp.ok:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    audio_bytes = base64.b64decode(data["audio_base64"])
    out_mp3.write_bytes(audio_bytes)

    ends     = data["alignment"].get("character_end_times_seconds", [])
    duration = ends[-1] if ends else 0.0
    size_kb  = len(audio_bytes) / 1024
    return {"duration": duration, "size_kb": size_kb, "path": str(out_mp3)}


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════

def main():
    if not ELEVEN_KEY:
        print("[오류] .env에 ELEVENLABS_API_KEY가 없습니다.")
        return

    t0 = time.perf_counter()

    print("=" * 62)
    print("ElevenLabs 한국어 음성 탐색 + TTS 비교")
    print(f'테스트 문장: "{TEST_SCRIPT}"')
    print(f"모델: {TTS_MODEL}  language_code: ko")
    print("=" * 62)

    my_voices = fetch_my_voices()
    shared    = fetch_shared_ko_voices()
    candidates = pick_candidates(my_voices, shared)

    print(f"\n[4] TTS 생성 — {len(candidates)}개 음성")
    results = []
    for c in candidates:
        vid  = c["voice_id"]
        name = c["name"]
        slug = vid[:12].replace("/", "_")
        out_mp3 = TTS_DIR / f"voice_compare_{slug}.mp3"

        print(f"\n    {name} [{vid}]")
        result = generate_tts(vid, out_mp3)
        result.update({"name": name, "voice_id": vid,
                        "style": c.get("style", c.get("use_case", "-")),
                        "note":  c.get("note", "")})
        results.append(result)

        if "error" in result:
            print(f"    ✗ 실패: {result['error']}")
        else:
            print(f"    ✓ {result['duration']:.1f}초  {result['size_kb']:.0f}KB"
                  f"  → {out_mp3.name}")

    # ── 최종 리포트 ──────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0

    sep = "=" * 62
    report_lines = [
        sep,
        "ElevenLabs 한국어 음성 비교 리포트",
        f'테스트 문장: "{TEST_SCRIPT}"',
        f"모델: {TTS_MODEL}  language_code: ko",
        sep,
        f"  {'음성명':<22} {'ID':<26} {'길이':>5}  {'크기':>6}  파일",
        f"  {'─'*22} {'─'*26} {'─'*5}  {'─'*6}  {'─'*30}",
    ]
    for r in results:
        if "error" in r:
            report_lines.append(f"  ✗ {r['name']:<22} {r['voice_id']:<26}  오류: {r['error']}")
        else:
            report_lines.append(
                f"  ✓ {r['name']:<22} {r['voice_id']:<26}"
                f"  {r['duration']:>4.1f}초  {r['size_kb']:>5.0f}KB"
                f"  {Path(r['path']).name}"
            )
        if r.get("note"):
            report_lines.append(f"    → {r['note']}")
    report_lines += [
        "",
        f"총 소요시간: {elapsed:.1f}초",
        "",
        "비교 방법:",
        "  - 각 mp3 파일을 재생하여 발음 명확도, 자연스러움, 광고 적합성 평가",
        "  - 선택 후 pipeline.py의 VOICE_ID를 해당 voice_id로 교체",
        sep,
    ]

    report_path = TTS_DIR / "voice_compare_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print("\n")
    print("\n".join(report_lines))
    print(f"\n리포트 저장: {report_path}")

    # voices_read 권한 안내
    if not my_voices and not shared:
        print("\n" + "─" * 62)
        print("💡 API 키에 voices_read 권한을 추가하면 내 보유 음성 및")
        print("   Voice Library 전체 목록을 조회할 수 있습니다.")
        print("   → https://elevenlabs.io/app/settings/api-keys")
        print("─" * 62)


if __name__ == "__main__":
    main()
