# shorts_factory 파이프라인 v3 설계서 + Claude Code 지시서

> 2026.04.09 — shorts_factory Day 3 최종 산출물
> v2→v3 주요 변경: product_researcher→product_analyzer, strategist→PD(콘티 통합), 모델 이원화(Pro/Flash)
> Claude 기획 + Gemini/Grok 리뷰 반영 확정

---

## v2→v3 변경 요약

| 항목 | v2 | v3 |
|------|----|----|
| 상품 분석 | product_researcher (웹 검색 고정) | **product_analyzer** (유형 판별→분기→통일 JSON) |
| 전략 수립 | strategist (대본 전략만) | **PD** (대본 전략 + 콘티 + I2V 프롬프트 + 이미지 배정) |
| 영상 생성 | video_generator (프롬프트 지시 없음) | video_generator (**PD 콘티 참조**) |
| LLM | Gemini 단일 | **Gemini Pro (PD) + Flash (나머지)** |
| 중간 포맷 | .md (비구조화) | **.json (구조화, 파싱 안전)** |
| Type C 대응 | 불가 | 이미지 분석 + 트렌드 검색 하이브리드 |

---

## 에이전트 목록 & 모델 배정

| # | 에이전트 | 역할 (스튜디오 비유) | 모델 | 호출 횟수 |
|---|----------|---------------------|------|-----------|
| 1 | product_analyzer | 리서처 | Gemini Flash | 3~4회 |
| 2 | **pd_strategist** | **PD (총괄)** | **Gemini Pro** | **1회** |
| 3 | hook_writer | 작가 (훅) | Gemini Flash | 1회 |
| 4 | scriptwriter | 작가 (대본) | Gemini Flash | 1회 |
| 5 | script_reviewer | PD 검수 | Gemini Flash | 1회+ |
| 6 | tts_generator | 성우 | ElevenLabs API | 5회 |
| 7 | video_generator | 영상팀 | Grok Imagine API | 3~4회 |
| 8 | capcut_builder | 편집자 | 로컬 Python | 1회 |

**Gemini Pro는 PD 1회만.** 나머지 전부 Flash. 비용 최소화.

---

## 파이프라인 흐름

```
입력: 상품명 + 이미지 3~4장 + (선택: 가격, 상세, 메모)

① product_analyzer [Flash, 3~4회]
   → product_profile.json

② pd_strategist [Pro, 1회, 이미지 직접 참조]
   → strategy.json (소구 5종 + 콘티 + I2V 프롬프트 + 이미지 배정)

③ hook_writer [Flash, 1회]
   → hooks.json (소구별 훅 5개)

④ scriptwriter [Flash, 1회]
   → scripts.json (풀 대본 5개 + 제목 + 해시태그)

⑤ script_reviewer [Flash, 1회+]
   → scripts_final.json (확정 대본 5개)
   → 미달 시 ③으로 회귀

⑥⑦ 병렬 실행:
   tts_generator [ElevenLabs, 5회] → audio/ (MP3 + SRT 5세트)
   video_generator [Grok, 3~4회] → clips/ (모션 클립)

⑧ capcut_builder [로컬, 1회]
   → capcut_drafts/ (CapCut 프로젝트 5벌)

⑨ CapCut 데스크톱 (수동) → MP4 5개 출력
```

---

## 에이전트별 상세 스펙

### ① product_analyzer (리서처)

**모델:** Gemini Flash (멀티모달)

**입력:**
```python
product_name: str          # 필수
images: list[str]          # 필수, 3~4장
price_info: str | None     # 선택
detail_text: str | None    # 선택
seller_memo: str | None    # 선택
```

**내부 로직: 3-Step**

Step 1 — 유형 분류 (Flash, 이미지+텍스트, 1회):
- A_spec: 브랜드 명확 + 스펙 비교 가능 (Sony, Dyson)
- B_niche_spec: 브랜드 있지만 한국 인지도 낮음 (Baseus, Ugreen)
- C_emotion: 노브랜드/카테고리, 감성 중심 (무드등, 인테리어 소품)
- D_efficacy: 식품/건강/소모품 (마누카꿀, 비타민)
- E_visual: 패션/뷰티 (향수, 화장품)

