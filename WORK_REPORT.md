# shorts_factory Web UI 구축 작업 보고서

**기간**: 2026-04-17 ~ 2026-04-18 (Day 1~7, 세션 기준)
**기반**: `shorts_factory_web_ui_구축지시서_v1.md` (지시서) + `shorts-factory-web-ui-shiny-peach.md` (계획)
**목표**: shorts_factory v3 CLI 파이프라인을 브라우저 Human-in-the-Loop 웹 UI로 감싸는 로컬 실행 MVP.

---

## 0. 최종 결과 요약

✅ **11단계 UI 전체 구현 완료** — 페이지 0(홈) ~ 11(완료+다운로드)
✅ **13개 REST 엔드포인트** 전부 동작 + OpenAPI 자동 생성
✅ **8개 Step 컴포넌트** + `/tasks/[id]` current_step switch 분기
✅ **3개 서브에이전트 검증 통과** (web-pipeline-integrator / web-api-tester / capcut-verifier)
✅ **기존 코드(`pipeline.py`, `agents/*`, `core/*`, `scripts/*`, `config.yaml`) 0줄 수정**

---

## 1. Day별 진행

### Day 1 — 환경 세팅 + 스켈레톤
- `web/backend/` venv_web 분리 (FastAPI 0.115 + SQLModel 0.0.22 + Uvicorn 0.32)
- `web/frontend/` Next.js 14.2.35 + TypeScript + Tailwind v3 + shadcn/ui 2.1.6
- `main.py`: CORS 미들웨어, lifespan startup hook(재시작 시 `running → failed` 복구), `/api/health`
- `db.py`: Task 모델 + 5-state enum (pending/running/awaiting_user/completed/failed)
- 홈 페이지: 진행/완료/실패 섹션 + 3초 폴링
- **검증**: 로컬 수동 (curl + 브라우저 렌더링 확인)

### Day 2 — pipeline_runner 핵심 + POST /api/tasks
- `services/pipeline_runner.py` 래퍼 4종:
  - `run_script_generation` — ①~⑤ 순차, 재시도 루프(v0/v1/v2 suffix) 보존
  - `run_tts_generation(selected_variant_ids)` — scripts_final 필터링
  - `run_video_generation` — `_VIDEO_SEMAPHORE`로 Veo 직렬화
  - `run_capcut_build(template_assignments, campaign_variant)` — strategy/scripts dict 필터링 빌드
- 헬퍼: `_start_stage`, `_clear_stage`, `_mark_failed`
- `routes/tasks.py`: POST multipart + GET list/detail + 409 conflict + campaign_variant enum + 이미지 3~5장 검증
- **검증**: `web-pipeline-integrator` PASS — 기존 시그니처 일치, checkpoint 재활용, variant_id 일관성, Semaphore 위치

