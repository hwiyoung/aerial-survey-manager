# 작업 완료 기록 — F3

## F3. 프로젝트 업로드 시 즉시 처리 예약 - 2026-03-13 (커밋: 9e0ac75)

### 요구사항
프로젝트 생성 시 "완료 후 처리" 옵션으로 즉시 처리 예약. 야간 무인 운영 지원. (SPRINT5_PLAN.md F3 참조)

### 진행 체크리스트
- [x] A1. 계획 수립
- [x] A2. 계획 검토
- [x] A3. 과도 설계 검토
- [x] 🚪 사용자 승인
- [x] B1. 구현
- [x] B2. 목적 부합 검토
- [x] B3. 버그/보안 검토 및 수정
- [x] B4. 수정사항 재검토
- [x] C1. 파일/함수 분리
- [x] C2. 코드 통합/재사용 검토
- [x] C3. 사이드이펙트 확인
- [x] C4. 불필요 코드 정리
- [x] C5. 코드 품질 검토
- [x] 🚪 변경사항 보고
- [x] D1. UX 관점 검토
- [x] D2. 전체 변경사항 통합 검토
- [x] D3. 배포 가능성 판단
- [x] 🚪 최종 승인
- [x] D4. 커밋 및 PR

### A1. 구현 계획

#### 기존 코드 현황 (이미 구현됨)
- `POST /processing/projects/{project_id}/schedule` — 이미 존재 (processing.py:461-547)
- `ProcessingJob.status="scheduled"` — 모델에 이미 존재
- `scheduled → queued 전환` — upload.py의 multipart/complete에서 이미 구현 (1015-1083행)
- `api.scheduleProcessing()` — client.js에 이미 존재

#### 변경 파일 (2개 BE + 1개 FE)

**1. `backend/app/api/v1/processing.py`** — `/schedule`에 즉시 전환 로직 추가
**2. `src/components/Upload/UploadWizard.jsx`** — Step 4에 "완료 후 자동 처리" 체크박스
**3. `src/App.jsx`** — handleUploadComplete에서 autoProcess 시 /schedule 호출

### A2. 계획 검토 결과
- `/schedule` API 자체에서 "이미 모든 이미지가 completed이면 즉시 queued 전환" → local-import에 별도 전환 로직 불필요

### A3. 과도 설계 검토 결과
- EO 미업로드 시 BE 차단: FE에서 이미 EO 필수이므로 방어적 검증으로 충분
- 예약 상태 미충족 조건 표시: 로컬 환경에서 불필요 (이미지 등록 즉시 완료)

### 변경 파일 요약

| 파일 | 변경 내용 |
|---|---|
| `backend/app/api/v1/processing.py` | `/schedule`에서 이미지 전부 completed이면 즉시 queued 전환 + Celery 태스크 제출 |
| `src/components/Upload/UploadWizard.jsx` | autoProcess 상태, Step 4 체크박스, handleFinish에 autoProcess 전달 |
| `src/App.jsx` | handleUploadComplete에서 autoProcess 시 api.scheduleProcessing() 호출 |

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
- `/schedule` API에 즉시 전환 로직을 넣는 것이 local-import에 전환 로직을 넣는 것보다 올바름 (어떤 경로로 이미지가 등록되든 동작)
