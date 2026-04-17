# shorts_factory Web UI 구축 지시서 (MVP)

> **대상**: Claude Code  
> **작성일**: 2026-04-17  
> **목표 납기**: 1주 (7일)  
> **기반 프로젝트**: https://github.com/genesiskoo/shorts_factory (Day 3 v3 파이프라인 구현 완료 상태)

---

## 0. 프로젝트 개요

### 0.1 무엇을 만드는가

`shorts_factory` Python 파이프라인을 **로컬 웹 UI**로 조작할 수 있게 만든다. CLI로 돌리던 파이프라인을 브라우저에서 Human-in-the-Loop 방식으로 단계별 검수하며 실행한다.

### 0.2 핵심 차별점

기존 `pipeline.py`는 "한 번 돌리면 끝까지 간다" 구조. 이 Web UI는 **각 단계에서 사용자가 검수/선택/재생성할 수 있게 분리**한다. 퀄리티가 완벽하지 않아도 되지만, **대본/영상 같은 비용/시간 큰 단계 전에는 반드시 검수 기회**를 제공해야 한다.

### 0.3 기술 스택 (확정)

| 영역 | 스택 |
|---|---|
| 백엔드 | FastAPI + SQLModel + SQLite + BackgroundTasks |
| 프론트엔드 | Next.js 14 (App Router) + TypeScript + Tailwind CSS + shadcn/ui |
| DB | SQLite (로컬 파일) |
| 파일 저장 | 로컬 파일시스템 (shorts_factory의 `output/` 디렉토리 재사용) |
| 배포 | 로컬 실행 (`localhost`) |

### 0.4 MVP 범위 (포함 / 제외)

