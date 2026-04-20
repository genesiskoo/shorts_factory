"""services/typecast_tts.py 단위 검증.

httpx.Client를 monkeypatch해 Typecast 외부 호출 없이 에러 매핑/파일 저장/
SRT 추정을 검증한다.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_typecast_wrapper.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401

# API 키 세팅 (없으면 __get_api_key가 실패)
os.environ.setdefault("TYPECAST_API_KEY", "test_key_fake")

from services import typecast_tts  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Fake httpx response / client
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, content: bytes = b"", text: str = ""):
        self.status_code = status
        self.content = content
        self.text = text

    def json(self):  # pragma: no cover - 미사용
        import json as _j
        return _j.loads(self.text or "null")


class FakeClient:
    """단발성 응답 1개를 반환하는 스텁."""

    def __init__(self, response: FakeResponse):
        self._response = response
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._response

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._response


def install_fake_client(resp: FakeResponse) -> FakeClient:
    fake = FakeClient(resp)

    class CM:
        def __enter__(self_inner):
            return fake

        def __exit__(self_inner, *exc):
            return False

    # typecast_tts는 `with httpx.Client() as client:` 패턴 사용
    def factory():
        return fake

    typecast_tts.httpx.Client = factory  # type: ignore[attr-defined]
    return fake


# ---------------------------------------------------------------------------
# Test 1: _estimate_srt — 한국어 문장
# ---------------------------------------------------------------------------
print("\n[test 1] _estimate_srt 기본 동작")

text = "이것은 한국어 테스트 문장 입니다. 감정 전달도 자연스럽게 되어야 합니다."
srt = typecast_tts._estimate_srt(text, duration=10.0)

check("SRT 비어있지 않음", len(srt) > 0)
check("숫자 인덱스 존재", "1\n" in srt)
check("타임스탬프 포맷 (HH:MM:SS,mmm)", "00:00:00,000" in srt)
check("줄 수 최소 3 이상", srt.count("\n\n") >= 2, f"chunks={srt.count(chr(10)+chr(10))}")

# 마지막 타임스탬프가 duration을 초과하지 않는지
import re
all_ts = re.findall(r"(\d{2}:\d{2}:\d{2},\d{3})", srt)
last_ts = all_ts[-1] if all_ts else "00:00:00,000"
h, m, s_ms = last_ts.split(":")
sec_part, ms_part = s_ms.split(",")
last_sec = int(h) * 3600 + int(m) * 60 + int(sec_part) + int(ms_part) / 1000
check("마지막 타임스탬프 <= duration", last_sec <= 10.01, f"last={last_sec}")


# ---------------------------------------------------------------------------
# Test 2: _estimate_srt — 빈 문자열
# ---------------------------------------------------------------------------
print("\n[test 2] 빈 문자열 SRT → 빈 문자열")
check("빈 text → ''", typecast_tts._estimate_srt("", 5.0) == "")
check("duration 0 → ''", typecast_tts._estimate_srt("안녕", 0) == "")


# ---------------------------------------------------------------------------
# Test 3: _build_payload — Smart Emotion + previous_text
# ---------------------------------------------------------------------------
print("\n[test 3] _build_payload smart emotion")

payload = typecast_tts._build_payload(
    text="안녕하세요",
    options={
        "voice_id": "tc_abc",
        "model": "ssfm-v30",
        "emotion_type": "smart",
        "audio_tempo": 1.1,
        "audio_format": "mp3",
    },
    ctx={"previous_text": "따뜻한 위로"},
)
check("voice_id 포함", payload.get("voice_id") == "tc_abc")
check("prompt.emotion_type=smart", payload.get("prompt", {}).get("emotion_type") == "smart")
check(
    "prompt.previous_text 반영",
    payload.get("prompt", {}).get("previous_text") == "따뜻한 위로",
)
check("output.audio_tempo", payload.get("output", {}).get("audio_tempo") == 1.1)
check("output.audio_format=mp3", payload.get("output", {}).get("audio_format") == "mp3")


# ---------------------------------------------------------------------------
# Test 4: _build_payload — preset emotion
# ---------------------------------------------------------------------------
print("\n[test 4] _build_payload preset emotion")

payload = typecast_tts._build_payload(
    text="안녕",
    options={
        "voice_id": "tc_abc",
        "emotion_type": "preset",
        "emotion_preset": "happy",
        "emotion_intensity": 1.5,
    },
)
pr = payload.get("prompt", {})
check("prompt.emotion_type=preset", pr.get("emotion_type") == "preset")
check("prompt.emotion_preset=happy", pr.get("emotion_preset") == "happy")
check("prompt.emotion_intensity=1.5", pr.get("emotion_intensity") == 1.5)


# ---------------------------------------------------------------------------
# Test 5: voice_id 없으면 ValueError
# ---------------------------------------------------------------------------
print("\n[test 5] voice_id 누락 → ValueError")
try:
    typecast_tts._build_payload("안녕", {})
    check("ValueError raised", False, "예외 미발생")
except ValueError:
    check("ValueError raised", True)


# ---------------------------------------------------------------------------
# Test 6: run — 200 정상 응답 → mp3 + srt 저장
# ---------------------------------------------------------------------------
print("\n[test 6] run() 정상 응답")

with tempfile.TemporaryDirectory() as tmp:
    # 320kbps ≈ 40000 bytes/sec. 2초 분량 흉내.
    fake_mp3 = b"\x00" * 80000
    install_fake_client(FakeResponse(200, content=fake_mp3))

    scripts = {
        "scripts": [
            {
                "variant_id": "v1_informative",
                "script_text": "이것은 한국어 대본 예시 문장 입니다.",
            }
        ]
    }
    result = typecast_tts.run(
        scripts,
        tmp,
        options={"voice_id": "tc_x", "audio_format": "mp3"},
    )
    vres = result.get("v1_informative", {})
    check("result에 mp3 경로 있음", bool(vres.get("mp3")), f"res={vres}")
    mp3_path = Path(vres.get("mp3") or "")
    srt_path = Path(vres.get("srt") or "")
    check("mp3 파일 생성됨", mp3_path.exists())
    check("srt 파일 생성됨", srt_path.exists())
    check("mp3 바이트 일치", mp3_path.read_bytes() == fake_mp3)
    srt_content = srt_path.read_text(encoding="utf-8")
    check("srt 내용 non-empty", len(srt_content) > 0)


# ---------------------------------------------------------------------------
# Test 7: run — 기존 파일 있으면 skip (checkpoint)
# ---------------------------------------------------------------------------
print("\n[test 7] 기존 파일 있으면 skip")

with tempfile.TemporaryDirectory() as tmp:
    audio_dir = Path(tmp) / "audio"
    audio_dir.mkdir(parents=True)
    pre_mp3 = audio_dir / "v1_informative.mp3"
    pre_srt = audio_dir / "v1_informative.srt"
    pre_mp3.write_bytes(b"EXISTING")
    pre_srt.write_text("existing srt", encoding="utf-8")

    # 호출되면 fail을 유도하는 에러 응답 세팅
    fake = install_fake_client(FakeResponse(500, text="should not be called"))

    scripts = {
        "scripts": [
            {"variant_id": "v1_informative", "script_text": "테스트 문장"}
        ]
    }
    result = typecast_tts.run(
        scripts, tmp, options={"voice_id": "tc_x", "audio_format": "mp3"}
    )
    check("skip: 외부 호출 0회", len(fake.calls) == 0, f"calls={len(fake.calls)}")
    check("기존 mp3 보존", pre_mp3.read_bytes() == b"EXISTING")


# ---------------------------------------------------------------------------
# Test 8: run — 401 → TypecastAuthError를 잡아 result.error로
# ---------------------------------------------------------------------------
print("\n[test 8] 401 응답 → result[vid].error")

with tempfile.TemporaryDirectory() as tmp:
    install_fake_client(FakeResponse(401, text="unauthorized"))
    scripts = {
        "scripts": [{"variant_id": "v1_informative", "script_text": "테스트"}]
    }
    result = typecast_tts.run(
        scripts, tmp, options={"voice_id": "tc_x", "audio_format": "mp3"}
    )
    vres = result.get("v1_informative", {})
    check("mp3 None", vres.get("mp3") is None)
    check("error 메시지 포함 '401'", "401" in (vres.get("error") or ""))


# ---------------------------------------------------------------------------
# Test 9: run — 402 / 429 매핑
# ---------------------------------------------------------------------------
print("\n[test 9] 402 크레딧/429 쿼터 매핑")

for status, label in [(402, "402"), (429, "429")]:
    with tempfile.TemporaryDirectory() as tmp:
        install_fake_client(FakeResponse(status, text=f"status {status}"))
        scripts = {
            "scripts": [{"variant_id": "v1_informative", "script_text": "테스트"}]
        }
        result = typecast_tts.run(
            scripts, tmp, options={"voice_id": "tc_x", "audio_format": "mp3"}
        )
        err = result.get("v1_informative", {}).get("error") or ""
        check(f"{status} → error에 '{label}' 포함", label in err, f"err={err}")


# ---------------------------------------------------------------------------
# Test 10: preview() — mp3 media type
# ---------------------------------------------------------------------------
print("\n[test 10] preview() media type")

install_fake_client(FakeResponse(200, content=b"\x00" * 1000))
audio, media = typecast_tts.preview(
    "안녕하세요 미리듣기",
    options={"voice_id": "tc_x", "audio_format": "mp3"},
)
check("preview bytes", len(audio) == 1000)
check("media=audio/mpeg (mp3)", media == "audio/mpeg")

install_fake_client(FakeResponse(200, content=b"\x00" * 1000))
audio, media = typecast_tts.preview(
    "안녕",
    options={"voice_id": "tc_x", "audio_format": "wav"},
)
check("media=audio/wav (wav)", media == "audio/wav")


# ---------------------------------------------------------------------------
# Test 11: list_voices — 200 응답 전달
# ---------------------------------------------------------------------------
print("\n[test 11] list_voices 정상")

import json as _json
sample_voices = [
    {
        "voice_id": "tc_1",
        "voice_name": "Alice",
        "gender": "female",
        "age": "young_adult",
        "use_cases": ["narration"],
        "models": [{"version": "ssfm-v30", "emotions": ["normal", "happy"]}],
    }
]
install_fake_client(FakeResponse(200, content=_json.dumps(sample_voices).encode()))
# FakeResponse.json이 self.text를 쓰는데 content만 채웠음 → text로도 세팅
fake = install_fake_client(
    FakeResponse(200, content=b"", text=_json.dumps(sample_voices))
)
# FakeResponse.json() 사용되므로 text 기반이어야 함
voices = typecast_tts.list_voices("ssfm-v30")
check("voices 길이=1", len(voices) == 1)
check("voice_id 일치", voices[0].get("voice_id") == "tc_1")


# ---------------------------------------------------------------------------
# 총평
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"TOTAL: {passed}/{total} PASS")
if passed != total:
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    sys.exit(1)