Step 2 — 유형별 분기:
- A/B → 웹 검색 "{상품명} 스펙 리뷰 비교" (1회)
- C/E → 이미지 분석 + 누끼 방어 (1회) + 트렌드 검색 "{키워드} 트렌드 2026" (1회)
- D → 성분 검색 "{상품명} 성분 효능" (1회) + 규제 표현 필터

Step 3 — product_profile.json 생성 (1회):
- 전 타입 할루시네이션 통제: "확인되지 않은 스펙 창작 금지"
- source_reliability 판정: high/medium/low

**출력: product_profile.json**
```json
{
  "product_name": "LED 버섯 무드등",
  "product_type": "C_emotion",
  "one_liner": "자취방 감성 폭발하는 버섯 모양 무드등",
  "target_audience": "자취생, 인테리어에 관심 있는 20~30대",
  "selling_points": ["...", "...", "...", "...", "..."],
  "visual_hints": ["어두운 침실에서 은은하게 빛나는 장면", "...", "..."],
  "forbidden_expressions": ["수면 개선 효과"],
  "trend_keywords": ["데스크테리어", "자취방 꾸미기"],
  "image_analysis": {
    "img_1": "흰 배경 누끼, 버섯 모양 조명 정면샷",
    "img_2": "어두운 침실 협탁 위에 놓인 사용씬",
    "img_3": "박스 패키지 정면"
  },
  "price_advantage": "해외직구 12,900원 vs 국내 29,900원",
  "source_reliability": "low"
}
```

---

### ② pd_strategist (PD — 총괄)

**모델:** Gemini Pro (멀티모달) — 이미지 직접 참조

**입력:**
- product_profile.json
- 원본 이미지 3~4장 (멀티모달 첨부)

**하는 일:**
1. 소구 전략 5종 수립 (서로 겹치지 않게)
2. 각 소구별 클립 3~4개 장면 구성 (스토리보드/콘티)
3. 입력 이미지 → 클립 배정 (어떤 이미지가 어떤 장면에)
4. 클립별 I2V 프롬프트 작성 (Grok Imagine용)
5. source_reliability low면 스펙 소구 비중 ↓, 감성/가성비 ↑

**프롬프트 핵심:**
```
너는 숏폼 광고 영상의 PD다.
상품 프로필과 실제 상품 이미지를 보고, 5개의 서로 다른 광고 영상을 기획하라.

각 영상(소구)별로 다음을 출력:
1. 소구 타입 (informative/empathy/scenario/review/comparison)
2. 소구 방향 1줄 요약
3. 클립 구성 (3~4개):
   - 클립 번호
   - 장면 설명 (어떤 그림이 보여야 하는지)
   - 사용할 입력 이미지 번호 (img_1, img_2, img_3...)
   - I2V 프롬프트 (Grok Imagine에 넣을 영문 프롬프트)
   - 타임라인 위치 (intro/middle/climax/outro)

[규칙]
- 같은 이미지를 다른 소구에서 재사용해도 되지만, I2V 프롬프트는 달라야 한다
- 누끼컷(흰 배경) 이미지는 "zoom in rotation on white background" 같은 제품 중심 모션으로
- 라이프스타일 이미지는 "gentle camera movement revealing the product in use" 같은 씬 모션으로
- I2V 프롬프트는 영문으로, 6초 클립 기준으로 작성
- source_reliability가 low면 스펙 나열형(informative) 대신 감성/상황극 비중을 높여라

JSON으로만 응답하라.
```

