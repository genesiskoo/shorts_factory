# AI 숏폼 자동생성 파이프라인

상품 이미지 3~4장 → 20~25초 세로형(9:16) 광고 숏폼 MP4 자동 생성.  
해외직구 셀러 대상. 기존 CapCut 수작업(3~4시간) → 사람 개입 2~3분 + 렌더링 5~7분으로 단축.

---

## 파이프라인 흐름

```
상품 이미지 (3~4장)
    │
    ├── [preprocess_image.py]  이미지 → 9:16 (1080×1920) 전처리
    │
    ├── [Image-to-Video API]   이미지 → 6초 모션 클립 (Hailuo 02 / Grok Imagine)
    │
    ├── [pipeline.py] ──────── Gemini 대본 생성 → ElevenLabs TTS + SRT
    │
    └── [build_shorts.py] ───  클립 연결 + TTS + BGM + Pillow 오버레이 → 최종 MP4
```

---

## 기술 스택

| 역할 | 도구 |
|------|------|
| Image-to-Video | Hailuo 02 (Atlas Cloud API) / xAI Grok Imagine |
| 대본 생성 | Gemini 2.5 Flash |
| TTS | ElevenLabs Flash v2.5 (`eleven_flash_v2_5`) |
| 영상 합성 | MoviePy 2.x + FFmpeg (NVENC 하드웨어 인코딩) |
| 한글 텍스트 | Pillow (MoviePy TextClip 한글 깨짐 이슈 회피) |
| 이미지 전처리 | Pillow |
| 런타임 | Python 3.10+ / Windows 11 |

---

## 설치

### 사전 요구사항

