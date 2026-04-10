# capcut_builder.py 작업 지시서 — shorts_factory Day 2

> Claude Code 실행용. 2026.04.09

---

## 목표

CapCut 템플릿 draft_content.json을 로드하여 동적 데이터(영상 클립, TTS, SRT 자막, 상품명)로 치환한 뒤, CapCut 프로젝트 폴더로 저장하는 `capcut_builder.py` 모듈을 구현한다.

---

## 사전 조건

### 라이브러리

- **1차 시도: pyCapCut** (`pip install pyCapCut`)
  - GuanYixuan/pyCapCut — CapCut 글로벌 전용 포크
  - ScriptFile.load_template()으로 draft_content.json 로드·치환·저장 가능
  - add_segment() + uuid.uuid4().hex로 material_id 자동 부여, 세그먼트 동적 생성 지원
- **dumps() 시 canvas_config 덮어쓰기 이슈 있음** — 저장 직전에 원본 canvas_config를 다시 패치해야 함
- **pyCapCut이 안 되면** → 라이브러리 쓰지 말고 직접 JSON dict 조작으로 전환 (uuid4로 material_id 생성, 나머지는 dict 키 접근)

### 템플릿 위치

```
templates/capcut_template/draft_content.json    ← 앤커 사운드코어 기존 납품본
```

이 파일은 프로젝트 루트의 templates/ 폴더에 복사해놓을 것. 아직 없으면 CapCut 프로젝트 폴더에서 복사:
```
C:\Users\FORYOUCOM\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\엔커사운드코어\draft_content.json
```

### CapCut 프로젝트 출력 경로

```python
CAPCUT_PROJECTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
```

builder가 여기에 새 폴더를 만들고 draft_content.json + 부속 파일을 저장하면 CapCut 데스크톱에서 프로젝트로 인식된다.

### 프로젝트 폴더에 필요한 파일

새 프로젝트 폴더 생성 시 템플릿 폴더에서 아래 파일을 복사:
- `draft_content.json` — 치환 후 저장 (메인)
- `draft_meta_info.json` — 프로젝트명만 변경
- `draft_settings` — 그대로 복사
- `draft_virtual_store.json` — 그대로 복사
- `timeline_layout.json` — 그대로 복사
- `draft_biz_config.json` — 그대로 복사
- `draft_agency_config.json` — 그대로 복사

나머지 파일/폴더(*.bak, *.tmp, draft_cover.jpg, subdraft/, Timelines/, Resources/ 등)는 불필요.

---

## 템플릿 구조 (치환 포인트)

참고 문서: `capcut_json_분석.md` (프로젝트 루트에 있음)

### 트랙 매핑

| Track | 역할 | 치환 여부 |
|-------|------|-----------|
| 0 | 메인 영상 클립 (현재 2 segments) | **치환** — I2V 클립 3~4개로 교체 |
| 1~3 | 배너/CTA 배경 shapes | 고정 (duration만 업데이트) |
| 4 | 네이버 로고 PNG | 고정 (duration만 업데이트) |
| 5 | 비행기 이모지 스티커 | 고정 (duration만 업데이트) |
| 6 | 상품명 텍스트 | **치환** — product_name |
| 7 | CTA 텍스트 | 고정 (보통 "구매링크는 프로필 링크 참고") |
| 8 | "해외직구" 텍스트 | 고정 (duration만 업데이트) |
| 9 | SRT 자막 (현재 6 segments) | **치환** — SRT entries 기반 동적 생성 |
| 10 | TTS 오디오 | **치환** — 경로 + duration |
| 11 | BGM 오디오 | **치환** — 경로 + duration |

### 시간 단위

CapCut JSON의 모든 시간값은 **마이크로초(μs)**.
- 1초 = 1,000,000
- 변환: `seconds * 1_000_000`

---

## 구현 스펙

### 파일 위치

```
shorts_factory/
├── scripts/
│   ├── capcut_builder.py        ← 신규 생성
│   ├── pipeline.py              ← 기존
│   └── build_shorts.py          ← 기존 (MoviePy 합성 — 폴백용으로 유지)
├── templates/
│   └── capcut_template/
│       ├── draft_content.json   ← 앤커 사운드코어 템플릿
│       ├── draft_meta_info.json
│       ├── draft_settings
│       ├── draft_virtual_store.json
│       ├── timeline_layout.json
│       ├── draft_biz_config.json
│       └── draft_agency_config.json
└── ...
```

### 함수 시그니처

