# Sprint 5 완료 기록

> 기간: 2026-03-12 ~ 2026-03-19
> 기획서: [SPRINT5_PLAN.md](SPRINT5_PLAN.md)
> 배포: `aerial-survey-manager-20260319.tar.gz`

---

## 구현 항목 요약

| # | 항목 | 완료일 | 커밋 |
|---|------|--------|------|
| F2 | 로컬 경로 이미지 불러오기 | 03-12 | `82ef6de` |
| F3 | 업로드 완료 시 즉시 처리 예약 | 03-13 | `9e0ac75` |
| F5 | 도엽 단위 클립+머지 | 03-16 | `f3529da` |
| F6 | 내보내기 후 COG 삭제 옵션 | 03-13 | — |
| F7 | 베이스맵 on/off 토글 | 03-13 | `d81d6f5` |
| F8 | 처리화면 지도 자유 이동 + 복귀 버튼 | 03-13 | `248200e` |
| F9 | 처리화면 정보 통합, COG 삭제 UI 개선 | 03-16 | — |
| F10 | 안정성 개선, 처리 단계 표시, 단일 계정 전환 | 03-17 | `f5e4faa` |
| F11 | 썸네일 전용 워커 분리 + 속도 최적화 | 03-19 | — |

---

## F2. 로컬 경로 이미지 불러오기

HTTP 업로드 → 로컬 경로 등록 방식으로 변경. 폴더 경로 입력 시 DB에 경로만 등록하고 처리 시 symlink로 원본 참조.

**주요 변경:**
- `backend/app/api/v1/upload.py` — `POST /local-import` 엔드포인트 신설
- `backend/app/workers/tasks.py` — `_prepare_images()` 절대 경로 분기 추가
- `src/components/Upload/UploadWizard.jsx` — 경로 입력 UI로 변경

**추가 개선:**
- ServerFileBrowser 기반 파일 탐색 (내장 디스크 표시, Shift+클릭 선택 방지, EO 파일 선택 통합)
- `backend/app/api/v1/filesystem.py` — `/home` 루트 추가, EO 확장자 필터, `read-text` 엔드포인트
- worker-engine concurrency 4→1 (Metashape 단일 라이선스 제약)

---

## F3. 업로드 완료 시 즉시 처리 예약

"완료 후 처리" 옵션으로 즉시 처리 예약. 야간 무인 운영 지원.

**주요 변경:**
- `backend/app/api/v1/processing.py` — `/schedule`에서 이미지 전부 completed이면 즉시 queued 전환 + Celery 태스크 제출
- `src/components/Upload/UploadWizard.jsx` — Step 4 "완료 후 자동 처리" 체크박스
- `src/App.jsx` — `handleUploadComplete`에서 autoProcess 시 `/schedule` 호출

---

## F5. 도엽 단위 클립+머지

정사영상을 국가 표준 도엽(1:5,000 / 1:1,000) 단위로 클립/머지. 납품·검수용 도엽 단위 산출물 생성.

**주요 변경:**
- `backend/app/api/v1/sheets.py` — 도엽 조회/검색 API (bounds-only 메모리 캐시 + STRtree)
- `backend/app/api/v1/download.py` — 클립/머지 API (gdalwarp -te, 배치는 Celery 비동기)
- `src/components/Project/SheetGridOverlay.jsx` — 도엽 격자 오버레이, map.on('click') 선택
- `src/components/Dashboard/FootprintMap.jsx` — 도엽 토글 버튼, 플로팅 컨트롤 패널

**기술 결정:**
- 190MB GeoJSON 전체 로드 대신 bounds만 추출 (~14MB 메모리)
- Canvas 렌더러에서 Rectangle 클릭 미동작 → `map.on('click')` + bounds 판정으로 우회
- 줌 레벨 제한 (1:1000→줌14, 1:5000→줌12) + 백엔드 200개 제한으로 렌더링 성능 확보

---

## F6. 내보내기 후 COG 삭제 옵션

정사영상 내보내기 완료 후 COG 파일 삭제 여부 선택. 삭제 전 GDAL로 썸네일 자동 생성.