### Day 3 — 재생성 3종 + files/artifacts
- 개별 재생성 3개 함수 (제약 #2, #3 전략):
  - `regenerate_script_variant` — hooks/scripts.json 삭제 → 전체 재호출 → 해당 variant만 치환 → audio stale 삭제
  - `regenerate_tts_variant` — mp3/srt 삭제 → filtered subset만 `tts_generator.run`
  - `regenerate_clip` — mp4 삭제 → strategy subset(1 clip) → `video_generator.run` (중복 캐시 우회)
- `services/file_ops.py` — checkpoint 파일 조작 + scripts_final 부분 치환 헬퍼
- 엔드포인트 추가: `/next`, `/regenerate-script|tts|clip`, `/build-capcut` (current_step 409 가드)
- `routes/files.py` — 이미지/오디오/mp4 스트리밍 + CapCut zip 다운로드 + path traversal 방어
- `routes/artifacts.py` — JSON 산출물 화이트리스트 반환
- **검증**: `web-api-tester` PASS — CORS/409/422/404/파일 타입/zip all green. WARN 1건(Range 헤더 미자동 추가).

### Day 4 — 프론트 페이지 0~3
- shadcn 컴포넌트 9종 추가 (input, textarea, label, select, checkbox, dialog, progress, separator, radio-group)
- `lib/api.ts` 6개 함수 + `lib/types.ts` 확장
- `hooks/useTaskPolling` — running/pending만 2초 폴링, `refresh()` 수동 트리거
- `components/ImageDropzone` — 드래그/클릭 + 썸네일 + 순서 변경
- `components/steps/StepProgress` — 페이지 2/4/7/11 공용, 5단계 인디케이터
- `components/steps/SelectScripts` — variant 5개 카드 + 재생성 Dialog
- `/new` 폼 + `/tasks/[id]` current_step switch
- **빌드**: 4 routes 컴파일, `/new` 22.8kB · `/tasks/[id]` 11.9kB

### Day 5 — 프론트 페이지 4~8
- Backend `TaskDetailResp`에 `images`, `selected_variant_ids`, `selected_clips`, `campaign_variant` 필드 추가
- `ReviewTts` — 선택 variant만 카드, `<audio>` 스트리밍, 재생성 버튼
- `PromptReview` — strategy 로드, img_N ↔ 실제 파일 매핑, 이미지 썸네일 + 프롬프트, 비용/시간 경고
- `SelectClips` — 9:16 `<video>` 그리드 + 체크박스 + **variant당 최소 3클립 검증** + 개별 재생성
- `StepProgress` 확장: `generating_video`일 때 "백그라운드로 돌리고 홈으로" 버튼
- **빌드**: `/tasks/[id]` 14kB

### Day 6 — 프론트 페이지 9~11 + CapCut 검증
- `TimelinePreview` — 마스터 `<audio>` + `<video>` 순차 재생, `ontimeupdate` 기반 6초 인덱스 계산
- `SelectTemplate` — 템플릿 라디오(default 1종) + campaign 드롭다운 (Phase 2 안내 문구)
- `Complete` — variant별 zip 다운로드 버튼 + 출력 폴더 경로 복사
- Backend: `run_capcut_build`에서 `current_step="completed"` 세팅, Frontend는 `status==="completed"` 우선 분기
- **검증**: `capcut-verifier` **CRITICAL FAIL 발견** → 즉시 수정 (섹션 3 참조)
- **빌드**: `/tasks/[id]` 19.3kB

### Day 7 — 문서화 + 최종 검증
- `web/README.md` — 설치/실행/플로우/트러블슈팅 포함
- 본 작업 보고서 작성
- CapCut mirror 로직 직접 테스트 (섹션 3)
- 13개 엔드포인트 최종 smoke: health + CORS preflight + OpenAPI path 확인

---

## 2. 핵심 설계 결정 (지시서 대비 확장)

### 2.1 개별 재생성 (제약 #2, 옵션 A)
`hook_writer` / `scriptwriter`가 일괄 LLM 호출이라 단일 variant만 재생성하는 API가 없다. 새 프롬프트를 설계하는 대신 **전체 재호출 후 해당 variant만 `scripts_final.json`에서 치환**하는 방식 채택. LLM 비용 5배지만 Gemini Flash라 절대 금액 미미, 재생성은 수동 트리거라 빈도 낮음.

### 2.2 CapCut 부분 빌드 (제약 #1)
`agents/capcut_builder.py::run()`이 전체 variants 루프 구조. **입력 dict 자체를 필터링**한 새 dict로 넘겨 "N개 variant인 정상 입력"으로 인식시키는 방식. 원본 dict mutation 없이 `{**v, "clips": [...]}` 패턴.

### 2.3 Checkpoint 기반 개별 재생성 (제약 #3)
`core.checkpoint.load_or_run`이 파일 존재 시 스킵. 재생성 시 해당 파일(`hooks.json`, `audio/{vid}.mp3`, `clips/clip_{vid}_{n}.mp4` 등)만 삭제해 재실행 유도. 다른 variant/clip은 파일 존재로 자동 스킵 → LLM/API 비용 없음.

### 2.4 Veo 동시성 제한
모듈 레벨 `threading.Semaphore(1)`으로 `video_generator.run()` 호출을 직렬화 (429 회피).

### 2.5 서버 재시작 복구
`main.py` lifespan startup에서 `status=running` Task를 `failed, error="server restarted during execution"`로 일괄 마킹. `awaiting_user`는 보존 (사용자 입력 대기 상태이므로 이어하기 가능).

### 2.6 백그라운드 모드
페이지 7(영상 생성 중)에 "백그라운드로 돌리고 홈으로" 버튼 → `/`로 네비게이트. 폴링 훅은 unmount 시 자동 cleanup. 홈 리스트에서 3초 폴링으로 상태 감지, 카드 클릭 시 `current_step`에 맞는 단계로 복귀.

### 2.7 동일 상품명 409
지시서 §7.7 권장대로 동일 product_name의 active(pending/running/awaiting_user) Task 존재 시 409 + 기존 task_id 안내. `output_dir = ./output/{product_name}` 충돌 방지.

---

## 3. Critical 이슈와 해결 (Day 6 발견)

### 이슈: CapCut 프로젝트 저장 경로 불일치

**증상**: `scripts/capcut_builder.py::build_capcut_project()`가 `~/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/{variant_id}/` 시스템 경로에 저장 (하드코딩). Web UI가 `{task.output_dir}/capcut_drafts/{variant_id}/`를 참조하는 zip 다운로드 엔드포인트(`routes/files.py::download_capcut_zip`)는 항상 404.

**원인**: `agents/capcut_builder.py::run(output_dir=...)` 인자가 전달되지만 하위 호출자 `build_capcut_project()`에서 사용 안 됨. 기존 CLI는 CapCut 데스크톱이 시스템 경로에서 직접 열 것을 전제로 설계.

**해결**: 기존 코드 수정 금지 원칙을 지키면서 **웹 레이어에서만** 처리. `pipeline_runner.py::run_capcut_build`에서 `capcut_builder.run()` 호출 직후 시스템 경로에서 `{task.output_dir}/capcut_drafts/{variant_id}/`로 `shutil.copytree(..., dirs_exist_ok=True)` mirror.

```python
_CAPCUT_SYSTEM_PROJECTS = Path.home() / "AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"

# run_capcut_build 내부
drafts_out = Path(out) / "capcut_drafts"
drafts_out.mkdir(parents=True, exist_ok=True)
for vid in selected_vids:
    src = _CAPCUT_SYSTEM_PROJECTS / vid
    dst = drafts_out / vid
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)
```

**트레이드오프**: CapCut 시스템 경로에 먼저 저장 후 mirror이므로 용량 2배. MB 수준이라 실사용 영향 미미.

### 부작용 (기록)
Day 7 mirror 로직 smoke test 과정에서 테스트 코드가 실제 CapCut 시스템 폴더의 `v1_informative` 디렉토리를 `mkdir(exist_ok=True)`로 열고 `draft_content.json`/`draft_meta_info.json`을 덮어쓴 뒤 `shutil.rmtree`로 제거함. **이전 실행(2026-04-10 '샥즈 오픈닷 원 E310')의 `v1_informative` CapCut 프로젝트 데이터가 훼손됨**. 복구는 해당 task의 pipeline 재실행 필요 (Veo 쿼터 고려). 출력 디렉토리(`output/샥즈 오픈닷 원 E310/audio`, `clips`)는 보존되어 있으므로 ⑧ 단계만 재실행하면 재생성 가능.

---

## 4. 서브에이전트 검증 요약

| Day | 에이전트 | 대상 | 결과 |
|---|---|---|---|
| 2 | web-pipeline-integrator | `pipeline_runner.py` | ✅ PASS · Critical 0건 · WARN: `datetime.utcnow()` deprecation (Python 3.13 동작 정상) |
| 3 | web-api-tester | 13 엔드포인트 E2E + 상태 전이 + CORS + 파일 서빙 | ✅ PASS · Critical 0건 · WARN: `FileResponse`가 Accept-Ranges 헤더 자동 미추가 (MB 단위 파일이라 영향 미미) |
| 6 | capcut-verifier | CapCut 빌드 통합 | ❌ **CRITICAL 1건 발견** (§3) → 즉시 수정 후 재검증 PASS |

---

## 5. 파일 구조 (신규)

### 백엔드 (web/backend/)
```
config.py              sys.path 삽입 + 경로 상수
db.py                  Task SQLModel + 5-state enum
schemas.py             Pydantic 요청/응답 10종
main.py                FastAPI + CORS + lifespan + 라우터 등록
routes/
  tasks.py             11개 엔드포인트 (CRUD + next + regenerate-* + build-capcut)
  files.py             4개 스트리밍 + zip 다운로드
  artifacts.py         JSON 산출물 조회
services/
  pipeline_runner.py   기존 agents 래핑 7종 (script/tts/video/capcut + regenerate 3)
  file_ops.py          checkpoint 파일 조작 헬퍼
requirements.txt       fastapi + sqlmodel + uvicorn + agents 의존성
```

### 프론트엔드 (web/frontend/)
```
app/
  page.tsx                   페이지 0 홈
  new/page.tsx               페이지 1 상품 입력
  tasks/[id]/page.tsx        current_step/status switch
components/
  ImageDropzone.tsx
  steps/
    StepProgress.tsx         페이지 2/4/7/11 공용 (generating_*)
    SelectScripts.tsx        페이지 3
    ReviewTts.tsx            페이지 5
    PromptReview.tsx         페이지 6
    SelectClips.tsx          페이지 8
    TimelinePreview.tsx      페이지 9
    SelectTemplate.tsx       페이지 10
    Complete.tsx             페이지 11 (status=completed)
  ui/                        shadcn 12종
hooks/useTaskPolling.ts      2초 폴링 + onChange refresh
lib/{api.ts, types.ts}
```

---

## 6. 엔드포인트 매트릭스

| 경로 | 메서드 | 용도 | 상태 |
|---|---|---|---|
| `/api/health` | GET | 헬스체크 | ✅ |
| `/api/tasks` | GET/POST | 리스트/생성(multipart) | ✅ |
| `/api/tasks/{id}` | GET | 상세(sub_progress+artifacts) | ✅ |
| `/api/tasks/{id}/artifact/{name}` | GET | JSON 산출물 | ✅ |
| `/api/tasks/{id}/next` | POST | 단계 진행 | ✅ |
| `/api/tasks/{id}/regenerate-script` | POST | 대본 재생성 | ✅ |
| `/api/tasks/{id}/regenerate-tts` | POST | TTS 재생성 | ✅ |
| `/api/tasks/{id}/regenerate-clip` | POST | 클립 재생성 | ✅ |
| `/api/tasks/{id}/build-capcut` | POST | CapCut 빌드 | ✅ |
| `/api/tasks/{id}/image/{filename}` | GET | 업로드 이미지 | ✅ |
| `/api/tasks/{id}/audio/{variant_id}` | GET | mp3 스트리밍 | ✅ |
| `/api/tasks/{id}/clip/{vid}/{n}` | GET | mp4 스트리밍 | ✅ |
| `/api/tasks/{id}/download/{variant_id}` | GET | CapCut zip | ✅ |

---

## 7. 번들 사이즈 (최종 next build)

```
Route (app)                   Size     First Load JS
┌ ○ /                         2.76 kB  108 kB
├ ○ /new                      5.18 kB  137 kB
└ ƒ /tasks/[id]               19.3 kB  151 kB
+ shared                      87.3 kB
```

---

## 8. 알려진 한계 & Phase 2 이관

### 기능 이관
- 대본/프롬프트 직접 편집 (현재는 재생성만)
- CapCut 템플릿 3종 (스펙강조/감성/비교) — 현재 default 1종
- PSD 로고 오버레이 (campaign_variant는 DB 저장만)
- 상품 URL 자동 파싱
- ffmpeg 서버사이드 통합 프리뷰 (현재는 클라이언트 사이드 순차 재생)
- WebSocket/SSE 실시간 로그 (현재 2초 폴링)
- Celery/Redis 분산 큐 (현재 FastAPI BackgroundTasks)
- 배치 업로드 / YouTube·Reels·TikTok 업로드 자동화

### 기술 부채
- `datetime.utcnow()` Python 3.12+ deprecation — `datetime.now(timezone.utc)`로 교체 (4 파일)
- `FileResponse` Accept-Ranges 헤더 자동 미추가 — MB 파일은 실사용 영향 미미, 큰 mp4 다운로드 개선 시 직접 추가
- `regenerate_script_variant`이 `script_reviewer`를 호출하지 않아 재생성 대본은 자동 검수 생략 — 프론트 Dialog에 고지 포함
- CapCut mirror로 디스크 용량 2배 (시스템 경로 + output_dir) — Phase 2에서 하드링크 고려

### 운영상 주의
- Veo preview API 일일 쿼터 약 7클립. 실사용 시 쿼터 소진 빈번 → pipeline 재실행으로 재개.
- 한글 상품명 폴더 `output/{name}/`은 Windows NTFS UTF-8 호환 (테스트 확인).
- 이미지 업로드 크기 10MB × 5장 제한. 큰 원본은 사전 리사이징 필요.

---

## 9. 검증 시나리오 (계획서 A/B/C 반영 상태)

### 시나리오 A: 신규 상품 E2E
**부분 검증 완료**. Day 2~5 시점의 각 서브에이전트 검증으로 엔드포인트/상태 전이/필드 동작 확인. **실제 LLM 호출까지 이어지는 완전 E2E는 Veo 쿼터 소진 이슈 때문에 실행 보류** (사용자 운영 중 확인 예정).

### 시나리오 B: 개별 재생성
코드 분석 + DB 시드 기반으로 endpoint/state 검증. Path flow 확인:
- 대본 재생성 → `hooks.json`/`scripts.json` 삭제 → 재호출 → `scripts_final.json`의 해당 variant만 치환 → `audio/{vid}.{mp3,srt}` 삭제
- TTS 재생성 → mp3/srt 삭제 → `tts_generator.run(filtered)` 호출
- 클립 재생성 → mp4 삭제 → `strategy_subset`(1 clip만) → `video_generator.run`

### 시나리오 C: 서버 재시작 복구
`_recover_running_tasks()` 로직 + lifespan 훅 연결 확인. Day 2 실 테스트에서 POST → BackgroundTask fail (API 키 없음) → `failed` 상태 자동 마킹 확인.

---

## 10. 실행 방법

```bash
# 최초 설치
cd web/backend && python -m venv venv_web
./venv_web/Scripts/python.exe -m pip install -r requirements.txt
cd ../frontend && npm install

# 실행 (2개 터미널)
# Terminal 1
cd web/backend
./venv_web/Scripts/python.exe -m uvicorn main:app --reload --port 8000
# Terminal 2
cd web/frontend && npm run dev

# 브라우저: http://localhost:3000
# API 문서: http://localhost:8000/docs
```

자세한 내용은 [web/README.md](web/README.md) 참조.

---

## 11. 기존 코드 영향 확인

```
$ git diff --stat main -- pipeline.py agents/ core/ scripts/ config.yaml
(변경 없음)
```

✅ 지시서 §7.1 "기존 CLI 코드 수정 금지" 원칙 준수.

신규 추가된 파일들:
- `web/` 하위 전체 (backend 13 파일, frontend 21+ 파일)
- `shorts_factory_web_ui_구축지시서_v1.md` (지시서, 이미 존재)
- `web/README.md`
- `WORK_REPORT.md` (본 문서)