```python
def build_capcut_project(
    template_dir: str | Path,       # templates/capcut_template/
    video_clips: list[str | Path],  # I2V 클립 경로 리스트 (3~4개)
    tts_path: str | Path,           # TTS MP3 절대 경로
    tts_duration_sec: float,        # TTS 길이 (초)
    srt_entries: list[dict],        # [{"text": str, "start": float, "end": float}, ...]  (초 단위)
    bgm_path: str | Path,           # BGM MP3 절대 경로
    product_name: str,              # 상품명
    project_name: str,              # CapCut 프로젝트명 (폴더명으로도 사용)
    cta_text: str = "구매링크는 프로필 링크 참고",
) -> Path:
    """
    CapCut 프로젝트 폴더를 생성하고 경로를 반환한다.

    1. template_dir에서 draft_content.json 로드
    2. 영상 총 길이 = tts_duration_sec + 2초
    3. Track 0: 비디오 클립 segments 교체 (video_clips 기반)
    4. Track 6: 상품명 텍스트 치환
    5. Track 9: SRT 자막 segments 동적 생성 (기존 segments 전부 삭제 → srt_entries로 재생성)
    6. Track 10: TTS 오디오 경로/duration 교체
    7. Track 11: BGM 경로/duration 교체
    8. Track 1~5, 7~8: 고정 요소의 duration을 total_duration으로 일괄 업데이트
    9. 루트 duration 업데이트
    10. CapCut 프로젝트 폴더에 저장 + 부속 파일 복사
    
    Returns: 생성된 CapCut 프로젝트 폴더 경로
    """
```

### 핵심 로직 상세

#### 1. 총 길이 계산

```python
total_duration_us = int((tts_duration_sec + 2.0) * 1_000_000)
```

TTS보다 2초 여유. 모든 고정 요소와 루트 duration에 적용.

#### 2. 비디오 클립 교체 (Track 0)

- 기존 segments 전부 삭제
- video_clips를 균등 분할하여 새 segments 생성
- 각 클립에 대해:
  - materials.videos에 새 material 추가 (path, duration, width=1080, height=1920)
  - tracks[0].segments에 새 segment 추가 (material_id 연결, source_timerange, target_timerange)
- 균등 분할: `clip_duration = total_duration_us / len(video_clips)`

```python
# 의사 코드
clip_dur = total_duration_us // len(video_clips)
for i, clip_path in enumerate(video_clips):
    mat_id = uuid4().hex  # 또는 pyCapCut API 사용
    # materials.videos에 추가
    # tracks[0].segments에 추가: target_timerange.start = i * clip_dur
```

#### 3. 상품명 텍스트 치환 (Track 6)

- materials.texts 중 상품명에 해당하는 material 찾기 (material_id로 매칭)
- content 필드가 JSON 문자열로 되어 있음 → json.loads() → text 필드 교체 → json.dumps()

```python
# materials.texts[idx]["content"]는 JSON string
content = json.loads(material["content"])
content["text"] = product_name
material["content"] = json.dumps(content, ensure_ascii=False)
```

#### 4. SRT 자막 동적 생성 (Track 9)

**가장 복잡한 부분.** 기존 자막 segments/materials를 전부 삭제하고 새로 생성.

```python
# 1. 기존 Track 9의 segment들에서 material_id 수집
# 2. materials.texts에서 해당 material_id들 삭제
# 3. tracks[9].segments 비우기
# 4. srt_entries 순회하면서:
#    a. 새 text material 생성 (기존 자막 material을 복제, text만 교체)
#    b. 새 segment 생성 (target_timerange.start/duration 설정)
#    c. materials.texts에 추가, tracks[9].segments에 추가
```

자막 material 생성 시 기존 자막 material 하나를 **템플릿으로 복제**하여 폰트/색상/스타일을 유지하고 text와 material_id만 교체하는 방식이 가장 안전하다.

#### 5. 오디오 교체 (Track 10: TTS, Track 11: BGM)

```python
# TTS
tts_material["path"] = str(tts_path)
tts_material["duration"] = int(tts_duration_sec * 1_000_000)
tts_material["name"] = Path(tts_path).name
tracks[10].segments[0].target_timerange = {"start": 0, "duration": tts_duration_us}
tracks[10].segments[0].source_timerange = {"start": 0, "duration": tts_duration_us}

# BGM — duration을 total_duration으로
bgm_material["path"] = str(bgm_path)
bgm_material["name"] = Path(bgm_path).name
tracks[11].segments[0].target_timerange["duration"] = total_duration_us
```

#### 6. 고정 요소 duration 일괄 업데이트

Track 1~5, 7~8의 모든 segments의 target_timerange.duration을 total_duration_us로 설정.

#### 7. canvas_config 패치 (pyCapCut 사용 시)