**포함**
- 11단계 UI 플로우 전체 구현 (아래 [섹션 2](#2-ui-플로우-11단계))
- 각 단계 산출물 브라우저 재생/검토
- 대본 variant 선택
- 영상 개별 재생성 (전체 재생성 + 개별 클립 재생성)
- CapCut 프로젝트 생성 및 다운로드
- 작업 이력 리스트 (홈페이지)
- 중단 후 재개 (현재 어느 스텝인지 DB에 저장)

**제외 (Phase 2로 이관)**
- 대본 직접 편집 후 재생성
- 영상 프롬프트 편집
- 통합 타임라인 프리뷰 (ffmpeg 합성)
- CapCut 템플릿 3종 (MVP는 1종만)
- 상품 URL 자동 파싱
- 사용자 인증 / 멀티유저
- 실시간 SSE (MVP는 폴링으로)

---

## 1. 프로젝트 구조

### 1.1 디렉토리 배치

`shorts_factory/` 저장소 안에 `web/` 폴더로 추가. 기존 파일 수정 최소화.

```
shorts_factory/                          # 기존
├── pipeline.py                          # 기존 (수정 없음)
├── agents/                              # 기존 (수정 없음)
├── core/                                # 기존 (수정 없음)
├── scripts/                             # 기존 (수정 없음)
├── output/                              # 기존 (웹에서 파일 서빙 대상)
├── .env                                 # 기존 (백엔드도 같은 환경변수 사용)
├── config.yaml                          # 기존
│
└── web/                                 # 🆕 신규
    ├── backend/
    │   ├── main.py                      # FastAPI 엔트리포인트
    │   ├── db.py                        # SQLModel 정의
    │   ├── schemas.py                   # Pydantic 요청/응답 스키마
    │   ├── routes/
    │   │   ├── __init__.py
    │   │   ├── tasks.py                 # 작업 CRUD
    │   │   ├── pipeline.py              # 단계별 실행 엔드포인트
    │   │   └── files.py                 # 파일 서빙 (이미지/오디오/영상)
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── pipeline_runner.py       # 기존 agents 개별 호출 래퍼
    │   │   └── file_manager.py          # 업로드/출력 경로 관리
    │   ├── requirements.txt
    │   └── .gitignore
    │
    └── frontend/
        ├── app/
        │   ├── layout.tsx               # 루트 레이아웃
        │   ├── page.tsx                 # 홈 (페이지 0)
        │   ├── new/page.tsx             # 새 작업 시작 (페이지 1)
        │   └── tasks/[id]/
        │       ├── page.tsx             # 작업 상세 (라우터)
        │       └── components/
        │           ├── Step2ScriptLoading.tsx
        │           ├── Step3ScriptSelect.tsx
        │           ├── Step4TtsLoading.tsx
        │           ├── Step5TtsReview.tsx
        │           ├── Step6PromptReview.tsx
        │           ├── Step7VideoLoading.tsx
        │           ├── Step8ClipSelect.tsx
        │           ├── Step9TimelinePreview.tsx
        │           ├── Step10TemplateSelect.tsx
        │           └── Step11Complete.tsx
        ├── components/
        │   ├── ui/                      # shadcn/ui 컴포넌트
        │   ├── ImageUploader.tsx
        │   ├── AudioPlayer.tsx
        │   ├── VideoPlayer.tsx
        │   └── ProgressIndicator.tsx
        ├── lib/
        │   ├── api.ts                   # fetch 래퍼
        │   └── types.ts                 # TypeScript 타입 정의 (백엔드 스키마 거울)
        ├── package.json
        ├── tsconfig.json
        ├── tailwind.config.ts
        └── .env.local
```

### 1.2 주요 `.gitignore` 항목 (web/.gitignore)

```
backend/tasks.db
backend/uploads/
backend/__pycache__/
backend/venv/
frontend/node_modules/
frontend/.next/
frontend/out/
frontend/.env.local
```

### 1.3 실행 방법

**개발 시 두 개 터미널**:

```bash
# Terminal 1: 백엔드
cd shorts_factory/web/backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2: 프론트엔드
cd shorts_factory/web/frontend
npm install
npm run dev
```

접속: `http://localhost:3000` (프론트엔드)  
API: `http://localhost:8000/docs` (FastAPI 자동 생성 Swagger)

---

## 2. UI 플로우 (11단계)

### 2.1 전체 흐름 다이어그램

```
[페이지 0: 홈]
   │
   ├─ 새 작업 ───────────> [페이지 1: 상품 입력]
   │                          │
   │                          ▼ (다음 누르면 백엔드 트리거)
   │                       [페이지 2: 대본 생성 중]
   │                          │ 자동 폴링
   │                          ▼
   │                       [페이지 3: 대본 선택/재생성]
   │                          │ 선택 확정
   │                          ▼
   │                       [페이지 4: TTS 생성 중]
   │                          │
   │                          ▼
   │                       [페이지 5: TTS 검수/재생성]
   │                          │
   │                          ▼
   │                       [페이지 6: 영상 프롬프트 확인]
   │                          │ 비용/시간 경고 후 확인
   │                          ▼
   │                       [페이지 7: 영상 생성 중]
   │                          │ (긴 작업, 홈으로 나갈 수 있음)
   │                          ▼
   │                       [페이지 8: 클립 선택/재생성]
   │                          │
   │                          ▼
   │                       [페이지 9: 타임라인 프리뷰]
   │                          │
   │                          ▼
   │                       [페이지 10: CapCut 템플릿 선택]
   │                          │
   │                          ▼
   │                       [페이지 11: 완료/다운로드]
   │
   └─ 기존 작업 이어하기 ──> [페이지 2~11 중 해당 스텝으로 점프]
```

### 2.2 단계별 상세 명세

#### **페이지 0: 홈 (`/`)**

**URL**: `GET /`

**역할**: 작업 이력 리스트. 새 작업 시작 or 기존 작업 이어하기.

**표시 요소**:
- 상단: "shorts_factory" 로고 + `[+ 새 작업]` 버튼 (→ `/new`)
- 진행 중 섹션: `status in ("pending", "running")` 또는 `status == "awaiting_user"` 인 Task 리스트
  - 각 항목: 상품명, 생성일시, 현재 스텝(current_step), `[이어하기 →]` 버튼 (→ `/tasks/{id}`)
- 완료 섹션: `status == "completed"` Task 리스트
  - 각 항목: 상품명, 생성일시, 완료 스탬프, `[열기 →]` 버튼 (→ `/tasks/{id}`)
- 실패 섹션 (접혀있음, 기본): `status == "failed"` Task 리스트
  - 각 항목: 에러 메시지 요약, `[재시도]` 버튼

**API 호출**:
- `GET /api/tasks` — 전체 이력

---

#### **페이지 1: 상품 입력 (`/new`)**

**URL**: `GET /new`

**역할**: 새 작업 생성. 폼 제출 시 백엔드가 `product_analyzer → pd_strategist → hook_writer → scriptwriter → script_reviewer`까지 연속 실행.

**폼 필드**:
| 필드 | 타입 | 필수 | 비고 |
|---|---|---|---|
| product_name | string | ✅ | 상품명 |
| price_info | string | ❌ | 최종 가격/쿠폰 정보 |
| detail_text | textarea | ❌ | 상세 설명 |
| seller_memo | textarea | ❌ | 판매자 메모 |
| images | file[] | ✅ | 3~5장, jpg/png/webp, 각 최대 10MB |
| campaign_variant | radio | ❌ | "family_month" / "children_day" / "parents_day" / "fast_delivery" / "none" |
| landing_url | string | ❌ | 캠페인 랜딩 URL |
| coupon_info | string | ❌ | 캠페인 쿠폰 정보 |

**이미지 업로드**:
- 드래그앤드롭 또는 클릭
- 업로드된 이미지 썸네일 리스트 표시, 순서 변경 가능 (드래그)
- 각 썸네일 아래 자동 라벨 `img_1`, `img_2`, ... 표시 (pipeline 내부 ID와 동일)

**제출 액션**:
1. `POST /api/tasks` (multipart/form-data) 호출
2. 응답으로 `task_id` 받음
3. `/tasks/{task_id}` 로 리다이렉트

---

#### **페이지 2: 대본 생성 중 (`/tasks/{id}`, step=generating_script)**

**역할**: 백엔드 ①②③④⑤ 실행 상태 폴링 표시.

**표시 요소**:
- 스텝 인디케이터: ○●○○○○○○○○ (2/10)
- 현재 에이전트 진행 상태:
  ```
  ✅ 상품 분석 완료          (28초)
  ✅ 전략 수립 완료          (61초)
  ⏳ 훅 작성 중...           경과 12초
  ⏸  대본 작성
  ⏸  대본 검수
  ```
- 예상 남은 시간 (hardcode: 각 단계 평균값으로 추정)

**동작**:
- 2초마다 `GET /api/tasks/{id}` 폴링
- `status == "awaiting_user"` AND `current_step == "select_scripts"` 되면 → 페이지 3으로 자동 전환
- `status == "failed"` 되면 → 에러 메시지 표시 + 재시도 버튼

---

#### **페이지 3: 대본 선택 / 재생성 (`/tasks/{id}`, step=select_scripts)** ⭐

**역할**: 생성된 5개 variant 중 다음 단계로 진행할 것 선택. 개별 재생성 가능.

**표시 요소**:
- 각 variant 카드 (접기/펼치기 가능):
  - 헤더: `☐ v1. 정보형(informative)  ⭐9/10  [🔄 재생성]`
  - 펼치면:
    - 훅 텍스트
    - 풀 대본 (100자 이내)
    - 제목 + 해시태그
    - 클립 배정 (변환될 이미지 썸네일 + 간단 설명)
    - 검수 통과 여부 + 점수
- 상단: `[☑ 전체] [☐ 해제] 선택: N/5개`
- 하단: `[← 이전]` `[선택한 N개로 TTS 생성 →]` (N>=1일 때만 활성)

**재생성 모달**:
- `[🔄 재생성]` 클릭 시 모달 팝업
- 필드: "재생성 방향 (선택)" textarea
- 버튼: `[취소] [재생성]`
- `POST /api/tasks/{id}/regenerate-script` 호출 (variant_id 지정)
- 재생성 중에는 해당 variant 카드만 로딩 오버레이
- 재생성 완료되면 해당 카드만 갱신

**"TTS 생성" 액션**:
- `POST /api/tasks/{id}/next` (body: `{selected_variant_ids: ["v1", "v3"]}`)
- 백엔드가 선택된 variant만 `scripts_final.json`으로 확정 후 TTS 스텝 진행
- 페이지 4로 이동

---

#### **페이지 4: TTS 생성 중**

**페이지 2와 동일한 패턴**. ⑥ tts_generator만 돌아감. variant 수만큼 순차 실행.

완료되면 `current_step == "review_tts"`로 전환, 페이지 5로.

---

#### **페이지 5: TTS 검수 / 재생성** ⭐

**역할**: 선택된 variant들의 TTS 결과 재생해서 확인. 필요 시 재생성.

**표시 요소**:
- 각 variant 카드:
  - 헤더: "v1. 정보형"
  - 대본 텍스트 (읽기 전용, MVP)
  - 오디오 플레이어 (HTML5 `<audio>`, `GET /api/tasks/{id}/audio/{variant_id}` 스트리밍)
  - 재생/일시정지/시크바/볼륨
  - `[🔄 재생성]` 버튼
- 하단: `[← 이전]` `[영상 프롬프트 확인 →]`

**재생성 액션**:
- `POST /api/tasks/{id}/regenerate-tts` (body: `{variant_id: "v1"}`)
- 해당 variant만 재생성

**MVP 제외**:
- 대본 편집 기능 (Phase 2)
- 엔진/음성 변경 (Phase 2, config.yaml 고정 사용)

---

#### **페이지 6: 영상 프롬프트 확인**

**역할**: Veo 호출 전 prompt/이미지 매칭 확인. 비용/시간 경고 후 진행.

**표시 요소**:
- 상단 경고 박스:
  ```
  ⚠️ 영상 생성은 클립 1개당 약 60~120초 소요됩니다.
  ⚠️ Veo 크레딧 ~$N.NN 차감 예상 (클립 N개 기준)
  ⚠️ 총 예상 소요 시간: 약 10분
  ```
- 각 variant별로 클립 리스트:
  ```
  v1. 정보형 (3개 클립)
  ├── Clip 1: 인트로 · img_1 사용
  │   [썸네일] Prompt: slow zoom in on ...
  ├── Clip 2: 중간 · img_2 사용
  │   [썸네일] Prompt: hand typing on ...
  └── Clip 3: 마무리 · img_3 사용
      [썸네일] Prompt: aesthetic desk setup ...
  ```
- 중복 조합 표시: `(source_image=img_1, prompt="...")` 중복 시 "재사용됨" 뱃지
- 하단: `[← 이전]` `[Veo로 영상 생성 시작 →]`

**MVP에서 빠지는 것**: 프롬프트 직접 편집. 표시만.

**액션**:
- `POST /api/tasks/{id}/next` 호출 → 영상 생성 스텝 진행

---

#### **페이지 7: 영상 생성 중** (긴 로딩)

**페이지 2/4와 유사하지만 훨씬 긴 시간 (5~15분)**.

**특이 요소**:
- 진행률 바: `2 / 7 클립` 형태
- 클립별 상태 리스트:
  ```
  ✅ Clip 1 (v1-intro)    완료  1m 23s
  ✅ Clip 2 (v1-middle)   완료  1m 48s
  ⏳ Clip 3 (v1-outro)    생성중 0m 42s
  ⏸  Clip 4 (v3-intro)
  ```
- **"백그라운드로 돌리고 홈으로 가기"** 버튼 (→ `/`)
  - 홈에서 해당 작업이 "진행 중" 섹션에 보이고, 돌아오면 그대로 이어짐
- 브라우저 Notification API 권한 요청 → 완료 시 푸시 (옵션)

---

#### **페이지 8: 클립 선택 / 개별 재생성** ⭐

**역할**: 생성된 클립들 검토. 마음에 안 드는 클립만 개별 재생성. variant별 최소 3클립 유지 조건.

**표시 요소**:
- variant별 그룹:
  ```
  v1. 정보형
  ┌───────┐ ┌───────┐ ┌───────┐
  │ Clip1 │ │ Clip2 │ │ Clip3 │
  │ [▶]   │ │ [▶]   │ │ [▶]   │
  │ ☑     │ │ ☑     │ │ ☐     │
  │ [🔄]  │ │ [🔄]  │ │ [🔄]  │
  └───────┘ └───────┘ └───────┘
  ```
- 각 클립 카드:
  - 작은 비디오 플레이어 (hover 시 재생)
  - 체크박스 (체크 해제하면 해당 variant 사용 불가 → variant별 최소 3개 체크 유지 검증)
  - 개별 재생성 버튼 `[🔄]`

**재생성 액션**:
- `POST /api/tasks/{id}/regenerate-clip` (body: `{variant_id: "v1", clip_num: 3}`)
- 같은 이미지+프롬프트로 재호출 (Veo는 시드가 다르면 결과 다름)

**액션**:
- `[타임라인 프리뷰 →]` → 페이지 9

---

#### **페이지 9: 타임라인 프리뷰**

**역할**: 각 variant의 클립 + TTS를 합친 "rough cut" 확인.

**MVP 단순 버전**:
- variant별로 클립 순차 재생 + TTS 오디오 동시 재생 (클라이언트 사이드 동기화)
- 각 클립 duration 6초 기준으로 `<video>` 태그 여러 개 나열
- HTML5 `<audio>` 와 `<video>` 동시 `play()` 호출

```
v1. 정보형 (미리보기)
┌─────────────────────────────────────┐
│  [클립 1 → 2 → 3 자동 순차 재생]    │
│  + TTS 오디오 동시 재생              │
└─────────────────────────────────────┘
```

**Phase 2로 연기**: ffmpeg 서버사이드 합성해서 단일 mp4 프리뷰 제공

**액션**:
- `[CapCut 템플릿 선택 →]` → 페이지 10

---

#### **페이지 10: CapCut 템플릿 선택**

**역할**: variant별로 CapCut 템플릿 지정.

**MVP 단순 버전**:
- 템플릿 1종만 존재 ("기본형"). 라디오 버튼 선택 UI는 만들되 옵션은 1개만.
- 향후 Phase 2에서 3종 추가 시 이 UI 그대로 확장.

**추가 요소 (캠페인 로고)**:
- 새 작업 시 입력한 `campaign_variant` 값이 표시됨 (변경 가능)
- `none` / `family_month` / `children_day` / `parents_day` / `fast_delivery` 선택 가능
- MVP에서는 **선택 UI만 구현**. 실제 로고 삽입은 Phase 2 (capcut_builder 확장 필요).

**액션**:
- `[🎬 CapCut 프로젝트 생성 →]` → `POST /api/tasks/{id}/build-capcut`
- 완료되면 페이지 11

---

#### **페이지 11: 완료 / 다운로드**

**표시 요소**:
- 성공 메시지 + 총 소요시간
- 생성된 CapCut 프로젝트 리스트 (variant별):
  - 파일명, 용량, 생성 시간
  - `[⬇️ 다운로드]` 버튼 (`GET /api/tasks/{id}/download/{variant_id}`)
  - `[📂 폴더 열기]` 버튼 (로컬 경로를 클립보드에 복사)
- 전체 output 폴더 경로 표시
- 다음 단계 안내 (ShortSync 배포 등)

---

## 3. 백엔드 API 명세

### 3.1 공통 규칙

- Base URL: `http://localhost:8000`
- 모든 응답 `Content-Type: application/json` (파일 다운로드 제외)
- 에러 응답 형식: `{"detail": "에러 메시지"}`
- 날짜/시간: ISO 8601 UTC

### 3.2 엔드포인트 목록

#### 작업 CRUD

**`POST /api/tasks`** — 새 작업 생성 + 대본 생성 자동 트리거

- Request: `multipart/form-data`
  - `product_name`: string (required)
  - `price_info`: string (optional)
  - `detail_text`: string (optional)
  - `seller_memo`: string (optional)
  - `campaign_variant`: string (optional, enum: `none|family_month|children_day|parents_day|fast_delivery`)
  - `landing_url`: string (optional)
  - `coupon_info`: string (optional)
  - `images`: file[] (required, 3~5개)
- Response: `{"task_id": int, "status": "pending"}`
- 동작:
  1. 이미지들을 `web/backend/uploads/{task_id}_{idx}_{filename}`로 저장
  2. Task DB 레코드 생성 (status=pending, current_step=generating_script)
  3. BackgroundTasks에 `run_script_generation(task_id)` 예약
  4. 즉시 응답 반환

**`GET /api/tasks`** — 전체 작업 리스트

- Response:
  ```json
  {
    "tasks": [
      {
        "id": 1,
        "product_name": "AULA F99",
        "status": "awaiting_user",
        "current_step": "select_scripts",
        "created_at": "2026-04-20T10:23:00Z",
        "completed_at": null
      }
    ]
  }
  ```

**`GET /api/tasks/{id}`** — 단일 작업 상태

- Response:
  ```json
  {
    "id": 1,
    "product_name": "AULA F99",
    "status": "awaiting_user",
    "current_step": "select_scripts",
    "sub_progress": {
      "current": 2,
      "total": 5,
      "agent": "scriptwriter",
      "elapsed_sec": 78
    },
    "created_at": "...",
    "output_dir": "./output/AULA F99",
    "error": null,
    "artifacts": {
      "product_profile": true,
      "strategy": true,
      "scripts_final": false,
      "audio": false,
      "clips": false,
      "capcut_drafts": false
    }
  }
  ```

**`GET /api/tasks/{id}/artifact/{name}`** — 중간 산출물 JSON 조회

- `name`: `product_profile | strategy | hooks | scripts | scripts_final`
- Response: 해당 JSON 파일 내용 그대로

---

#### 단계 진행 제어

**`POST /api/tasks/{id}/next`** — 다음 단계로 진행

- Body (스텝별 다름):
  ```json
  // select_scripts 완료 시
  {
    "step": "select_scripts",
    "selected_variant_ids": ["v1_informative", "v3_scenario"]
  }
  
  // review_tts 완료 시
  { "step": "review_tts" }
  
  // review_prompts 완료 시
  { "step": "review_prompts" }
  
  // select_clips 완료 시
  {
    "step": "select_clips",
    "selected_clips": {
      "v1_informative": [1, 2, 3],
      "v3_scenario": [1, 2, 4]
    }
  }
  ```
- Response: `{"task_id": int, "next_step": "..."}`
- 동작: Task 상태 업데이트 + 다음 에이전트 실행 BackgroundTask 예약

**`POST /api/tasks/{id}/regenerate-script`** — 대본 개별 재생성

- Body:
  ```json
  {
    "variant_id": "v1_informative",
    "direction": "더 캐주얼한 톤으로" // optional
  }
  ```
- Response: `{"task_id": int, "variant_id": "...", "status": "regenerating"}`
- 동작: 해당 variant만 hook_writer + scriptwriter 다시 호출. 완료 후 strategy.json + scripts_final.json 업데이트.

**`POST /api/tasks/{id}/regenerate-tts`** — TTS 개별 재생성

- Body: `{"variant_id": "v1_informative"}`

**`POST /api/tasks/{id}/regenerate-clip`** — 클립 개별 재생성

- Body:
  ```json
  {
    "variant_id": "v1_informative",
    "clip_num": 3
  }
  ```

**`POST /api/tasks/{id}/build-capcut`** — 최종 CapCut 프로젝트 생성

- Body:
  ```json
  {
    "template_assignments": {
      "v1_informative": "default",
      "v3_scenario": "default"
    },
    "campaign_variant": "family_month"
  }
  ```
- Response: `{"task_id": int, "status": "building"}`
- 동작: `capcut_builder.run(...)` 호출. 완료 시 status=completed.

---

#### 파일 서빙

**`GET /api/tasks/{id}/image/{filename}`** — 업로드된 이미지 반환

**`GET /api/tasks/{id}/audio/{variant_id}`** — TTS mp3 스트리밍

**`GET /api/tasks/{id}/clip/{variant_id}/{clip_num}`** — 영상 클립 스트리밍 (mp4)

**`GET /api/tasks/{id}/download/{variant_id}`** — CapCut 프로젝트 zip 다운로드

---

### 3.3 에이전트 실행 래핑 (핵심)

기존 `pipeline.py::run()`은 end-to-end. Web UI는 스텝별 분리 실행이 필요. 따라서 **`web/backend/services/pipeline_runner.py`에 래퍼 함수들**을 만든다:

```python
# web/backend/services/pipeline_runner.py

def run_script_generation(task_id: int) -> None:
    """①②③④⑤ 순차 실행. 완료 후 status=awaiting_user, current_step=select_scripts."""

def run_tts_generation(task_id: int, selected_variant_ids: list[str]) -> None:
    """⑥ tts_generator 실행. scripts_final.json을 selected만 필터링 후 실행."""

def run_video_generation(task_id: int) -> None:
    """⑦ video_generator 실행."""

def run_capcut_build(task_id: int, template_assignments: dict, campaign_variant: str) -> None:
    """⑧ capcut_builder 실행."""

def regenerate_script_variant(task_id: int, variant_id: str, direction: str | None) -> None:
    """특정 variant만 hook_writer + scriptwriter 재실행."""

def regenerate_tts_variant(task_id: int, variant_id: str) -> None:

def regenerate_clip(task_id: int, variant_id: str, clip_num: int) -> None:
```

**중요**: 기존 `pipeline.py`와 `agents/` 코드는 **수정하지 않고** import해서 쓴다. checkpoint 시스템(`core/checkpoint.py::load_or_run`)이 이미 있어서 중간 파일이 존재하면 스킵하므로, 스텝별 실행에 그대로 재활용 가능.

**예외 처리**:
- 모든 래퍼는 try/except로 감싸고, 실패 시 Task.status="failed", Task.error=str(e)로 DB 업데이트
- Task.status는 항상 각 단계 시작/종료 시 업데이트

---

## 4. 데이터 모델 (SQLModel)

### 4.1 Task 테이블

```python
# web/backend/db.py

from sqlmodel import Field, SQLModel, create_engine
from datetime import datetime
from enum import Enum
import json

class TaskStatus(str, Enum):
    pending = "pending"              # 생성 직후, 아직 실행 안 됨
    running = "running"              # 에이전트 실행 중
    awaiting_user = "awaiting_user"  # 사용자 입력/선택 대기
    completed = "completed"          # 전체 완료
    failed = "failed"                # 에러로 중단

class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_name: str
    price_info: str | None = None
    detail_text: str | None = None
    seller_memo: str | None = None
    
    # JSON string으로 저장
    images: str                      # ["uploads/1_0_img1.jpg", ...]
    
    # 캠페인
    campaign_variant: str | None = None  # none|family_month|children_day|...
    landing_url: str | None = None
    coupon_info: str | None = None
    
    # 진행 상태
    status: TaskStatus = TaskStatus.pending
    current_step: str | None = None  # generating_script | select_scripts | generating_tts | review_tts | review_prompts | generating_video | select_clips | preview_timeline | select_template | building_capcut
    sub_agent: str | None = None     # 현재 돌아가는 에이전트명 (진행 중일 때)
    sub_started_at: datetime | None = None  # 현재 서브 작업 시작 시간 (경과 계산용)
    
    # 사용자 선택 (JSON)
    selected_variant_ids: str | None = None    # ["v1_informative", "v3_scenario"]
    selected_clips: str | None = None          # {"v1_informative": [1,2,3], ...}
    template_assignments: str | None = None    # {"v1_informative": "default", ...}
    
    # 경로
    output_dir: str | None = None    # "./output/{product_name}"
    
    # 에러
    error: str | None = None
    
    # 타임스탬프
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

engine = create_engine("sqlite:///./tasks.db")
SQLModel.metadata.create_all(engine)
```

### 4.2 상태 전이 규칙

```
[pending]
   │ BackgroundTask 시작
   ▼
[running, sub_agent=product_analyzer]
   │ 각 에이전트 순차 실행
   ▼
[running, sub_agent=script_reviewer]
   │ ⑤ 완료
   ▼
[awaiting_user, current_step=select_scripts]
   │ POST /next (selected_variant_ids)
   ▼
[running, sub_agent=tts_generator]
   │
   ▼
[awaiting_user, current_step=review_tts]
   │ POST /next
   ▼
[awaiting_user, current_step=review_prompts]
   │ POST /next
   ▼
[running, sub_agent=video_generator]
   │
   ▼
[awaiting_user, current_step=select_clips]
   │ POST /next (selected_clips)
   ▼
[awaiting_user, current_step=preview_timeline]
   │ POST /next
   ▼
[awaiting_user, current_step=select_template]
   │ POST /build-capcut
   ▼
[running, sub_agent=capcut_builder]
   │
   ▼
[completed]
```

실패 시 어느 단계에서든 `[failed]`로. 재시도는 `current_step`부터 다시 시작.

---

## 5. 프론트엔드 핵심 구현 가이드

### 5.1 API 클라이언트 (`lib/api.ts`)

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type TaskStatus = "pending" | "running" | "awaiting_user" | "completed" | "failed";

export interface Task {
  id: number;
  product_name: string;
  status: TaskStatus;
  current_step: string | null;
  sub_progress?: {
    current: number;
    total: number;
    agent: string;
    elapsed_sec: number;
  };
  created_at: string;
  completed_at: string | null;
  error: string | null;
  artifacts: Record<string, boolean>;
}

export async function listTasks(): Promise<{ tasks: Task[] }> {
  return fetch(`${API_BASE}/api/tasks`).then(r => r.json());
}

export async function getTask(id: number): Promise<Task> {
  return fetch(`${API_BASE}/api/tasks/${id}`).then(r => r.json());
}

export async function createTask(formData: FormData): Promise<{ task_id: number }> {
  return fetch(`${API_BASE}/api/tasks`, {
    method: "POST",
    body: formData,
  }).then(r => r.json());
}

export async function nextStep(id: number, body: Record<string, any>) {
  return fetch(`${API_BASE}/api/tasks/${id}/next`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => r.json());
}

export async function regenerateScript(id: number, variantId: string, direction?: string) {
  return fetch(`${API_BASE}/api/tasks/${id}/regenerate-script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variant_id: variantId, direction }),
  }).then(r => r.json());
}

// ... 나머지 regenerate* 함수 동일 패턴
```

### 5.2 폴링 훅 (`hooks/useTaskPolling.ts`)

```typescript
import { useEffect, useState } from "react";
import { getTask, Task } from "@/lib/api";

export function useTaskPolling(taskId: number, intervalMs = 2000) {
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    
    async function tick() {
      try {
        const data = await getTask(taskId);
        if (!active) return;
        setTask(data);
        // 진행 중이거나 대기 상태면 계속 폴링
        if (data.status === "running" || data.status === "pending") {
          timer = setTimeout(tick, intervalMs);
        }
        // awaiting_user, completed, failed는 폴링 중단
      } catch (e) {
        if (active) setError(String(e));
      }
    }
    
    tick();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [taskId, intervalMs]);
  
  return { task, error };
}
```

### 5.3 페이지 라우팅 전략

`/tasks/[id]/page.tsx`에서 `task.current_step`에 따라 동적으로 해당 Step 컴포넌트 렌더링:

```tsx
// app/tasks/[id]/page.tsx
"use client";

import { useTaskPolling } from "@/hooks/useTaskPolling";
import Step2ScriptLoading from "./components/Step2ScriptLoading";
import Step3ScriptSelect from "./components/Step3ScriptSelect";
// ... 나머지 import

export default function TaskPage({ params }: { params: { id: string } }) {
  const taskId = parseInt(params.id);
  const { task, error } = useTaskPolling(taskId);
  
  if (error) return <ErrorView message={error} />;
  if (!task) return <LoadingSpinner />;
  
  if (task.status === "failed") return <FailedView task={task} />;
  if (task.status === "completed") return <Step11Complete task={task} />;
  
  // current_step에 따라 분기
  switch (task.current_step) {
    case "generating_script":
      return <Step2ScriptLoading task={task} />;
    case "select_scripts":
      return <Step3ScriptSelect task={task} />;
    case "generating_tts":
      return <Step4TtsLoading task={task} />;
    case "review_tts":
      return <Step5TtsReview task={task} />;
    case "review_prompts":
      return <Step6PromptReview task={task} />;
    case "generating_video":
      return <Step7VideoLoading task={task} />;
    case "select_clips":
      return <Step8ClipSelect task={task} />;
    case "preview_timeline":
      return <Step9TimelinePreview task={task} />;
    case "select_template":
      return <Step10TemplateSelect task={task} />;
    case "building_capcut":
      return <Step4TtsLoading task={task} />;  // 로딩 UI 재활용
    default:
      return <UnknownStep task={task} />;
  }
}
```

---

## 6. 7일 개발 스케줄

### Day 1 (세팅 + 백엔드 스켈레톤)

- [ ] `web/` 폴더 생성, `.gitignore` 설정
- [ ] `web/backend/` FastAPI 프로젝트 초기화
  - `main.py` — FastAPI 앱, CORS 설정
  - `db.py` — SQLModel Task 정의
  - `requirements.txt`
  - `GET /api/health` 엔드포인트
- [ ] `web/frontend/` Next.js 초기화
  - `create-next-app` + TypeScript + Tailwind + App Router
  - shadcn/ui 설치
  - `lib/api.ts` 기본 fetch 래퍼
- [ ] 홈페이지 (`/`) 빈 레이아웃 + "새 작업" 버튼
- [ ] 프론트 → 백엔드 `/api/health` 호출 성공 확인

### Day 2 (백엔드: 작업 생성 + 파이프라인 실행)

- [ ] `routes/tasks.py`
  - `POST /api/tasks` — 멀티파트 업로드, 이미지 저장, DB 기록
  - `GET /api/tasks` — 리스트
  - `GET /api/tasks/{id}` — 단일 조회
- [ ] `services/pipeline_runner.py`
  - `run_script_generation(task_id)` — 기존 agents를 import해서 ①②③④⑤ 순차 호출
  - DB 상태 업데이트 (sub_agent, sub_started_at 등)
- [ ] BackgroundTasks로 백그라운드 실행 연결
- [ ] 수동 테스트: curl/Postman으로 POST → 작업 생성 → DB 확인 → `output/` 폴더에 중간 파일 생성 확인

### Day 3 (프론트: 페이지 0, 1, 2, 3)

- [ ] 페이지 0: 홈 - 작업 리스트 (진행 중 / 완료 / 실패 섹션)
- [ ] 페이지 1: `/new` - 상품 입력 폼 + 이미지 드래그앤드롭
- [ ] 페이지 2: `/tasks/[id]` (step=generating_script) - 진행 상태 폴링
- [ ] 페이지 3: (step=select_scripts) - variant 카드 리스트 + 선택 UI
- [ ] **재생성 모달** 구현
- [ ] 페이지 0 → 1 → 2 → 3 플로우 수동 테스트

### Day 4 (백엔드: 나머지 엔드포인트 + 파일 서빙)

- [ ] `POST /api/tasks/{id}/next` — step별 분기 처리
- [ ] `POST /api/tasks/{id}/regenerate-script`
- [ ] `POST /api/tasks/{id}/regenerate-tts`
- [ ] `POST /api/tasks/{id}/regenerate-clip`
- [ ] `POST /api/tasks/{id}/build-capcut`
- [ ] `routes/files.py`
  - `GET /api/tasks/{id}/audio/{variant_id}` — mp3 스트리밍
  - `GET /api/tasks/{id}/clip/{variant_id}/{clip_num}` — mp4 스트리밍
  - `GET /api/tasks/{id}/download/{variant_id}` — zip 다운로드
- [ ] `GET /api/tasks/{id}/artifact/{name}` — JSON 산출물 조회

### Day 5 (프론트: 페이지 4~11 전부)

- [ ] 페이지 4~5: TTS 생성/검수 (AudioPlayer 컴포넌트)
- [ ] 페이지 6: 영상 프롬프트 확인 (정적 표시)
- [ ] 페이지 7: 영상 생성 중 ("백그라운드로 돌리기" 버튼)
- [ ] 페이지 8: 클립 선택 (VideoPlayer 컴포넌트, 체크박스)
- [ ] 페이지 9: 타임라인 프리뷰 (클립 + 오디오 동기 재생)
- [ ] 페이지 10: 템플릿 선택 (라디오 버튼, 옵션 1개)
- [ ] 페이지 11: 완료 + 다운로드

### Day 6 (통합 테스트 + 버그 수정)

- [ ] 상품 1개로 end-to-end 전체 플로우 수동 테스트
- [ ] 재생성 기능 동작 확인 (대본/TTS/클립 각각)
- [ ] 중단 후 재개 시나리오 테스트 (홈으로 나갔다가 돌아오기)
- [ ] 실패 시 에러 처리 확인 (에이전트 하나 일부러 fail시켜서)
- [ ] CapCut 데스크톱에서 최종 프로젝트 정상 열리는지 확인
- [ ] 발견된 버그 수정

### Day 7 (최종 점검 + 문서화)

- [ ] README 작성 (`web/README.md`)
  - 설치 방법
  - 실행 방법
  - 트러블슈팅
- [ ] 실사용 시나리오 3회 반복 테스트 (다른 상품 3개)
- [ ] Windows 재부팅 후 실행 가능한지 확인
- [ ] 4/20 프로모션 실전 투입 준비 완료

---

## 7. 구현 시 주의사항

### 7.1 기존 코드 수정 금지 원칙

- `pipeline.py`, `agents/*`, `core/*`, `scripts/*` — **일체 수정하지 않는다**
- 필요한 기능은 `web/backend/services/` 아래 래퍼 함수로 구현
- 공통 import path: `sys.path.insert(0, str(PROJECT_ROOT))` 패턴 사용

### 7.2 Windows 경로 처리

- shorts_factory는 Windows에서 개발됨 (README 기준)
- 파일 경로는 `pathlib.Path` 사용, 문자열 join 금지
- 한글 상품명 폴더 생성 시 인코딩 문제 주의 (이미 `pipeline.py` 상단에 UTF-8 wrapper 있음)

### 7.3 BackgroundTasks 한계

FastAPI의 `BackgroundTasks`는 단일 프로세스 내에서만 동작. 서버 재시작하면 실행 중이던 작업 날아감. **MVP 범위에서는 OK** (Celery 도입은 Phase 3).

대신 DB에 `status=running`인 채로 남은 Task를 서버 시작 시 감지해서 `status=failed, error="서버 재시작으로 중단됨"`으로 마킹하는 로직 추가 권장.

### 7.4 이미지 / 오디오 / 영상 파일 경로

- 업로드된 이미지: `web/backend/uploads/{task_id}_{idx}_{filename}`
- pipeline이 생성하는 산출물: `shorts_factory/output/{product_name}/` (기존 그대로)
- 웹에서 서빙할 때는 `/api/tasks/{id}/...` 라우트 통해서만 노출 (직접 `/static/` 노출 금지)

### 7.5 CORS

개발 시 프론트 `:3000` → 백엔드 `:8000`이라 CORS 필요:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 7.6 에러 로깅

- 기존 `pipeline.py`의 logging 설정 그대로 활용
- 백엔드는 별도로 `web/backend/logs/web.log`에 기록
- 에러 발생 시 stack trace 전체를 Task.error에 저장하지 말고, 요약만 (전체는 로그 파일)

### 7.7 작업 디렉토리 충돌

동시에 같은 product_name으로 작업 생성하면 `output/{product_name}/` 충돌. 
- MVP: 같은 product_name이 이미 존재하면 작업 생성 시 409 에러 반환
- 또는 `output/{product_name}_{task_id}/` 형식으로 분리 (기존 pipeline 코드 수정 필요하므로 비추)

**권장**: 409 응답 + 프론트에서 "이미 존재합니다. 다른 이름 쓰시거나 기존 작업 여시겠습니까?" 안내

---

## 8. 이후 단계 (Phase 2, MVP 이후)

다음 기능들은 MVP 범위 밖. 실전 사용하며 우선순위 조정 예정.

- **프롬프트 편집 기능**: 페이지 6에서 i2v_prompt 직접 수정 + 반영
- **대본 직접 편집**: 페이지 5에서 대본 수정 후 TTS 재생성
- **CapCut 템플릿 3종**: 스펙강조형 / 감성형 / 비교형
- **PSD 로고 자동 오버레이**: capcut_builder 확장, 날짜 기반 로고 자동 선택
- **상품 URL 자동 파싱**: 스마트스토어/해외직구 URL → 상품정보 추출
- **ffmpeg 기반 통합 프리뷰**: 페이지 9 개선
- **WebSocket/SSE 실시간 로그**: 폴링 → 푸시
- **Celery + Redis**: BackgroundTasks → 분산 큐
- **Batch 처리**: 한 번에 여러 상품 업로드
- **YouTube/TikTok/Instagram 직접 업로드 연동**
- **성과 분석 연동**: Windsor.ai로 업로드 후 결과 추적

---

## 9. 체크리스트 요약

### 시작 전 확인
- [ ] `.env` 파일에 `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `CLAUDE_API_KEY` 존재
- [ ] 기존 `python pipeline.py --product "..." --images ...`가 정상 동작
- [ ] Node.js 18+ 설치
- [ ] Python 3.10+ 설치

### MVP 완료 기준
- [ ] 홈페이지에서 새 작업 생성 가능
- [ ] 이미지 3~5장 업로드 가능
- [ ] 대본 5개 variant 생성 후 선택 가능
- [ ] 선택한 variant에 대해서만 TTS 생성됨
- [ ] TTS 재생 가능
- [ ] 영상 생성 진행률 실시간 표시
- [ ] 영상 개별 클립 재생성 가능
- [ ] CapCut 프로젝트 다운로드 가능
- [ ] 중단 후 재개 가능 (홈 → 이어하기)
- [ ] 상품 3개 연속 처리 안정적으로 동작

---

## 부록 A. 참고 경로 레퍼런스

```python
# 기존 shorts_factory에서 재사용할 것들
from pipeline import run as run_full_pipeline  # 참고용, 실제로는 쓰지 않음
from core.checkpoint import load_or_run, save_json
from core.config import get_llm_config, get_tts_config, get_i2v_config
from agents import (
    product_analyzer,
    pd_strategist,
    hook_writer,
    scriptwriter,
    script_reviewer,
    tts_generator,
    video_generator,
    capcut_builder,
)
```

## 부록 B. variant_id 네이밍 규칙

pd_strategist가 생성하는 `variant_id` 형식:
- `v1_informative` — 정보/스펙 중심
- `v2_empathy` — 공감형
- `v3_scenario` — 상황극
- `v4_review` — 후기형
- `v5_comparison` — 비교형

이 ID는 strategy.json → scripts_final.json → audio/{variant_id}.mp3 → clips/{variant_id}_{clip_num}.mp4 → capcut_drafts/{variant_id}/ 모든 경로에서 동일하게 쓰임.

## 부록 C. campaign_variant 값 정의

| 값 | 의미 | 색상 | 기간 |
|---|---|---|---|
| `none` | 캠페인 미적용 | - | - |
| `family_month` | 가정의달+세일 | `#F23E7C` | 4.20.~5.8. |
| `children_day` | 어린이날+세일 | `#10BF55` | 4.20.~5.5. |
| `parents_day` | 어버이날+세일 | `#BD2664` | 5.8. |
| `fast_delivery` | 빠른배송+세일 | `#8B30FF` | 상시 |

MVP에서는 값만 DB에 저장. 실제 로고 삽입은 Phase 2.

---

*문서 버전: v1.0 / 최종 업데이트: 2026-04-17*  
*작성자: shorts_factory 프로젝트팀*