**주요 변경:**
- `backend/app/api/v1/projects.py` — `DELETE /projects/{id}/ortho/cog` (삭제 전 썸네일 PNG 생성)
- `backend/app/models/project.py` — `ortho_thumbnail_path` 컬럼 추가
- `src/components/Project/ExportDialog.jsx` — 다운로드 완료 후 COG 삭제 확인 다이얼로그

---

## F7. 베이스맵 on/off 토글

대시보드/처리화면에서 베이스맵 레이어 토글. 정사영상 위 베이스맵이 불필요할 때 끌 수 있음.

**주요 변경:**
- `src/components/Dashboard/FootprintMap.jsx` — showBasemap 상태, 플로팅 토글 버튼
- `src/components/Project/ProjectMap.jsx` — 동일 토글 (localStorage 동기화)
- `public/siqms_mark.png` — 로고 복구 (Docker 이미지에서 추출)

---

## F8. 처리화면 지도 자유 이동 + 복귀 버튼

지도 뷰포인트가 정사영상 바운더리에 고정되는 문제 해결. 자유 이동 + "원래 범위로" 버튼.

**주요 변경:**
- `src/components/Project/ProjectMap.jsx` — FitBounds projectId별 1회 제한, Crosshair 복귀 버튼

**원인:** `FitBounds` 컴포넌트가 project 객체 재생성 시마다 fitBounds 반복 실행

---

## F9. 처리화면 정보 통합, COG 삭제 UI 개선

싱글/더블클릭 뷰 통합, 원본 이미지 정보 제거, COG 삭제 UI 개선.

**주요 변경:**
- `src/App.jsx` — 싱글클릭도 InspectorPanel 표시
- `src/components/Project/InspectorPanel.jsx` — 원본 정보 제거, COG 삭제 버튼 배치
- `src/components/Project/ProjectMap.jsx` — COG 없으면 로딩 상태 미설정 (무한대기 해소)
- `src/components/Dashboard/DashboardView.jsx` — 지도 기본 높이 600px → 1000px

---

## F10. 안정성 개선 + 처리 단계 표시 + 단일 계정 전환

### F10-A: 인스펙터 레이아웃 개선 및 메타 정보 강화 (03-16)
- COG 썸네일 해상도 1024 → 4096px
- 저장용량: `du -sb` → DB `ortho_size` 합산 (빠르고 정확)
- "촬영일" → "처리완료일" 변경
- InspectorPanel 3칸 → 2칸 레이아웃
- 처리 모드 한글화 (Normal→정밀 처리, Fast→고속 처리 등)
- 프로젝트 생성일, 처리완료일, 처리 소요시간 추가

### F10-B: 안정성 개선 및 UX 정리 (03-17)
- 도엽 패널 머지 기능 제거
- 처리 중 단계별 진행 상태 표시 (Sidebar — 5초 polling)
- **Celery 이중 실행 버그 수정**: `visibility_timeout=604800`(7일), `worker_prefetch_multiplier=1`, `acks_late=True`, 멱등성 체크
- 단일 계정 운영 체제: 회원가입 제거, 관리 메뉴 제거, `/register` → 403
- LoginPage: "이메일" → "아이디"

---

## F11. 썸네일 전용 워커 분리 + 속도 최적화

처리 중에도 썸네일 생성이 블로킹되지 않도록 전용 워커 분리.

**주요 변경:**
- `backend/app/workers/tasks.py` — 썸네일 큐 `celery` → `thumbnail`, throttle/defer 로직 제거
- `docker-compose.yml` / `docker-compose.prod.yml` — `celery-worker-thumbnail` 서비스 추가
- `backend/app/api/v1/upload.py` — `GET /upload/images/{id}` 온디맨드 썸네일 엔드포인트
- `src/components/Project/ProjectMap.jsx` — EO 클릭 시 썸네일 트리거 + 3초 폴링 + 로딩 스피너

**성능:** PIL → GDAL 전환. 오버뷰 있음 0.1초, 없음 ~4-5초 (기존 22초 대비 4배 개선)