**출력: strategy.json**
```json
{
  "variants": [
    {
      "variant_id": "v1_informative",
      "hook_type": "informative",
      "direction": "숨겨진 기능 3가지로 스펙 어필",
      "clips": [
        {
          "clip_num": 1,
          "scene": "제품 정면 클로즈업에서 천천히 줌인",
          "source_image": "img_1",
          "i2v_prompt": "slow zoom in on a mushroom-shaped LED lamp on white background, soft lighting, product showcase",
          "timeline": "intro"
        },
        {
          "clip_num": 2,
          "scene": "어두운 방에서 조명이 켜지는 순간",
          "source_image": "img_2",
          "i2v_prompt": "dark bedroom slowly illuminated by warm mushroom lamp on nightstand, cozy atmosphere",
          "timeline": "middle"
        },
        {
          "clip_num": 3,
          "scene": "터치로 밝기 조절하는 손 클로즈업",
          "source_image": "img_3",
          "i2v_prompt": "hand gently touching the top of mushroom lamp, brightness changes, close-up",
          "timeline": "climax"
        },
        {
          "clip_num": 4,
          "scene": "책상 위 소품들 사이에 놓인 전체샷",
          "source_image": "img_1",
          "i2v_prompt": "aesthetic desk setup with mushroom lamp among stationery items, slight camera pan right",
          "timeline": "outro"
        }
      ]
    }
  ]
}
```

---

### ③ hook_writer (작가 — 훅)

**모델:** Gemini Flash
**입력:** strategy.json (소구별 direction)
**출력:** hooks.json — 소구별 초반 3초 훅 텍스트

---

### ④ scriptwriter (작가 — 대본)

**모델:** Gemini Flash
**입력:** hooks.json + strategy.json + product_profile.json
**출력:** scripts.json — 소구별 풀 대본 (100자 이내) + 제목 + 해시태그

---

### ⑤ script_reviewer (PD 검수)

**모델:** Gemini Flash
**입력:** scripts.json
**출력:** scripts_final.json — 확정 대본. 미달 시 hook_writer로 회귀.
**검수 기준:** 훅 임팩트, 글자수, forbidden_expressions 위반 여부, 소구간 차별성

---

### ⑥ tts_generator (성우)

**API:** ElevenLabs eleven_v3 Matilda
**입력:** scripts_final.json
**출력:** audio/ (MP3 5개 + SRT 5개, word-level 타임스탬프)

---

### ⑦ video_generator (영상팀)

**API:** Grok Imagine
**입력:** strategy.json (clips 배열) + 원본 이미지
**출력:** clips/ (6초 모션 클립)

**핵심:** strategy.json의 클립별 `source_image` + `i2v_prompt`를 그대로 실행.
자체 판단 없음. PD 지시대로만 움직인다.

**최적화:** 같은 이미지+같은 프롬프트 조합은 1회만 생성하고 재사용.

---

### ⑧ capcut_builder (편집자)

**입력:** audio/ + clips/ + scripts_final.json + strategy.json + 템플릿
**출력:** capcut_drafts/ (CapCut 프로젝트 5벌)

Day 2에서 구현 완료. v3에서 추가 변경 없음.
단, strategy.json의 timeline 배치를 참조하여 클립 순서 결정.

---

## 디렉토리 구조

```
shorts_factory/
├── agents/
│   ├── product_analyzer.py    # ① 리서처 [Flash]
│   ├── pd_strategist.py       # ② PD [Pro]
│   ├── hook_writer.py         # ③ 작가-훅 [Flash]
│   ├── scriptwriter.py        # ④ 작가-대본 [Flash]
│   ├── script_reviewer.py     # ⑤ 검수 [Flash]
│   ├── tts_generator.py       # ⑥ 성우 [ElevenLabs]
│   ├── video_generator.py     # ⑦ 영상팀 [Grok]
│   └── capcut_builder.py      # ⑧ 편집자 [로컬] (Day 2 완료)
├── core/
│   ├── llm_client.py          # Gemini Pro/Flash 통합 클라이언트
│   ├── checkpoint.py          # load_or_run 로직
│   └── config.py              # API 키, 모델 설정
├── templates/
│   ├── capcut_template/       # CapCut 더미 프로젝트
│   └── reference_hooks.md     # 조회수 높은 훅 패턴
├── output/
│   └── {product_name}/
│       ├── product_profile.json
│       ├── strategy.json
│       ├── hooks.json
│       ├── scripts.json
│       ├── scripts_final.json
│       ├── audio/
│       ├── clips/
│       └── capcut_drafts/
├── pipeline.py                # 메인 오케스트레이터
├── config.yaml                # API 키, 경로
└── README.md
```