- Python 3.10+
- [FFmpeg](https://www.gyan.dev/ffmpeg/builds/) (winget: `Gyan.FFmpeg`)
- NVIDIA GPU (RTX 계열, NVENC 인코딩)

### 패키지 설치

```bash
python -m venv venv
venv\Scripts\activate
pip install moviepy pillow requests python-dotenv google-genai
```

### 환경 변수 (`.env`)

```env
XAI_API_KEY=xai-...          # Grok Imagine Video API
ATLAS_API_KEY=...             # Atlas Cloud API (Hailuo 02 / Seedance)
GEMINI_API_KEY=AIza...        # Gemini 대본 생성
ELEVENLABS_API_KEY=...        # TTS
```

---

## 스크립트 목록

### 테스트 / 검증

| 파일 | 설명 |
|------|------|
| `scripts/test_grok_imagine.py` | Grok Imagine Video API — 이미지 → 6초 클립, 프롬프트 3종 |
| `scripts/test_grok_prompts.py` | cinematic / dynamic / lifestyle 프롬프트 비교 |
| `scripts/test_atlas_cloud.py` | Hailuo 02 Standard vs Seedance 1.5 Fast 비교 |
| `scripts/test_916_ratio.py` | 9:16 비율 확보 방법 비교 (Pillow 전처리 vs `aspect_ratio` 파라미터) |
| `scripts/compare_ko_voices.py` | ElevenLabs 한국어 음성 탐색 + TTS 샘플 생성 |

### 핵심 파이프라인

| 파일 | 설명 |
|------|------|
| `scripts/preprocess_image.py` | 상품 이미지 → 1080×1920 변환 (pad / crop 모드) |
| `scripts/build_shorts.py` | 클립 합성 빌더 — 영상 연결 + TTS/BGM 믹싱 + Pillow 오버레이 |
| `scripts/pipeline.py` | 엔드-투-엔드 실행 — 대본 생성 → TTS → SRT → 영상 합성 |

---

## 실행 방법

### 1. 이미지 전처리

```bash
python scripts/preprocess_image.py
# 결과: assets/preprocessed/*_916.jpg
```

### 2. 개별 테스트 (API 검증)

```bash
# Image-to-Video API 비교
python scripts/test_atlas_cloud.py

# 한국어 TTS 음성 비교 샘플 생성
python scripts/compare_ko_voices.py
# 결과: output/tts/voice_compare_*.mp3 + voice_compare_report.txt
```

### 3. 풀 파이프라인 실행

```bash
python scripts/pipeline.py
# 결과: output/shorts_<상품슬러그>.mp4
```

`pipeline.py` 상단의 `PRODUCT` 딕셔너리와 `VOICE_ID`를 상품에 맞게 수정 후 실행.

---

## 영상 레이어 구조 (1080×1920 / 24fps)

```
┌──────────────────────┐
│  상단 배너 (채널명)   │  ← 반투명 검정 + 흰 텍스트
├──────────────────────┤
│                      │
│   Image-to-Video     │
│   모션 클립 (루프)   │
│                      │
├──────────────────────┤
│  SRT 자막            │  ← 어절 단위, Pillow 렌더링
├──────────────────────┤
│  상품명 + 가격       │  ← 흰/금색 텍스트, 그림자
├──────────────────────┤
│  CTA 버튼 바         │  ← 주황 배경 + 흰 텍스트
└──────────────────────┘
오디오: TTS + BGM (볼륨 12%)
```

---

## API 비용 추정 (숏폼 1편 기준)

| 항목 | 단가 | 숏폼 1편 예상 비용 |
|------|------|-------------------|
| Hailuo 02 (5초 클립 × 3) | ~$0.05/초 | ~$0.75 |
| Grok Imagine (6초 클립 × 3) | $0.07/초 | ~$1.26 |
| Gemini 2.5 Flash (대본) | $0.15/1M input tokens | ~$0.001 |
| ElevenLabs Flash v2.5 (TTS) | $0.30/1,000자 | ~$0.03 |

> 숏폼 1편 총 비용 약 $0.8~1.3 (약 1,100~1,800원)

---

## 개발 로그

| Day | 내용 |
|-----|------|
| Day 1 | 프로젝트 초기화, Grok Imagine API 테스트 (cinematic/dynamic/lifestyle 3종) |
| Day 1+ | Atlas Cloud API 비교 — Hailuo 02 Standard / Seedance 1.5 Fast |
| Day 1+ | 9:16 비율 확보 방법 검증 (Pillow 전처리 vs aspect_ratio 파라미터) |
| Day 2 | ElevenLabs 한국어 음성 탐색, build_shorts.py 합성 빌더 구현 |
| Day 2 | pipeline.py 풀 파이프라인 — Gemini 대본 → TTS/SRT → 영상 합성 |

---

## 폴더 구조

```
shorts_factory/
├── scripts/
│   ├── pipeline.py           # 풀 파이프라인
│   ├── build_shorts.py       # 영상 합성 빌더
│   ├── preprocess_image.py   # 이미지 전처리
│   ├── compare_ko_voices.py  # TTS 음성 비교
│   ├── test_atlas_cloud.py   # Image-to-Video API 비교
│   ├── test_grok_imagine.py  # Grok API 테스트
│   ├── test_grok_prompts.py  # 프롬프트 비교
│   └── test_916_ratio.py     # 9:16 비율 테스트
├── assets/
│   └── preprocessed/         # 전처리된 9:16 이미지
├── output/
│   └── tts/                  # TTS mp3 + SRT 파일
├── .env                      # API 키 (git 제외)
├── CLAUDE.md                 # Claude Code 프로젝트 지시서
└── README.md
```

---

## 주의사항

- **한글 텍스트**: MoviePy `TextClip`(ImageMagick) 한글 깨짐 이슈로 **반드시 Pillow**로 렌더링
- **FFmpeg 경로**: `scripts/*.py` 상단 `FFMPEG_BINARY` 환경변수를 로컬 설치 경로에 맞게 수정
- **Image-to-Video URL**: 생성 후 임시 URL이므로 즉시 다운로드 필요
- **출력 파일**: `output/` 디렉터리의 생성물은 git 추적 제외 (`.gitignore` 설정됨)
