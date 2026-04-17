# shorts_factory v3 — Claude Code 프로젝트 규칙

## 프로젝트 개요
상품명 + 이미지 3~4장 → 소구별 대본 5개 자동 생성 → CapCut JSON 자동 편집 → 20~25초 세로형(9:16) 광고 숏폼 5개 변형 출력.
설계서: shorts_factory_v3_설계서_지시서.md 참조.

## 기술 스택
- Python 3.10+, google-genai (Gemini Pro/Flash + Veo), ElevenLabs (TTS)
- CapCut 데스크톱 (JSON 템플릿 치환 방식 렌더링)
- MoviePy + FFmpeg (폴백 합성용)

## 작업 규칙

### 서브에이전트 필수 사용
- 코드 작성 후 반드시 서브에이전트(Task)로 검증한다
- **검증 에이전트**: 작성된 코드를 실행, 에러 여부 + 출력 파일 존재 + 내용 정합성 확인, pass/fail 리포트
- **로그 에이전트**: 각 단계 완료 시 work_log.md에 아래 형식으로 누적 기록