---

## config.yaml

```yaml
llm:
  pro:
    provider: gemini
    model: gemini-2.5-pro
    api_key: "${GEMINI_API_KEY}"
  flash:
    provider: gemini
    model: gemini-2.5-flash
    api_key: "${GEMINI_API_KEY}"
  fallback:
    provider: claude
    model: claude-sonnet-4-20250514
    api_key: "${CLAUDE_API_KEY}"

tts:
  provider: elevenlabs
  voice: Matilda
  model: eleven_multilingual_v2
  api_key: "${ELEVENLABS_API_KEY}"

i2v:
  provider: grok
  api_key: "${XAI_API_KEY}"

paths:
  template_dir: "./templates/capcut_template"
  output_dir: "./output"
  reference_hooks: "./templates/reference_hooks.md"
```

---

## pipeline.py 핵심 로직

```python
import json
from core.checkpoint import load_or_run
from core.llm_client import GeminiClient
from agents import (
    product_analyzer, pd_strategist, hook_writer,
    scriptwriter, script_reviewer, tts_generator,
    video_generator, capcut_builder
)

def run(product_name: str, images: list[str],
        price_info: str = None, detail_text: str = None,
        seller_memo: str = None):
    """메인 파이프라인 오케스트레이터"""

    out = f"./output/{product_name}"
    os.makedirs(out, exist_ok=True)

    # 이미지 인덱스 매핑 (전 에이전트 공유)
    # img_1 = images[0], img_2 = images[1], ...
    image_map = {f"img_{i+1}": path for i, path in enumerate(images)}

    # ① 리서처 [Flash]
    profile = load_or_run(
        f"{out}/product_profile.json",
        product_analyzer.run,
        product_name, images, price_info, detail_text, seller_memo
    )

    # ② PD [Pro] — 이미지 직접 전달
    strategy = load_or_run(
        f"{out}/strategy.json",
        pd_strategist.run,
        profile, images
    )

    # ③~⑤ 대본 체인 [Flash] — 회귀 루프는 pipeline에서 제어
    MAX_RETRIES = 2
    for attempt in range(MAX_RETRIES + 1):
        hooks = load_or_run(
            f"{out}/hooks_v{attempt}.json" if attempt > 0 else f"{out}/hooks.json",
            hook_writer.run,
            strategy
        )

        scripts = load_or_run(
            f"{out}/scripts_v{attempt}.json" if attempt > 0 else f"{out}/scripts.json",
            scriptwriter.run,
            hooks, strategy, profile
        )

        review_result = script_reviewer.run(scripts, profile)
        # script_reviewer는 pass/fail + 피드백만 반환 (순수 함수)
        if review_result["all_passed"] or attempt == MAX_RETRIES:
            scripts_final = review_result["scripts"]
            save_json(f"{out}/scripts_final.json", scripts_final)
            break
        # 미달 시 checkpoint 파일 삭제하고 재생성
        logger.info(f"대본 미달 — 재생성 {attempt+1}/{MAX_RETRIES}")

    # ⑥⑦ 병렬 실행
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        audio_future = executor.submit(
            tts_generator.run, scripts_final, out
        )
        clips_future = executor.submit(
            video_generator.run, strategy, images, image_map, out
        )
        audio_result = audio_future.result()
        clips_result = clips_future.result()

    # ⑧ 편집자 [로컬]
    capcut_builder.run(
        audio_dir=f"{out}/audio",
        clips_dir=f"{out}/clips",
        scripts=scripts_final,
        strategy=strategy,
        output_dir=f"{out}/capcut_drafts"
    )

    print(f"완료: {out}/capcut_drafts/ 에 프로젝트 5벌 생성됨")
    print("→ CapCut 데스크톱에서 열어서 렌더링하세요")
```