```python
# dumps() 전에 원본 canvas_config 보존
original_canvas = copy.deepcopy(draft["canvas_config"])
# ... pyCapCut 처리 ...
# dumps() 후 복원
draft["canvas_config"] = original_canvas
```

#### 8. 프로젝트 폴더 저장

```python
CAPCUT_PROJECTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"
project_dir = CAPCUT_PROJECTS / project_name
project_dir.mkdir(exist_ok=True)

# draft_content.json 저장
(project_dir / "draft_content.json").write_text(
    json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8"
)

# 부속 파일 복사
for fname in ["draft_meta_info.json", "draft_settings", "draft_virtual_store.json",
              "timeline_layout.json", "draft_biz_config.json", "draft_agency_config.json"]:
    src = template_dir / fname
    if src.exists():
        shutil.copy2(src, project_dir / fname)

# draft_meta_info.json에서 프로젝트명 변경
meta_path = project_dir / "draft_meta_info.json"
if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["draft_name"] = project_name  # 키 이름은 실제 파일에서 확인 필요
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
```

---

## 테스트 방법

### 테스트 스크립트 (test_capcut_builder.py)

```python
"""
capcut_builder.py 테스트
- 기존 PoC 데이터(Sony XM5)를 사용하여 CapCut 프로젝트 생성
- 생성된 프로젝트를 CapCut에서 열어서 정상 동작 확인
"""
from pathlib import Path
from scripts.capcut_builder import build_capcut_project

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"

# 기존 PoC에서 생성된 데이터 사용
result = build_capcut_project(
    template_dir=ROOT / "templates" / "capcut_template",
    video_clips=[
        OUTPUT / "earbuds_zoom.mp4",
        OUTPUT / "earbuds_float.mp4",
        OUTPUT / "earbuds_reveal.mp4",
    ],
    tts_path=OUTPUT / "tts" / "sony_xm5.mp3",
    tts_duration_sec=18.0,   # 실제 TTS 길이로 교체
    srt_entries=[
        {"text": "테스트 자막 1", "start": 0.0, "end": 3.0},
        {"text": "테스트 자막 2", "start": 3.0, "end": 6.0},
        {"text": "테스트 자막 3", "start": 6.0, "end": 9.0},
        {"text": "테스트 자막 4", "start": 9.0, "end": 12.0},
        {"text": "테스트 자막 5", "start": 12.0, "end": 15.0},
        {"text": "테스트 자막 6", "start": 15.0, "end": 18.0},
    ],
    bgm_path=ROOT / "kornevmusic-epic-478847.mp3",
    product_name="Sony WF-1000XM5 무선 이어폰",
    project_name="test_capcut_builder",
)

print(f"프로젝트 생성 완료: {result}")
print("CapCut 데스크톱에서 'test_capcut_builder' 프로젝트를 열어서 확인하세요.")
```

### 검증 체크리스트

1. [ ] CapCut 데스크톱에서 생성된 프로젝트가 목록에 나타나는가
2. [ ] 프로젝트를 열었을 때 크래시 없이 정상 로드되는가
3. [ ] 영상 클립 3개가 타임라인에 순서대로 배치되어 있는가
4. [ ] 상품명 텍스트가 "Sony WF-1000XM5 무선 이어폰"으로 바뀌어 있는가
5. [ ] SRT 자막 6개가 각각 올바른 시간대에 표시되는가
6. [ ] TTS 오디오가 재생되는가
7. [ ] BGM이 영상 전체 길이로 재생되는가
8. [ ] 배너/CTA/로고 등 고정 요소가 정상 표시되는가
9. [ ] 렌더링(내보내기) 버튼 → MP4 정상 출력되는가

---

## 폴백 전략

pyCapCut이 안 되면 (import 에러, 로드 실패, CapCut에서 안 열림 등):

**직접 JSON 조작으로 전환:**
```python
import json, uuid, copy, shutil
from pathlib import Path

def build_capcut_project(...):
    draft = json.loads(template_path.read_text(encoding="utf-8"))
    # dict 키 접근으로 직접 치환
    # material_id는 uuid.uuid4().hex[:32].upper()
    # 나머지 로직 동일
```

이 경우 pyCapCut의 add_segment()를 쓸 수 없으므로, 기존 segment dict를 copy.deepcopy()로 복제하고 필요한 필드만 교체하는 방식으로 진행.

---

## 참고 파일

- `capcut_json_분석.md` — 치환 포인트 상세 매핑
- `shortform-factory-handoff-v2.md` — MVP 전체 설계
- `scripts/build_shorts.py` — MoviePy 기반 기존 합성 코드 (폴백 참조)
- `scripts/pipeline.py` — 기존 파이프라인 (TTS/SRT 생성 로직 참조)

---

*2026.04.09 작성*
