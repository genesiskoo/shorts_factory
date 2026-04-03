# AI 숏폼 자동생성 파이프라인 — Claude Code 프로젝트 지시서

## 프로젝트 개요

상품 URL + 이미지 3~4장 → 20~25초 세로형(9:16) 광고 숏폼 자동 생성 파이프라인.
해외직구 셀러 대상. 기존 CapCut 수작업(1건 3~4시간)을 자동화하여 사람 개입 2~3분 + 렌더링 대기 5~7분으로 단축하는 것이 목표.

## 기술 스택

- Python 3.10+
- MoviePy + FFmpeg (영상 합성)
- Pillow (한글 텍스트 렌더링 — MoviePy TextClip은 한글 깨짐이므로 반드시 Pillow 사용)
- xAI Grok Imagine Video API (이미지 → 6초 모션 클립 생성)
- ElevenLabs Flash API (한국어 TTS + word-level 타임스탬프)
- LLM API (대본 생성 — Anthropic 또는 OpenAI)
- BeautifulSoup/Selenium (상품 URL 크롤링)

## 작업 환경

- Windows 11
- CPU: i7-13700K (16코어/24스레드)
- RAM: 32GB
- GPU: RTX 4070 (NVENC 하드웨어 인코딩 가능)
- 저장소: NVMe SSD

## 파이프라인 구조

```
① URL 입력 → 크롤링 → 상품 정보 추출
② LLM 대본 생성 → 3개 대본 → 사용자 선택
③ TTS → ElevenLabs Flash → MP3 + word-level 타임스탬프 JSON → SRT 변환
④ 이미지→영상 → Grok Imagine API → 6초 모션 클립 3~4개
⑤ 영상 합성 (MoviePy + FFmpeg + Pillow)
   → 클립 연결 + TTS + Pillow 한글 자막/오버레이 + BGM → 9:16 숏폼 출력
⑥ 변형 생성 → BGM/클립순서/대본 교체로 5개 버전 자동 출력
```

## 영상 레이어 구조 (9:16, 1080×1920)

| 레이어 | 내용 | 구현 방법 |
|--------|------|-----------|
| 1. BGM | lo-fi 배경음악 | AudioFileClip + volumex() |
| 2. TTS | 상품 설명 나레이션 | AudioFileClip |
| 3. 영상 클립 | Grok Imagine 클립 3~4개 | concatenate_videoclips |
| 4. 상품 이미지 | 고정 위치 오버레이 | ImageClip |
| 5. 상단 배너 | 브랜드 PNG | ImageClip |
| 6~8. 텍스트 | 상품명 / CTA / 태그 | Pillow → ImageClip |
| 9. 오토캡션 | word-level 자막 | Pillow 이미지 기반 시퀀스 |

## Grok Imagine Video API 사용법

```python
import requests, time

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {XAI_API_KEY}",
}

# 1. 영상 생성 요청
response = requests.post(
    "https://api.x.ai/v1/videos/generations",
    headers=headers,
    json={
        "model": "grok-imagine-video",
        "prompt": "Slowly zoom in on the product with soft studio lighting",
        "image": {"url": "https://상품이미지URL"},
        "duration": 6,
        "aspect_ratio": "9:16",
        "resolution": "720p",
    },
)
request_id = response.json()["request_id"]

# 2. 폴링
while True:
    result = requests.get(
        f"https://api.x.ai/v1/videos/{request_id}",
        headers={"Authorization": headers["Authorization"]},
    )
    data = result.json()
    if data["status"] == "done":
        video_url = data["video"]["url"]
        break
    elif data["status"] == "error":
        raise Exception(data.get("error"))
    time.sleep(5)
```

가격: 영상 초당 ~$0.07. 6초 클립 1개 ≈ $0.42 (약 580원).
숏폼 1개(클립 4개) ≈ $1.68 (약 2,300원). 마진은 여전히 충분.

## 한글 텍스트 렌더링 방침

MoviePy TextClip(ImageMagick 의존)은 한글 깨짐 이슈가 있으므로,
모든 한글 텍스트는 Pillow로 이미지 렌더링 후 ImageClip으로 합성한다.

```python
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy.editor import ImageClip

def make_text_image(text, font_path, font_size, color, canvas_size):
    img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, font_size)
    draw.text((x, y), text, font=font, fill=color)
    return ImageClip(np.array(img), ismask=False, transparent=True)
```

## 프롬프트 템플릿 3종 (Grok Imagine용)

1. **cinematic**: "Slowly zoom in on the product with soft studio lighting, elegant product showcase, smooth camera movement, premium commercial feel"
2. **dynamic**: "Dynamic camera orbit around the product, energetic movement, vibrant lighting with subtle particle effects, eye-catching product reveal"
3. **lifestyle**: "Product gently floating with a soft bokeh background, warm natural lighting, lifestyle commercial aesthetic, inviting and aspirational mood"

---

# 오늘 할 일 (Day 1)

## 목표: Grok Imagine API가 숏폼에 쓸만한지 판단

### Task 1: 프로젝트 초기화
- Python 가상환경 생성
- 의존성 설치: moviepy, pillow, requests, python-dotenv
- FFmpeg 설치 확인
- .env 파일에 XAI_API_KEY 설정
- 프로젝트 폴더 구조 잡기

### Task 2: Grok Imagine API 테스트 스크립트
- 상품 이미지 URL 1개 → 6초 image-to-video 생성
- 비동기 요청 → 폴링 → 다운로드까지 완전한 흐름
- 프롬프트 3종(cinematic/dynamic/lifestyle) 각각 테스트
- 9:16 세로 비율 확인
- 결과 mp4 저장

### Task 3: 결과 판단
- 생성된 3개 클립 퀄리티 확인
- OK → Day 2 진행 (MoviePy 뼈대 + Pillow 텍스트)
- NG → 대안 API 조사 (Kling, Runway 등)

### 참고
- xAI 공식 문서: https://docs.x.ai/developers/model-capabilities/video/generation
- 영상 URL은 임시 URL이므로 생성 후 즉시 다운로드할 것
- 9:16 비율 지원 확인 필요 (문서에서 aspect_ratio 파라미터 확인)