---

## Gemini API 호출 총 횟수

| 에이전트 | 모델 | 호출 수 |
|----------|------|---------|
| product_analyzer | Flash | 3~4회 |
| pd_strategist | **Pro** | **1회** |
| hook_writer | Flash | 1회 |
| scriptwriter | Flash | 1회 |
| script_reviewer | Flash | 1~3회 |
| **합계** | | **7~10회** |

+ ElevenLabs 5회, Grok 3~4회

Flash 무료 티어 분당 15회 → 여유. Pro 무료 크레딧 → 1회뿐이라 비용 무시.

---

## 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| Gemini Pro 무료 크레딧 소진 | Claude Sonnet 폴백 (config.yaml fallback) |
| Gemini Flash rate limit | checkpoint로 실패 지점부터 재실행 |
| PD JSON 출력 깨짐 | json.loads() 실패 시 1회 재시도 + "JSON만 출력" 강화 프롬프트 |
| I2V 프롬프트 퀄리티 | PD 프롬프트에 예시 3개 포함. 결과 나쁘면 프롬프트 튜닝 |
| 이미지 배정 오류 | PD가 이미지를 직접 보고 판단하므로 v2 대비 대폭 개선 |
| 할루시네이션 | product_analyzer 네거티브 프롬프팅 + source_reliability 전파 |

---

## 채택 내역

| 출처 | 채택 | 보류 |
|------|------|------|
| **Gemini (1차)** | 감성형 하이브리드 리서치, 누끼컷 방어, 할루시네이션 통제, JSON 출력 강제 | — |
| **Grok (1차)** | visual_hints 필드, PD 시각적 힌트 활용 | 하이브리드 유형(주+보조) → MVP 이후 |
| **Claude** | 전체 아키텍처, product_analyzer 3-Step, PD 콘티 통합, 모델 이원화(Pro/Flash), 토큰 효율 분석 | — |
| **Gemini (2차-설계서리뷰)** | Gemini SDK `response_mime_type` JSON 강제, video_generator 폴링/타임아웃/백오프, 이미지 인덱스 매핑 규칙 통일, 회귀 루프를 pipeline.py로 이동 | — |
| **Grok (2차-설계서리뷰)** | PD 프롬프트에 I2V 예시 포함 강조, product_profile에 image_analysis 필드 추가, variant 간 클립 구성 스타일 차별화 | 3개 이상 미달 시 PD 재실행 → MVP 이후 |

---

# Claude Code 지시서

> 이 섹션을 Claude Code에 그대로 전달하여 구현을 지시한다.

---

## 지시 개요

shorts_factory 프로젝트의 에이전트 체인을 v3 설계에 맞춰 구현하라.
Day 2에서 완료된 capcut_builder.py는 그대로 유지.
나머지 에이전트 + core 모듈 + pipeline.py를 새로 구현한다.

**작업 순서대로 실행하라. 각 단계 완료 후 테스트하고 다음으로 넘어가라.**

---

## Step 1: core/ 모듈 구현

### core/config.py
- config.yaml 로드
- 환경변수에서 API 키 읽기 (${VAR} 문법 처리)
- `get_llm_config(tier: "pro" | "flash" | "fallback")` 함수

### core/llm_client.py
- GeminiClient 클래스
  - `__init__(self, tier: str)` — config에서 모델/키 로드
  - `call(self, prompt: str, images: list[str] = None, json_mode: bool = True, response_schema: dict = None) -> dict`
  - **json_mode=True면 Gemini SDK의 `response_mime_type="application/json"` 파라미터를 반드시 설정하라.** 프롬프트로만 JSON 강제하지 말고 SDK 레벨에서 강제. `response_schema`가 주어지면 함께 전달하여 출력 포맷을 원천 차단.
  - SDK 레벨 JSON 강제에도 파싱 실패 시 1회 재시도 (프롬프트에 "JSON만 출력하라" 추가하여 폴백)
  - images 전달 시 Gemini 멀티모달 호출 (이미지를 base64로 인코딩하여 첨부)
  - rate limit 에러 시 exponential backoff (3초 → 6초 → 12초, 최대 3회)
  - Gemini 실패 시 fallback(Claude) 자동 전환

