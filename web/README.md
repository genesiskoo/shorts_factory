# shorts_factory Web UI

shorts_factory v3 파이프라인의 Human-in-the-Loop 웹 인터페이스. CLI로 돌리던 11단계를 브라우저에서 단계별 검수/재생성하며 실행한다.

## 구조

```
web/
├── backend/                 # FastAPI + SQLModel + SQLite
│   ├── main.py              # 엔트리 + CORS + lifespan hook
│   ├── db.py                # Task 모델
│   ├── schemas.py           # Pydantic 스키마
│   ├── config.py            # sys.path 삽입 + 경로 상수
│   ├── routes/              # tasks / artifacts / files 라우터
│   ├── services/
│   │   ├── pipeline_runner.py  # 기존 agents 래핑, 스텝별 실행
│   │   └── file_ops.py      # checkpoint 파일 조작
│   └── requirements.txt
└── frontend/                # Next.js 14 App Router + Tailwind + shadcn/ui
    ├── app/
    │   ├── page.tsx             # 페이지 0: 홈
    │   ├── new/page.tsx         # 페이지 1: 상품 입력
    │   └── tasks/[id]/page.tsx  # 페이지 2~11 current_step 분기
    ├── components/
    │   ├── steps/               # Step 컴포넌트 8종
    │   ├── ImageDropzone.tsx
    │   └── ui/                  # shadcn 컴포넌트
    ├── hooks/useTaskPolling.ts
    └── lib/{api.ts, types.ts}
```

## 사전 요구

- Python 3.10+ (개발은 3.13으로 진행)
- Node.js 18+ (개발은 22.17로 진행)
- 프로젝트 루트 `.env`에 `GEMINI_API_KEY`, `ELEVENLABS_API_KEY` 설정
- 기존 `pipeline.py`가 정상 동작하는 상태

## 설치 (최초 1회)

```bash
# 백엔드
cd web/backend
python -m venv venv_web
./venv_web/Scripts/python.exe -m pip install -r requirements.txt

# 프론트엔드
cd ../frontend
npm install
```

## 실행 (개발 모드)

**터미널 1 — 백엔드**:
```bash
cd web/backend
./venv_web/Scripts/python.exe -m uvicorn main:app --reload --port 8000
```

**터미널 2 — 프론트엔드**:
```bash
cd web/frontend
npm run dev
```

접속:
- 프론트: `http://localhost:3000`
- API 문서: `http://localhost:8000/docs`
- 헬스체크: `http://localhost:8000/api/health`

## 사용 플로우

1. 홈 `/` → `[+ 새 작업]`
2. `/new` 폼: 상품명 + 이미지 3~5장 + 캠페인 → 제출
3. **페이지 2~5 자동 진행** (대본 5 variant 생성 ~2~3분) → 검수 선택
4. TTS 생성 → 오디오 검수 / 재생성
5. 영상 프롬프트 확인 → Veo 클립 생성 (~5~15분, 백그라운드 가능)
6. 클립 선택 / 개별 재생성
7. 타임라인 프리뷰
8. CapCut 템플릿 + 캠페인 선택 → 빌드 → zip 다운로드
9. CapCut 데스크톱에서 열어 렌더링

## 핵심 설계 결정

### 1. 기존 코드 수정 금지
`pipeline.py`, `agents/*`, `core/*`, `scripts/*`, `config.yaml`은 **수정하지 않는다**. `web/backend/services/pipeline_runner.py`에서 `import`만 재사용. `sys.path` 설정은 `config.py`의 side-effect import로 처리.

### 2. checkpoint 재활용
`core.checkpoint.load_or_run(filepath, func, ...)`이 이미 파일 존재 시 스킵. 웹에서는 그대로 활용하고, 개별 재생성 시에만 해당 파일을 명시적으로 삭제해 재실행을 유도.

### 3. 개별 재생성 전략 (3종)
- **대본**: `hook_writer` + `scriptwriter` 전체 재호출 → 해당 variant만 `scripts_final.json`에서 치환 → TTS 파일 삭제
- **TTS**: `audio/{variant_id}.{mp3,srt}` 삭제 → `tts_generator.run(filtered)` 재호출
- **클립**: `clips/clip_{variant_id}_{n}.mp4` 삭제 → strategy subset(해당 1개 clip만)으로 `video_generator.run` 호출

### 4. CapCut 부분 빌드
`agents/capcut_builder.py`는 전체 variants 루프 구조. 래퍼에서 `strategy`/`scripts` dict를 선택된 variants/clips로 필터링한 새 dict로 넘겨 "variants가 N개인 정상 입력"으로 보이게 함.

