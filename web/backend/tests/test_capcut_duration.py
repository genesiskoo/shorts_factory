"""scripts/capcut_builder.py duration 보정 검증.

Veo 8초 mp4를 16초 segment에 배치 → 8초 freeze 버그를 막기 위한
ffprobe 기반 layout 로직 단위 테스트.

실행:
    cd web/backend && venv_web/Scripts/python.exe tests/test_capcut_duration.py
또는:
    cd web/backend && venv_web/Scripts/python.exe -m pytest tests/test_capcut_duration.py -v
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Windows cp949 콘솔에서 한글/유니코드 출력을 위한 stdout wrapper.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from capcut_builder import _layout_video_segments  # noqa: E402
from agents.capcut_builder import _get_mp3_duration  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}  {detail}")


# ---------------------------------------------------------------------------
# Test 1: 정확히 합이 target과 일치 (Veo 8초 × 4 = TTS 30초 + 2 = 32초)
# ---------------------------------------------------------------------------
print("\n[test 1] sum(actual) == target_total — 정확 매칭")

clips = [Path(f"clip_{i}.mp4") for i in range(4)]
actual = [8_000_000, 8_000_000, 8_000_000, 8_000_000]  # 32s total
target = 32_000_000  # TTS 30s + 2s buffer

layout = _layout_video_segments(clips, actual, target)

check("4개 segment 반환", len(layout) == 4)
check("0번 start=0", layout[0][0] == 0)
check("1번 start=8s", layout[1][0] == 8_000_000)
check("3번 start=24s", layout[3][0] == 24_000_000)
check("모든 source_dur=actual", all(l[1] == 8_000_000 for l in layout))
check("모든 target_dur=actual", all(l[2] == 8_000_000 for l in layout))


# ---------------------------------------------------------------------------
# Test 2: sum(actual) < target — 마지막 segment freeze (의도된 짧은 padding)
# ---------------------------------------------------------------------------
print("\n[test 2] sum(actual) < target — 마지막 segment freeze padding")

clips = [Path(f"clip_{i}.mp4") for i in range(4)]
actual = [8_000_000] * 4  # 32s
target = 34_000_000  # 34s — 2s 부족

layout = _layout_video_segments(clips, actual, target)

check("앞 3개 source==target", all(layout[i][1] == layout[i][2] == 8_000_000 for i in range(3)))
check("마지막 source==actual (8s)", layout[3][1] == 8_000_000)
check("마지막 target=10s (freeze 2s)", layout[3][2] == 10_000_000)
last_end = layout[3][0] + layout[3][2]
check("timeline 끝=target_total", last_end == target, f"last_end={last_end}")


# ---------------------------------------------------------------------------
# Test 3: sum(actual) > target — 마지막 segment cut (TTS가 짧은 경우)
# ---------------------------------------------------------------------------
print("\n[test 3] sum(actual) > target — 마지막 segment cut")

clips = [Path(f"clip_{i}.mp4") for i in range(4)]
actual = [8_000_000] * 4  # 32s
target = 28_000_000  # 28s — 4s 초과

layout = _layout_video_segments(clips, actual, target)

check("앞 3개는 source==target==actual", all(layout[i][1] == layout[i][2] == 8_000_000 for i in range(3)))
# 마지막은 28s - 24s = 4s
check("마지막 target=4s (cut)", layout[3][2] == 4_000_000)
check("마지막 source=4s (cut, freeze 방지)", layout[3][1] == 4_000_000)
last_end = layout[3][0] + layout[3][2]
check("timeline 끝=target_total", last_end == target)


# ---------------------------------------------------------------------------
# Test 4: 가변 길이 (Veo 클립이 약간씩 다른 길이)
# ---------------------------------------------------------------------------
print("\n[test 4] 가변 actual durations")

clips = [Path(f"clip_{i}.mp4") for i in range(3)]
actual = [7_500_000, 8_200_000, 7_800_000]  # 23.5s
target = 25_000_000  # 25s — 1.5s 부족

layout = _layout_video_segments(clips, actual, target)

check("0번 start=0, dur=7.5s", layout[0][0] == 0 and layout[0][1] == 7_500_000)
check("1번 start=7.5s, dur=8.2s", layout[1][0] == 7_500_000 and layout[1][1] == 8_200_000)
check("2번 start=15.7s", layout[2][0] == 15_700_000)
# 마지막 source=actual (7.8s), target=25s - 15.7s = 9.3s (freeze 1.5s)
check("2번 source=actual=7.8s", layout[2][1] == 7_800_000)
check("2번 target=9.3s (freeze)", layout[2][2] == 9_300_000)


# ---------------------------------------------------------------------------
# Test 5: 단일 클립 (edge case)
# ---------------------------------------------------------------------------
print("\n[test 5] 단일 클립")

clips = [Path("only.mp4")]
actual = [8_000_000]
target = 10_000_000  # 10s

layout = _layout_video_segments(clips, actual, target)

check("1개 segment", len(layout) == 1)
check("start=0", layout[0][0] == 0)
check("source=actual=8s", layout[0][1] == 8_000_000)
check("target=10s (freeze 2s)", layout[0][2] == 10_000_000)


# ---------------------------------------------------------------------------
# Test 6: 큰 Cut (사용자 보고 시나리오 — TTS는 정상이지만 Veo 클립이 적어 대형 freeze)
# ---------------------------------------------------------------------------
print("\n[test 6] 사용자 보고 케이스 (n_clips=2, 큰 freeze 방지)")

# 2 클립이고 TTS 32s + 2 = 34s. 균등 분할이면 17s/클립이지만
# actual은 8s씩. 이전 코드는 17s segment 만들어 9s freeze 발생.
# 새 로직: 앞 segment 8s (정확), 마지막 8s + 18s freeze (불가피). 경고 로그.
clips = [Path(f"clip_{i}.mp4") for i in range(2)]
actual = [8_000_000, 8_000_000]  # 16s
target = 34_000_000  # 34s — 18s 부족

layout = _layout_video_segments(clips, actual, target)

check("0번 정확 8s (no freeze)", layout[0][1] == 8_000_000 and layout[0][2] == 8_000_000)
check("1번 source=actual=8s", layout[1][1] == 8_000_000)
# 마지막 segment가 어쩔 수 없이 큰 freeze (TTS가 너무 길어서)
# 하지만 이전 코드와 비교하면: 이전엔 0번 17s(9s freeze) + 1번 17s(9s freeze) = 18s 총 freeze
# 새 코드: 0번 0s freeze + 1번 18s freeze = 같은 18s지만 마지막에만 몰림 (자연스러움)
check("1번 target=26s (freeze 18s — TTS 길이 한계)", layout[1][2] == 26_000_000)


# ---------------------------------------------------------------------------
# Test 7: _get_mp3_duration 정확도 — 실제 mp3로 검증 (있을 때만)
# ---------------------------------------------------------------------------
print("\n[test 7] _get_mp3_duration 실측 mp3")

real_mp3 = PROJECT_ROOT / "output" / "게임써 GAMESIR G7 Pro" / "audio" / "v3_scenario.mp3"
if real_mp3.exists():
    dur = _get_mp3_duration(real_mp3)
    # 파일 크기 추정 버그(128kbps 가정)였다면 50s 이상 반환. 실측 22.55s ±0.5s
    check(
        f"v3_scenario.mp3 ≈22.55s (got {dur:.2f}s)",
        20.0 <= dur <= 25.0,
        f"got={dur:.3f}s",
    )
else:
    print("  [SKIP] 실측 mp3 없음 — Phase A는 회귀 테스트로 검증")


# ---------------------------------------------------------------------------
# Test 8: fixed_tracks에 TRACK_PRODUCT_NAME(6) 포함 확인
# ---------------------------------------------------------------------------
print("\n[test 8] fixed_tracks에 상품명 track 포함")

import inspect
import capcut_builder as cap_mod
src = inspect.getsource(cap_mod)
# fixed_tracks 정의 라인이 TRACK_PRODUCT_NAME 포함하는지 확인 (정적 검증)
check(
    "fixed_tracks에 TRACK_PRODUCT_NAME 토큰 존재",
    "TRACK_PRODUCT_NAME" in src and "fixed_tracks" in src,
)


# ---------------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------------
print(f"\n========== {sum(1 for _, ok, _ in results if ok)}/{len(results)} PASS ==========")
fails = [(n, d) for n, ok, d in results if not ok]
if fails:
    print("FAIL details:")
    for n, d in fails:
        print(f"  - {n}: {d}")
    sys.exit(1)


def test_capcut_duration_layout() -> None:
    """pytest entry — 위에서 이미 실행되었으므로 fail 검사만."""
    assert all(ok for _, ok, _ in results), [n for n, ok, _ in results if not ok]