### core/checkpoint.py
- `load_or_run(filepath: str, func: callable, *args, **kwargs)`
  - filepath 존재하면 json.load()로 로드하여 반환
  - 없으면 func(*args, **kwargs) 실행 → 결과를 filepath에 json.dump() 저장 → 반환

**테스트:** config.yaml 샘플 만들고, GeminiClient로 "hello" 호출 성공 확인.

---

## Step 2: agents/product_analyzer.py

product_analyzer_설계.md의 3-Step 로직 그대로 구현.

```python
def run(product_name, images, price_info=None, detail_text=None, seller_memo=None) -> dict:
```

- Step 1: GeminiClient("flash").call(분류 프롬프트, images=images)
- Step 2: 유형별 분기 (if/elif)
  - A/B → GeminiClient("flash").call(웹 검색 프롬프트)
  - C/E → GeminiClient("flash").call(이미지 분석 프롬프트, images=images) → GeminiClient("flash").call(트렌드 검색 프롬프트)
  - D → GeminiClient("flash").call(성분 검색 프롬프트)
- Step 3: GeminiClient("flash").call(JSON 구조화 프롬프트)
- 출력 스키마 검증: product_type, selling_points(5개), visual_hints(3개), image_analysis(이미지 수만큼), source_reliability 필수

**프롬프트는 위 설계서의 프롬프트 핵심 섹션을 참조하되, 실제 프롬프트 텍스트를 상수로 agents/prompts/ 디렉토리에 분리하라.**

**테스트:** "앤커 사운드코어 슬립 A30" (Type A) + "버섯등" (Type C) 각각 돌려서 product_profile.json 정상 출력 확인.

---

## Step 3: agents/pd_strategist.py

```python
def run(profile: dict, images: list[str]) -> dict:
```

- GeminiClient("pro").call(PD 프롬프트, images=images)
- 입력: product_profile.json 내용 + 원본 이미지
- 출력: strategy.json (위 설계서의 스키마 참조)
- 출력 검증: variants 5개, 각각 clips 3~4개, 각 clip에 source_image + i2v_prompt 필수

**테스트:** product_analyzer 결과를 넣고 strategy.json 정상 출력 확인. clips의 source_image가 실제 존재하는 이미지 번호인지 검증.

---

## Step 4: agents/hook_writer.py + scriptwriter.py + script_reviewer.py

### hook_writer.py
```python
def run(strategy: dict) -> dict:
```
- Flash 1회. strategy.json의 각 variant direction을 보고 훅 생성.
- 출력: hooks.json — `{"hooks": [{"variant_id": "v1_informative", "hook_text": "..."}, ...]}`

### scriptwriter.py
```python
def run(hooks: dict, strategy: dict, profile: dict) -> dict:
```
- Flash 1회. 훅 + 소구 방향 + 상품 프로필을 보고 풀 대본 작성.
- 출력: scripts.json — 각 variant별 `script_text` (100자 이내) + `title` + `hashtags`

### script_reviewer.py
```python
def run(scripts: dict, profile: dict) -> dict:
```
- Flash 1회. 각 대본에 점수 (1~10).
- forbidden_expressions 위반 체크.
- **순수 함수로 구현.** 합격 여부와 피드백만 반환. 회귀/재생성 루프는 pipeline.py에서 제어.
- 출력: `{"all_passed": true/false, "scripts": [...], "feedback": [{"variant_id": "...", "score": 8, "passed": true}, ...]}`

**테스트:** 의도적으로 나쁜 대본을 넣어서 pipeline.py의 재생성 루프가 작동하는지 확인.

---

## Step 5: agents/tts_generator.py + video_generator.py