### 5. 서버 재시작 복구
uvicorn 시작 시 `status=running`인 Task를 `failed, error="server restarted..."`로 마킹. `awaiting_user`는 보존.

### 6. 경로 규약
- 업로드: `web/backend/uploads/{task_id}_{idx}_{sanitized}.ext`
- 파이프라인 산출물: `{PROJECT_ROOT}/output/{product_name}/` (기존 그대로)
- 파일 서빙은 `/api/tasks/{id}/...` 라우트로만 노출 (직접 `/static/` 금지)

## API 개요

| Method | Path | 용도 |
|---|---|---|
| GET | `/api/health` | 헬스체크 |
| GET | `/api/tasks` | 전체 리스트 |
| POST | `/api/tasks` | 새 작업 생성 (multipart) |
| GET | `/api/tasks/{id}` | 상세 + sub_progress + artifacts |
| GET | `/api/tasks/{id}/artifact/{name}` | JSON 산출물 조회 |
| POST | `/api/tasks/{id}/next` | 다음 단계 진행 |
| POST | `/api/tasks/{id}/regenerate-script` | 대본 재생성 |
| POST | `/api/tasks/{id}/regenerate-tts` | TTS 재생성 |
| POST | `/api/tasks/{id}/regenerate-clip` | 클립 재생성 |
| POST | `/api/tasks/{id}/build-capcut` | CapCut 빌드 |
| GET | `/api/tasks/{id}/image/{filename}` | 업로드 이미지 |
| GET | `/api/tasks/{id}/audio/{variant_id}` | TTS mp3 |
| GET | `/api/tasks/{id}/clip/{variant_id}/{n}` | 영상 mp4 |
| GET | `/api/tasks/{id}/download/{variant_id}` | CapCut zip |

## MVP 제약

다음 기능은 Phase 2로 이관:
- 대본/프롬프트 직접 편집 후 재생성
- CapCut 템플릿 3종 (스펙강조/감성/비교)
- PSD 로고 오버레이 (campaign_variant 시각 반영)
- 상품 URL 자동 파싱
- ffmpeg 기반 통합 프리뷰 (MVP는 클라이언트 사이드 순차 재생)
- WebSocket/SSE 실시간 로그 (MVP는 2초 폴링)
- Celery/Redis (MVP는 FastAPI BackgroundTasks)
- 배치 업로드 / YouTube·Instagram 업로드 연동

## 트러블슈팅

**uvicorn 시작 실패 — 모듈 import 에러**
- `cd web/backend` 위치에서 실행. 다른 디렉토리에서는 `config.py`의 `PROJECT_ROOT` 계산 틀어짐.
- `venv_web` 활성화 확인. `agents/`, `core/`가 `sys.path`에 잡혀야 import 성공.

**Task가 무한 running**
- 백엔드 로그 확인: `web/backend/logs/web.log` + 프로젝트 루트 `logs/pipeline.log`
- LLM API 키 누락 또는 쿼터 소진 시 에이전트 예외 → `Task.error`에 요약 저장됨
- 서버 재시작 시 자동으로 `failed` 마킹 (`awaiting_user`는 보존)

**Veo 429 RESOURCE_EXHAUSTED**
- Veo preview API 일일 쿼터 약 7클립 제한. `video_generator.py`의 재시도(60/90/120초)도 실패 시 종료.
- 다음 날 재실행 시 checkpoint(`clips/*.mp4`)로 완료 분은 스킵, 실패 분만 재시도.

**동일 상품명 409 에러**
- `pending / running / awaiting_user` 상태의 Task 존재 시 발생. 원본 task를 완료/실패 처리 후 재시도 가능.
- 빠른 재실행이 필요하면 홈에서 이전 task를 `failed`로 만들거나 DB에서 삭제.

**CORS 에러 (브라우저)**
- 프론트는 `:3000`, 백엔드는 `:8000` 고정. 포트 바꿀 때 `web/backend/config.py::ALLOWED_CORS_ORIGINS` 업데이트.

**한글 상품명 / 파일명**
- 업로드 파일명은 sanitize(영숫자/언더스코어만) 후 저장. 원본은 표시용으로 DB에 남지 않음.
- 상품명은 그대로 `output/{product_name}/` 폴더로 사용. Windows NTFS UTF-8 호환.

## 현재 상태 (2026-04-18 Day 7 완료)

- ✅ 11단계 UI 전체 구현
- ✅ 대본/TTS/클립 개별 재생성
- ✅ CapCut 프로젝트 다운로드
- ✅ 서버 재시작 후 이어하기
- ✅ 서브에이전트 검증 (web-pipeline-integrator, web-api-tester, capcut-verifier) 통과
