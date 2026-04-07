# 실감정사영상 생성 플랫폼 — 기술 매뉴얼

> 버전: v1.0.9 (2026-03-20)
> 대상: 개발자, 유지보수 담당자

---

## 목차

1. [아키텍처 개요](#1-아키텍처-개요)
2. [프론트엔드 (React)](#2-프론트엔드)
3. [백엔드 (FastAPI)](#3-백엔드)
4. [처리 엔진 (Metashape)](#4-처리-엔진)
5. [인프라 (Docker)](#5-인프라)
6. [데이터 흐름](#6-데이터-흐름)

---

## 1. 아키텍처 개요

```
┌─────────────┐     ┌─────────┐     ┌──────────────┐
│  Frontend   │────▶│  Nginx  │────▶│  FastAPI (api)│
│  (React)    │     │ :8081   │     │  :8000       │
└─────────────┘     └─────────┘     └──────┬───────┘
                         │                  │
                    ┌────▼────┐       ┌─────▼──────┐
                    │ TiTiler │       │ PostgreSQL │
                    │ (COG)   │       │ + PostGIS  │
                    └─────────┘       └────────────┘
                                           │
                                     ┌─────▼──────┐
                                     │   Redis    │
                                     │ (Celery)   │
                                     └─────┬──────┘
                              ┌────────────┼────────────┐
                        ┌─────▼─────┐ ┌────▼────┐ ┌─────▼──────┐
                        │worker-    │ │celery-  │ │celery-     │
                        │engine     │ │worker   │ │worker-     │
                        │(Metashape)│ │(파일)    │ │thumbnail   │
                        └───────────┘ └─────────┘ └────────────┘
```

| 서비스 | 기술 | 역할 |
|--------|------|------|
| frontend | React + Vite + TailwindCSS | UI |
| nginx | Nginx Alpine | 리버스 프록시, 정적 파일, 타일맵 |
| api | FastAPI + Uvicorn | REST API, WebSocket |
| db | PostgreSQL 15 + PostGIS 3.3 | DB, 공간 데이터 |
| redis | Redis 7 | Celery 브로커/백엔드 |
| worker-engine | Celery + Metashape | GPU 정사영상 처리 (GPU 미인식 시 CPU fallback, 10배+ 느림) |
| celery-worker | Celery | 파일 관리, COG 인제스트 |
| celery-worker-thumbnail | Celery | 썸네일 전용 워커 |
| celery-beat | Celery Beat | 스케줄러 |
| titiler | TiTiler 0.18 | COG 타일 서빙 |
| flower | Flower | Celery 모니터링 |

---

## 2. 프론트엔드

### 2.1 src/App.jsx — 메인 애플리케이션

**역할:** 전체 상태 관리, 뷰 모드 전환, 이벤트 핸들링

**주요 상태:**
- `selectedProjectId` — 현재 선택된 프로젝트
- `viewMode` — 대시보드/처리/프로젝트 상세 뷰 전환
- `uploadsByProject` — 프로젝트별 업로드 진행 상태
- `checkedProjectIds` — 체크된 프로젝트 (배치 작업용)

**핵심 핸들러:**
- `handleUploadComplete()` — 업로드 마법사 완료 시 실행. sourceDir가 있으면 `api.localImport()`, 없으면 `S3MultipartUploader`
- `handleStartProcessing()` — 처리 시작 → `api.startProcessing()`
- `handleExport()` — 내보내기 → ExportDialog 열기

**의존성:** AuthContext, useProjects 훅, S3MultipartUploader

---

### 2.2 src/api/client.js — API 클라이언트

**역할:** 백엔드 REST API 통신, JWT 인증 토큰 관리

**인증:**
- `login(email, password)` → access_token + refresh_token 저장
- 401 응답 시 자동 `refreshAccessToken()` 호출
- 모든 요청에 `Authorization: Bearer {token}` 헤더

**주요 메서드 그룹:**

| 그룹 | 메서드 | 설명 |
|------|--------|------|
| 프로젝트 | `getProjects()`, `createProject()`, `updateProject()`, `deleteProject()` | CRUD |
| 이미지 | `getProjectImages()`, `localImport()`, `getImage()`, `regenerateThumbnail()` | 이미지 관리 |
| 처리 | `startProcessing()`, `getProcessingStatus()`, `cancelProcessing()` | 처리 제어 |
| 내보내기 | `prepareBatchExport()`, `clipExport()`, `mergeExport()` | 다운로드 |
| 도엽 | `getSheets()`, `searchSheet()`, `getSheetScales()` | 도엽 조회 |
| EO | `uploadEoData()`, `readTextFile()` | EO 데이터 |
| WebSocket | `connectStatusWebSocket()` | 실시간 처리 상태 |

---

### 2.3 src/services/s3Upload.js — S3 멀티파트 업로드

**역할:** MinIO/S3 직접 업로드 (현재 로컬 모드에서는 미사용, 레거시 코드)

**클래스:** `S3MultipartUploader`
- `uploadFiles(files, projectId, options)` — 병렬 업로드 시작
- 기본 설정: 동시 파일 6개, 파트 동시성 4개, 파트 크기 10MB
- 실시간 속도(Mbps) 및 ETA 계산
- AbortController로 취소 지원

---

### 2.4 src/contexts/AuthContext.jsx — 인증 컨텍스트

**역할:** 전역 사용자 인증 상태, 권한 판단

**제공 값:**
- `user`, `isAuthenticated`, `isAdmin`
- `canCreateProject`, `canEditProject`, `canDeleteProject`
- `login()`, `logout()`

---

### 2.5 src/components/LoginPage.jsx — 로그인 페이지

**역할:** 아이디/비밀번호 로그인 폼

**상태:** formData (email, password), loading
**동작:** `useAuth().login()` 호출 → 성공 시 대시보드로 전환

---

### 2.6 src/components/Dashboard/DashboardView.jsx — 대시보드 뷰

**역할:** 통계 카드, 차트, 지도를 포함한 메인 대시보드

**구성:**
- 상단: 통계 카드 4개 (면적, 프로젝트, 저장용량)
- 중앙: FootprintMap (프로젝트 위치 지도)
- 하단: 인스펙터 패널 (프로젝트 선택 시)

**API 호출:** `getStorageStats()` — 저장 용량 조회
**상태:** 인스펙터 열림 시 지도 높이 1000px → 900px 자동 조정

---

### 2.7 src/components/Dashboard/FootprintMap.jsx — 대시보드 지도

**역할:** Leaflet 기반 프로젝트 위치/정사영상 표시, 도엽 격자 제어

**주요 내부 컴포넌트:**

| 컴포넌트 | 역할 |
|----------|------|
| `TiTilerOrthoLayer` | TiTiler 서버로 COG 타일 스트리밍 표시 |
| `RegionBoundaryLayer` | 권역 경계 GeoJSON 오버레이 |
| `SheetGridOverlay` | 도엽 격자 오버레이 |
| `SheetControlPanel` | 도엽 축척 선택, 검색, 클립 UI |
| `FootprintMapHeader` | 촬영영역/권역/도엽 토글 버튼 |

**상태:**
- `showBasemap` — 배경지도 토글 (localStorage 연동)
- `availableScales` — 축척 목록 (초기값 50K→25K→5K→1K, API 응답으로 갱신)
- `sheetState` — 도엽 상태 (visible, scale, selectedSheets, overlappingSheets)

**SheetControlPanel 동작:**
1. 축척 버튼 클릭 → `onSheetStateChange({scale: N})`
2. 도엽번호 검색 → `api.searchSheet(mapid)` → 지도 이동
3. 클립 버튼 → `api.clipExport(projectIds, sheetIds, options)`

---

### 2.8 src/components/Dashboard/Sidebar.jsx — 사이드바

**역할:** 프로젝트 목록, 그룹 관리, 처리 진행 표시

**주요 기능:**
- 프로젝트 트리 (그룹별 폴더 구조)
- 검색, 지역 필터
- `ProcessingSteps` — 처리 중 5단계 진행률 표시 (5초 폴링)
  - 내보내기(Export Raster)를 COG 변환에 합산 표시

**의존성:** `useGroupState` 훅 (그룹 CRUD)

---

### 2.9 src/components/Dashboard/Header.jsx — 헤더

**역할:** 상단 네비게이션, 로고, 로그아웃
**의존성:** `useAuth()`

---

### 2.10 src/components/Dashboard/StatsCard.jsx — 통계 카드

**역할:** 재사용 가능한 메트릭 표시 컴포넌트
- `StatsCard` — 단일 메트릭 (아이콘, 값, 단위, 트렌드)
- `StatsCardsGrid` — 그리드 레이아웃

---

### 2.11 src/components/Dashboard/Charts.jsx — 차트

**역할:** Recharts 기반 시각화
- `TrendLineChart` — 월별 처리 현황
- `DistributionPieChart` — 지역별 분포
- `ProgressDonutChart` — 진행률
- `MonthlyBarChart` — 월별 데이터

---

### 2.12 src/components/Upload/UploadWizard.jsx — 업로드 마법사

**역할:** 4단계 프로젝트 생성 마법사

| Step | 내용 | 주요 컴포넌트 |
|------|------|---------------|
| 1 | 이미지 폴더 선택 | ServerFileBrowser |
| 2 | EO 데이터 설정 | ServerFileBrowser (mode="eo"), 컬럼 매핑 UI |
| 3 | 카메라 모델 선택 | 드롭다운 + 커스텀 입력 |
| 4 | 프로젝트명, 처리 모드, 자동 처리 | 텍스트 입력 + 체크박스 |

**완료 시 전달 데이터:** `{ projectData, files, eoFile, eoConfig, cameraModel, sourceDir, filePaths, autoProcess, processMode }`

---

### 2.13 src/components/Upload/ServerFileBrowser.jsx — 서버 파일 탐색기

**역할:** 서버 파일시스템 탐색 (외장하드, 네트워크 드라이브)

**API 호출:**
- `api.getFilesystemRoots()` — 루트 디바이스 목록 (/media, /mnt, /home)
- `api.browseFilesystem(path, fileTypes)` — 디렉토리 내용

**Props:**
- `mode` — "folder" (폴더 선택), "eo" (EO 파일 단일 선택)
- `fileTypes` — "images", "eo", "all"
- `initialPath` — 초기 경로 (EO 선택 시 이미지 폴더로 자동 이동)

---

### 2.14 src/components/Upload/UploadProgressPanel.jsx — 업로드 진행 패널

**역할:** 다중 파일 업로드 상태 실시간 표시

**표시 정보:** 파일별 진행률, 속도(MB/s), ETA, 상태(대기/업로드/완료/오류)

---

### 2.15 src/components/Project/InspectorPanel.jsx — 인스펙터 패널

**역할:** 프로젝트 상세 정보, 처리 상태, 정사영상 관리

**레이아웃:** 2칸 (프로젝트 정보 2/3 + 정사영상 썸네일 1/3)

**좌측 패널 구성:**
- 헤더: BLOCK 배지 + UUID + 상태 배지 + 제목 + 권역/처리모드
- 처리 결과: 면적(km²) · GSD(cm/px) · 정사영상 용량(GB) — 3열 카드 강조 표시
- 기본 정보(생성일, 처리완료일) + 원본 데이터(사진 수, EO, 용량) — 2열 나란히 배치

**주요 동작:**
- 정사영상 삭제 → `api.deleteOrthoCog()` → 썸네일 자동 생성 후 COG 삭제
- 처리 중단 → `api.cancelProcessing()`
- 처리 모드 한글 매핑: Normal→정밀, Fast→고속, Preview→미리보기, High→고정밀

---

### 2.16 src/components/Project/ProjectMap.jsx — 프로젝트 지도

**역할:** EO 포인트, 정사영상 타일, 베이스맵 표시

**주요 기능:**
- `FitBounds` — projectId별 1회만 자동 줌 (반복 방지)
- `MapRefSetter` — map 인스턴스 외부 ref 노출
- EO 포인트 토글 (Eye/EyeOff 아이콘)
- 온디맨드 썸네일 — 클릭 시 `api.regenerateThumbnail()`
- EO 클릭 시 팝업으로 좌표/고도/ω/φ/κ + 썸네일 표시

**컨트롤 버튼 (우상단):**
- 배경지도 토글
- 원래 범위 복귀 (Crosshair 아이콘)
- EO 마커 토글

---

### 2.17 src/components/Project/ExportDialog.jsx — 내보내기 대화상자

**역할:** 정사영상 배치 내보내기, 좌표계/GSD 설정

**동작 흐름:**
1. 옵션 설정 (좌표계, GSD)
2. `api.prepareBatchExport()` → download_id 반환
3. 진행률 폴링 (1초 간격)
4. 완료 시 `triggerDirectDownload()` → 파일 다운로드
5. (선택) COG 삭제 확인 → `api.deleteOrthoCog()`

**상태 초기화:** WebSocket의 allProjects 업데이트로 인한 불필요한 재실행 방지

---

### 2.18 src/components/Project/SheetGridOverlay.jsx — 도엽 격자 오버레이

**역할:** Leaflet 지도에 도엽 Rectangle 표시, 선택/해제

**동작:**
- 줌 레벨 제한 (1:1000→줌14, 1:5000→줌12 이상만 로드)
- `api.getSheets(scale, bounds)` — 뷰포트 내 도엽 조회 (최대 200개)
- `map.on('click')` + bounds 판정으로 도엽 선택 (Canvas 렌더러 우회)

---

### 2.19 src/config/mapConfig.js — 지도 설정

**역할:** 오프라인/온라인 타일 URL 및 기본 설정

```javascript
getTileConfig() → {
  url: '/tiles/{z}/{x}/{y}',  // 오프라인
  // 또는 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'  // 온라인
  center: [35.5, 127.5],
  zoom: 7,
  maxZoom: 16  // 오프라인 (온라인: 18)
}
```

---

### 2.20 Custom Hooks

| 훅 | 파일 | 역할 |
|----|------|------|
| `useProjects()` | src/hooks/useApi.js | 프로젝트 CRUD, 배치 작업 |
| `useProcessingProgress(projectId)` | src/hooks/useProcessingProgress.js | WebSocket 실시간 처리 진행률 |
| `useGroupState()` | src/hooks/useGroupState.js | 프로젝트 그룹 관리 |

---

## 3. 백엔드

### 3.1 backend/app/main.py — FastAPI 진입점

**역할:** 서버 초기화, 라우터 등록, stuck job 복구

**lifespan 이벤트:**
- startup: `_recover_stuck_jobs()` — 'processing' 상태 작업을 'error'로 전환 (전원 차단 복구)
- shutdown: 정리 작업

**등록된 라우터:**
- `/api/v1/auth` — 인증
- `/api/v1/projects` — 프로젝트
- `/api/v1/upload` — 업로드
- `/api/v1/processing` — 처리
- `/api/v1/download` — 다운로드
- `/api/v1/sheets` — 도엽
- `/api/v1/filesystem` — 파일 탐색

---

### 3.2 backend/app/database.py — DB 설정

**역할:** SQLAlchemy 비동기 엔진 및 세션 관리

- `engine`: PostgreSQL asyncpg 드라이버
- `async_session`: 비동기 세션 팩토리
- `get_db()`: 의존성 주입용 (자동 commit/rollback)

---

### 3.3 backend/app/models/project.py — DB 모델

| 모델 | 주요 필드 | 설명 |
|------|----------|------|
| `Project` | title, status, bounds(PostGIS), area, ortho_path, ortho_size, ortho_thumbnail_path | 프로젝트 |
| `Image` | original_path, upload_status, location(PostGIS), project_id(인덱스) | 항공 이미지 |
| `ExteriorOrientation` | x, y, z, omega, phi, kappa, crs | EO 데이터 |
| `CameraModel` | focal_length, sensor_width/height, pixel_size, ppa_x/y | 카메라 IO |
| `ProcessingJob` | engine, status, progress, gsd, output_crs, process_mode, celery_task_id, result_path, result_gsd | 처리 작업 |
| `QCResult` | issues(JSONB), status | 품질 검사 |

**Project 상태값:** pending → queued → processing → completed / error / cancelled

---

### 3.4 backend/app/schemas/project.py — Pydantic 스키마

| 스키마 | 용도 |
|--------|------|
| `ProjectCreate/Update` | 입력 검증 |
| `ProjectResponse` | 응답 (image_count, can_edit 포함) |
| `ProcessingOptions` | 처리 옵션 (engine, gsd, output_crs, process_mode) |
| `ProcessingJobResponse` | 작업 상태 (progress, step_status 포함) |
| `EOConfig/EOUploadResponse` | EO 데이터 관련 |

---

### 3.5 backend/app/api/v1/auth.py — 인증

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /login` | 로그인 → access_token + refresh_token |
| `POST /refresh` | 토큰 갱신 |
| `POST /register` | 비활성화 (403 반환) |

---

### 3.6 backend/app/auth/jwt.py — JWT 유틸리티

| 함수 | 설명 |
|------|------|
| `hash_password()` | bcrypt 해싱 |
| `verify_password()` | 비밀번호 검증 |
| `create_access_token()` | JWT 발급 (기본 24시간) |
| `create_refresh_token()` | Refresh 토큰 (기본 7일) |
| `create_internal_token()` | 내부 서비스용 (Celery→API 통신) |
| `get_current_user()` | 의존성 — 인증된 사용자 반환 |

---

### 3.7 backend/app/api/v1/projects.py — 프로젝트 CRUD

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /` | 프로젝트 목록 (페이지네이션, 필터) |
| `POST /` | 프로젝트 생성 |
| `GET /{id}` | 상세 조회 |
| `PUT /{id}` | 업데이트 |
| `POST /batch` | 배치 작업 (delete, update_status) |
| `POST /{id}/eo-upload` | EO 데이터 업로드 (CSV/TXT 파싱, 좌표 변환) |
| `DELETE /{id}/ortho/cog` | 정사영상 삭제 (썸네일 생성 후 COG 삭제) |
| `DELETE /{id}/source-images` | 원본 이미지 삭제 |
| `GET /stats/monthly` | 월별 통계 |
| `GET /stats/regional` | 지역별 통계 |
| `GET /stats/storage` | 저장 용량 (DB ortho_size 합산) |

**정사영상 삭제 로직 (`DELETE /{id}/ortho/cog`):**
1. `_generate_ortho_thumbnail()` — GDAL로 4096px PNG 썸네일 생성
2. COG 파일 삭제
3. `project.ortho_path = None`, `ortho_size = None`
4. `ortho_thumbnail_path`에 썸네일 경로 저장

**프로젝트 삭제 시 로컬 파일 보호:**
- `original_path`가 절대경로(`/`로 시작)이면 삭제하지 않음 (외장하드 원본 보호)

---

### 3.8 backend/app/api/v1/upload.py — 이미지 업로드/임포트

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /{project_id}/local-import` | 로컬 경로 등록 (파일 복사 없이 DB에 경로만 등록) |
| `GET /{project_id}/images` | 이미지 목록 |
| `GET /images/{image_id}` | 이미지 상세 (썸네일 URL 포함) |
| `POST /images/{image_id}/regenerate-thumbnail` | 온디맨드 썸네일 생성 |

**local-import 동작:**
1. 디렉토리 스캔 (비동기 스레드풀에서 실행 — 이벤트 루프 블로킹 방지)
2. 이미지 파일 필터 (jpg, jpeg, png, tif, tiff)
3. Image 레코드 bulk 생성 (`original_path`에 절대경로 저장)
4. `upload_status = "completed"` 설정
5. 썸네일 비동기 생성 트리거

---

### 3.9 backend/app/api/v1/processing.py — 처리 관리

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /engines` | 활성 처리 엔진 목록 |
| `POST /projects/{id}/start` | 즉시 처리 시작 |
| `POST /projects/{id}/schedule` | 자동 처리 예약 (업로드 완료 시 자동 시작) |
| `GET /projects/{id}/status` | 처리 상태 + step_status 조회 |
| `POST /projects/{id}/cancel` | Celery 태스크 revoke |
| `GET /metrics` | 처리 성능 지표 (큐 대기, 소요시간, 메모리) |
| `WebSocket /ws/projects/{id}/status` | 실시간 처리 진행률 |
| `POST /broadcast` | 내부 — Celery 워커가 WebSocket으로 브로드캐스트 |

**처리 시작 로직:**
1. 업로드 완료 이미지 확인
2. 기존 진행 중 작업 검사 (6시간 미활동 or 24시간 초과 시 자동 리셋)
3. ProcessingJob 생성 (status=queued)
4. `process_orthophoto.delay(job_id, project_id, options)` → Celery 큐

**WebSocket 연결 관리:**
- `ConnectionManager` — 활성 연결 관리
- 죽은 연결 자동 정리 (disconnect 예외 처리)

---

### 3.10 backend/app/api/v1/download.py — 다운로드/내보내기

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /projects/{id}/ortho` | 정사영상 다운로드 (Range 헤더 지원) |
| `POST /batch` | 배치 내보내기 (ZIP) |
| `POST /clip` | 도엽 클립 내보내기 |
| `POST /merge` | 도엽 머지 내보내기 |

**클립 처리:** `gdalwarp -t_srs {crs} -te {minx} {miny} {maxx} {maxy} -r bilinear -co COMPRESS=LZW`
**머지 처리:** 각 COG 클립 후 → gdalwarp로 모자이킹

---

### 3.11 backend/app/api/v1/sheets.py — 도엽 격자

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /scales` | 사용 가능한 축척 (GeoJSON 파일 존재 여부 기반) |
| `GET /` | bounds 교차 도엽 조회 (최대 200개) |
| `GET /search` | 도엽번호 검색 |

**데이터 로딩:**
- `data/TN_MAPINDX_{scale}K_5179.geojson` 파일에서 bounds만 추출
- 메모리 캐시: 5K ~0.5MB, 1K ~14MB (원본 190MB 전체 로드 안 함)
- EPSG:5179 → WGS84 변환 (pyproj)

---

### 3.12 backend/app/api/v1/filesystem.py — 파일 탐색

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /devices` | 마운트된 디바이스 목록 (/media, /mnt, /home) |
| `GET /browse` | 디렉토리 내용 (file_types 필터: images, eo, all) |
| `GET /read-text` | 텍스트 파일 읽기 (EO 파일 미리보기용) |

---

### 3.13 backend/app/services/storage_local.py — 로컬 저장소

**역할:** MinIO 없이 로컬 파일시스템에 직접 저장

| 메서드 | 설명 |
|--------|------|
| `upload_file()` | 파일 복사 (같은 경로면 스킵) |
| `move_file()` | 파일 이동 (복사보다 효율적) |
| `get_local_path()` | 로컬 절대 경로 반환 |
| `get_presigned_url()` | nginx alias 기반 URL 반환 |
| `delete_recursive()` | 재귀 삭제 |
| `object_exists()` | 파일 존재 확인 |

**보안:** Path traversal 방지 (`_resolve` 메서드)

---

### 3.14 backend/app/services/eo_parser.py — EO 파서

**역할:** 외부방향정보 CSV/TXT 파일 파싱

**파싱 옵션:**
- delimiter: 자동 감지 (comma, space, tab)
- header: 유무 감지
- column 순서: 커스터마이징 가능
- 무효 행 자동 스킵

**출력:** `EORow(image_name, x, y, z, omega, phi, kappa)` 리스트

---

### 3.15 backend/app/workers/tasks.py — Celery 태스크

**Celery 설정:**
- Broker/Backend: Redis
- `visibility_timeout`: 604800초 (7일) — 장시간 처리 시 Redis 재전달 방지
- `worker_prefetch_multiplier`: 1 — 한 번에 1개만 가져옴
- `task_routes`: 엔진별 큐 분리 (metashape, thumbnail, celery)

**주요 태스크:**

| 태스크 | 큐 | 설명 |
|--------|-----|------|
| `process_orthophoto` | metashape | 메인 처리 파이프라인 |
| `generate_thumbnail` | thumbnail | 이미지 썸네일 생성 (GDAL 우선 → PIL 폴백) |
| `delete_project_data` | celery | 프로젝트 데이터 삭제 |
| `save_eo_metadata` | celery | EO 메타데이터 저장 |
| `inject_external_cog` | celery | 외부 COG 인제스트 |

**process_orthophoto 단계:**
1. 이미지 준비 — symlink 생성 (로컬) 또는 다운로드 (MinIO)
2. EO 데이터 임포트
3. processing_router.py 실행 (subprocess)
4. COG 변환 (`gdal_translate -of COG -co BLOCKSIZE=1024 -co COMPRESS=LZW -co BIGTIFF=YES`)
5. GSD/경계 추출, 프로젝트 지오정보 업데이트
6. 스토리지 업로드, 체크섬(SHA256) 계산
7. DB 업데이트, 메트릭 저장

**멱등성:** `job.status == 'completed'`이면 재실행 skip

---

### 3.16 backend/entrypoint.sh — 시작 스크립트

**실행 순서:**
1. PostgreSQL 연결 대기 (30회 재시도)
2. Alembic 마이그레이션 (다중 head 자동 머지)
3. 카메라 모델 시드 (`seed_camera_models.py`)
4. 권역 데이터 시드 (`regions_seed.sql` 우선 → GeoJSON 폴백)
5. 기본 관리자 계정 생성 (`admin` / `siqms`)
6. Uvicorn 서버 시작 (0.0.0.0:8000)

---

## 4. 처리 엔진

### 4.1 처리 파이프라인 (Metashape DAGs)

```
activate_metashape_license.py
         ↓
    align_photos.py          ← 사진 정렬 (downscale: Preview=4, Normal=2, High=1)
         ↓
   build_depth_maps.py       ← 깊이맵 생성 (downscale: Preview=8, Normal=4, High=1)
         ↓
      build_dem.py            ← DEM 생성 (선택)
         ↓
  build_orthomosaic.py       ← 정사 모자이크 (refine_seamlines=True)
         ↓
  export_orthomosaic.py      ← GeoTIFF 내보내기
         ↓
     convert_cog.py          ← COG 변환 (BLOCKSIZE=1024, COMPRESS=LZW, BIGTIFF=YES)
         ↓
deactivate_metashape_license.py
```

### 4.2 common_utils.py — 공유 유틸리티

| 함수 | 설명 |
|------|------|
| `progress_callback(value, task_name, output_path)` | 진행률을 status.json에 기록 (10% 단위 로그) |
| `change_task_status_in_ortho(run_id, status)` | API broadcast 호출 (WebSocket 전송) |
| `check_success(output_path)` | status.json으로 성공 판단 (99-100: 성공, 1000: 실패) |

### 4.3 align_photos.py — 사진 정렬

**동작:**
1. Metashape Document/Chunk 생성
2. CRS 설정 (기본 EPSG:4326)
3. 사진 추가 + EO 데이터 임포트
4. 드론 제조사 감지 → EulerAnglesOPK 설정
5. `matchPhotos()` — downscale은 처리 모드에 따라 결정
6. `alignCameras()`

### 4.4 build_orthomosaic.py — 정사 모자이크

**동작:**
1. project.psx 오픈
2. `chunk.buildOrthomosaic(surface_data=ElevationData, refine_seamlines=True)`
3. 결과 GSD 저장

### 4.5 convert_cog.py — COG 변환

**동작:**
1. result.tif → result_cog.tif 변환
2. COG 옵션: `BLOCKSIZE=1024, COMPRESS=LZW, RESAMPLING=LANCZOS, BIGTIFF=YES`
3. alignment ≥ 80%이면 project.files 삭제 (저장소 절약)
4. 실패 시 파일 보존 (디버깅용)

### 4.6 engines/metashape/entrypoint.sh — 워커 시작

**동작:**
1. SIGTERM/SIGINT 신호 처리
2. `METASHAPE_LICENSE_KEY` 환경변수로 자동 활성화
3. Celery 워커 실행 (백그라운드)
4. 종료 시 자식 프로세스만 정리 (라이선스는 유지)

---

## 5. 인프라

### 5.1 docker-compose.yml / docker-compose.prod.yml

**개발 vs 프로덕션 차이:**

| 항목 | 개발 (docker-compose.yml) | 프로덕션 (docker-compose.prod.yml) |
|------|--------------------------|-----------------------------------|
| 소스 마운트 | 있음 (핫 리로드) | 없음 (이미지 내장) |
| DB 포트 | 5434 노출 | 미노출 (보안) |
| Redis 포트 | 6380 노출 | 미노출 |
| worker-engine | `--profile engine` | `--profile engine` |
| restart | unless-stopped | always |

**호스트 파일시스템 마운트:**
```yaml
- /media:/media:ro,rslave    # 외장하드
- /mnt:/mnt:ro               # 마운트 포인트
- /run/media:/run/media:ro    # 자동 마운트
- /home:/home:ro              # 홈 디렉토리
```

### 5.2 nginx.prod.conf

**라우팅 규칙:**

| 경로 | 대상 |
|------|------|
| `/` | frontend (React) |
| `/api/` | api (FastAPI) |
| `/titiler/` | titiler (COG 타일) |
| `/tiles/{z}/{x}/{y}` | 오프라인 타일 (try_files .jpg .jpeg .png) |
| `/storage/` | 로컬 저장소 (정사영상 서빙) |

### 5.3 scripts/build-release.sh

**배포 패키지 빌드 흐름:**
1. 기존 배포 이미지 삭제
2. `docker compose -p aerial-prod -f docker-compose.prod.yml --profile engine build --no-cache`
3. 이미지 태깅 (`aerial-survey-manager:{service}-{version}`)
4. docker-compose.prod.yml → docker-compose.yml 변환 (Python: build → image 치환)
5. Docker 이미지 tar.gz 저장
6. 권역/도엽 GeoJSON, SSL 인증서, 스크립트 복사
7. 전체 패키지 tar.gz 생성

### 5.4 scripts/install.sh

**설치 흐름:**
1. 시스템 요구사항 확인 (Docker, NVIDIA)
2. **Docker GPU 전달 검증** — nvidia runtime 등록 확인 + 실제 컨테이너 GPU 테스트. 실패 시 자동 복구 시도
3. `.env` 생성 (비밀번호 자동 생성)
4. nginx 설정 (도메인)
5. SSL 설정 (선택)
6. Docker 이미지 로드 또는 빌드
7. 서비스 시작
8. 헬스체크

### 5.5 scripts/fix-gpu.sh

**GPU 진단 및 복구 스크립트.** 컨테이너에서 GPU가 인식되지 않을 때 사용.

**실행:** `sudo bash scripts/fix-gpu.sh`

**동작:**
1. 호스트 GPU 드라이버 확인 (`nvidia-smi`)
2. NVIDIA Container Toolkit 확인 → 없으면 자동 설치
3. Docker GPU 전달 테스트 (`docker run --gpus all`) → 실패 시 Docker 재시작
4. worker-engine 재시작
5. 최종 확인 (`docker exec aerial-worker-engine nvidia-smi`)

### 5.6 기타 운영 스크립트

| 스크립트 | 용도 |
|----------|------|
| `healthcheck.sh` | 전체 서비스 상태 점검 (Docker, API, DB, Redis, GPU, Celery) → PASS/WARN/FAIL 요약 |
| `collect-logs.sh` | 모든 서비스 로그 + 시스템 정보 수집 → `logs_*.tar.gz` (비밀번호 자동 제외) |
| `shutdown-metashape.sh` | Metashape 라이선스 비활성화 → worker-engine 종료 → 전체 종료 (선택) |
| `system-info.sh` | OS/CPU/RAM/디스크/GPU/Docker/네트워크 정보 출력 |
| `setup-autostart.sh` | `systemctl enable docker` + restart 정책 확인 |
| `secure-deployment.sh` | .env 권한 제한, systemd 서비스 등록, 사용자 관리 명령어 생성 |

---

## 6. 데이터 흐름

### 6.1 이미지 업로드 (로컬 모드)
```
사용자 → UploadWizard(Step1) → ServerFileBrowser → 폴더 선택
  → App.handleUploadComplete() → api.localImport(projectId, sourceDir)
  → backend: 파일 스캔(스레드풀) → Image 레코드 bulk 생성
  → upload_status = "completed"
  → generate_thumbnail.delay() → thumbnail 큐
```

### 6.2 처리 파이프라인
```
사용자 → "처리 시작" → api.startProcessing()
  → backend: ProcessingJob 생성(queued)
  → process_orthophoto.delay() → metashape 큐
  → Celery worker:
    1. _prepare_images() → symlink 생성
    2. processing_router.py → Metashape DAG 실행
       → align → depth → DEM → orthomosaic → export
    3. _convert_to_cog() → COG 변환
    4. _upload_cog_to_storage() → 결과 저장
    5. DB 업데이트 (project.ortho_path, ortho_size)
  → _broadcast_ws() → WebSocket → 프론트엔드 실시간 업데이트
```

### 6.3 정사영상 표시
```
사용자 → 프로젝트 선택 → FootprintMap
  → api.getCogUrl(projectId) → presigned URL
  → TiTilerOrthoLayer → TiTiler 서버
  → /titiler/cog/tiles/{z}/{x}/{y}.png?url={cog_url}
  → COG 내부 타일 구조 활용 (전체 파일 읽기 불필요)
```

### 6.4 도엽 클립
```
사용자 → 도엽 선택 → "클립" 버튼
  → api.clipExport(projectIds, sheetIds, {crs, gsd})
  → backend: gdalwarp -te {도엽 bounds} → 클립된 GeoTIFF
  → 단일 도엽: 동기 처리 → 즉시 다운로드
  → 다중 도엽: Celery 비동기 → ZIP → 다운로드
```