### tts_generator.py
```python
def run(scripts_final: dict, output_dir: str) -> dict:
```
- ElevenLabs API로 각 variant 대본 → MP3 + SRT
- word-level 타임스탬프 요청
- 출력: audio/ 디렉토리에 v1.mp3, v1.srt, v2.mp3, v2.srt ...

### video_generator.py
```python
def run(strategy: dict, images: list[str], image_map: dict, output_dir: str) -> dict:
```
- strategy.json의 clips 배열을 순회
- 각 clip의 source_image를 image_map으로 실제 파일 경로 변환 (img_1 → images[0])
- 각 clip의 source_image + i2v_prompt로 Grok Imagine API 호출
- **중복 제거:** 같은 (source_image, i2v_prompt) 조합은 1회만 생성, 결과 재사용 (딕셔너리 캐시)
- **I2V는 응답에 수십 초~수분 걸림.** 비동기 폴링 로직 또는 충분한 timeout(최소 120초) 설정 필수. rate limit 고려하여 요청 간 2~3초 딜레이 + exponential backoff 적용.
- 클립 길이: 6초 기준
- 출력: clips/ 디렉토리에 clip_v1_1.mp4, clip_v1_2.mp4 ...

---

## Step 6: pipeline.py

위 설계서의 pipeline.py 핵심 로직을 구현.
- **이미지 인덱스 매핑:** pipeline 진입 시 `image_map = {f"img_{i+1}": path for i, path in enumerate(images)}` 생성. 이 딕셔너리를 video_generator에 전달.
- **대본 회귀 루프:** script_reviewer는 pass/fail만 반환. pipeline.py에서 `while` 또는 `for` 루프로 미달 시 hook_writer부터 재호출 (최대 2회).
- checkpoint 적용 (모든 중간 산출물)
- tts + video 병렬 실행 (ThreadPoolExecutor)
- 에러 시 해당 단계만 재실행 가능하도록

---

## Step 7: 통합 테스트

실제 상품 1개로 end-to-end 풀 파이프라인:
```bash
python pipeline.py --product "LED 버섯 무드등" --images img_1.jpg img_2.jpg img_3.jpg
```

확인 사항:
- [ ] product_profile.json 생성됨
- [ ] strategy.json에 variants 5개, 각각 clips 3~4개
- [ ] scripts_final.json에 확정 대본 5개
- [ ] audio/에 MP3+SRT 5세트
- [ ] clips/에 모션 클립
- [ ] capcut_drafts/에 프로젝트 5벌
- [ ] CapCut 데스크톱에서 프로젝트 정상 로드

---

## 구현 규칙

1. **프롬프트는 agents/prompts/ 디렉토리에 텍스트 파일로 분리.** 코드에 인라인 금지. 프롬프트 튜닝 시 코드 수정 불필요하도록.
2. **모든 에이전트 출력은 JSON.** .md 사용 금지. Gemini SDK `response_mime_type="application/json"` 우선 적용, 그래도 파싱 실패 시 재시도.
3. **checkpoint 적용 필수.** 중간 파일 존재 시 스킵. 실패 시 해당 단계만 재실행.
4. **로깅:** 각 에이전트 호출 시 `[에이전트명] 시작/완료/실패` 로그. print가 아닌 logging 모듈 사용.
5. **타입 힌트:** 모든 함수에 타입 힌트 적용.
6. **capcut_builder.py는 건드리지 마라.** Day 2 완성본 그대로 유지. strategy.json의 timeline 필드만 추가로 읽도록 연결점만 수정.
7. **모델명:** config.yaml의 Gemini/Claude 모델명은 구현 시점의 최신 안정 버전으로 확인 후 적용. 현재 기준 gemini-2.5-pro / gemini-2.5-flash.
8. **에이전트는 순수 함수.** 상태를 가지지 않는다. 입력 받고 출력 반환만. 루프/회귀/재시도 제어는 전부 pipeline.py에서.

---

*2026.04.09 작성 — shorts_factory Day 3 최종*
