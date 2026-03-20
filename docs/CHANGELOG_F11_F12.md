# 변경사항 정리 (f5e4faa 이후)

> 기준 커밋: `f5e4faa` (feat: 안정성 개선, 처리 단계 표시, 단일 계정 운영 체제)
> 작성일: 2026-03-20

---

## 1. 신규 기능

### F11. 썸네일 전용 워커 분리 + 온디맨드 생성
- 썸네일 큐를 `celery` → `thumbnail` 전용 큐로 분리 (처리 중에도 썸네일 동시 생성)
- 처리 중 Redis throttling 제거
- GDAL 우선 → PIL 폴백 구조로 썸네일 생성 속도 개선 (22초 → 0.1~5초)
- EO 포인트 클릭 시 온디맨드 썸네일 생성 + 로딩 스피너 표시
- `docker-compose.yml` / `docker-compose.prod.yml`: `celery-worker-thumbnail` 서비스 추가

### EO 포인트 토글
- `ProjectMap.jsx`: Eye/EyeOff 아이콘으로 EO 마커 표시/숨김 토글 버튼 추가

---

## 2. 안정성 개선

### Stuck Job 복구
- `backend/app/main.py`: 서버 시작 시 'processing' 상태로 고착된 작업을 'error'로 전환 (전원 차단 복구)

### WebSocket 죽은 연결 정리
- `backend/app/api/v1/processing.py`: disconnect 예외 처리 개선, 죽은 연결 자동 정리

### 로컬 파일 보호
- `backend/app/api/v1/projects.py`: 프로젝트 삭제 시 로컬 임포트 파일(절대경로)은 삭제하지 않도록 보호

### Healthcheck 강화
- 모든 Celery 워커에 `celery inspect ping` 기반 healthcheck 추가
- worker-engine: graceful shutdown (120s), stop_signal SIGTERM

---

## 3. 성능 최적화

### 파일 스캔 비동기화
- `backend/app/api/v1/upload.py`: 파일 스캔을 비동기 스레드풀로 이관 (이벤트 루프 블로킹 방지)

### DB 인덱스 추가
- `backend/app/models/project.py`: `Image.project_id` 컬럼에 인덱스 추가

---

## 4. UX 개선

### 용어 통일
- "COG 정사영상" / "COG" → "정사영상"으로 통일 (ExportDialog, InspectorPanel)

### ExportDialog 버그 수정
- 대화상자 재진입 시 상태 초기화 버그 수정
- 컴포넌트 언마운트 시 interval 정리

### 업로드 후 자동 종료
- `App.jsx`: 처리 모드 진입 시 업로드 다이얼로그 자동 종료

### 축척 버튼 정렬
- `FootprintMap.jsx`: 축척 버튼 큰 축척 우선 정렬 (50K → 25K → 5K → 1K)

---

## 5. 배포/인프라 개선

### 호스트 파일시스템 마운트
- `/media`, `/mnt`, `/run/media`, `/home` 마운트 추가 (외부 드라이브 이미지 접근)

### 자동 관리자 계정 생성
- `backend/entrypoint.sh`: 기존 계정 없을 때 기본 관리자 계정 자동 생성

### 권역 데이터 초기화 개선
- `backend/entrypoint.sh`: SQL 덤프 우선 → GeoJSON 폴백 방식

### 라이선스 자동 활성화
- `engines/metashape/entrypoint.sh`: METASHAPE_LICENSE_KEY 환경변수 기반 자동 활성화

### 빌드/설치 스크립트 개선
- `scripts/build-release.sh`: docker-compose.yml 동적 생성 (Python 스크립트), 도엽 GeoJSON 복사 로직 추가
- `scripts/install.sh`: MinIO 설정 제거, LOCAL_STORAGE_PATH 통합, COMPOSE_PROFILES 자동 설정
- `nginx.prod.conf`: 타일맵 경로 개선, .jpeg 확장자 추가

### Docker 보안 조정
- `backend/Dockerfile.prod`: 비루트 사용자 제거 (호스트 파일시스템 접근을 위해 root 필요)

---

## 6. 코드 정리

### 삭제된 파일
| 파일 | 사유 |
|------|------|
| `src/services/upload.js` | 미사용 레거시 (HTTP 업로드 → 로컬 경로 등록으로 전환) |
| `src/components/Dashboard/KoreaMap.jsx` | 미사용 컴포넌트 (export만 되고 import 없음) |
| `backend/scripts/sync_data.py` | 미사용 유틸리티 스크립트 |
| `engines/metashape/temp_export_dem.py` | 임시 실험 파일 |
| `engines/metashape/webserver_config.py` | 미사용 설정 파일 |
| `docs/PROGRESS_F2.md` ~ `PROGRESS_F11.md` (9개) | `SPRINT5_COMPLETION.md`로 통합 |

### 정리된 export
- `src/components/Dashboard/index.js`: KoreaMap, RegionStatsTable export 제거

---

## 7. 신규 파일

| 파일 | 설명 |
|------|------|
| `backend/alembic/versions/6e5a787f17c3_*.py` | Image.project_id 인덱스 마이그레이션 |
| `backend/alembic/versions/97e6f82943ae_*.py` | ortho_thumbnail_path 컬럼 마이그레이션 |
| `backend/scripts/regions_seed.sql` | 권역 데이터 SQL 시드 |
| `docs/SPRINT5_COMPLETION.md` | Sprint 5 (F2~F11) 통합 완료 기록 |
| `docs/BUG_REPORT_2026_03.md` | 시스템 버그 26건 분석 리포트 |

---

## 변경 파일 통계
- 수정: 20개 파일
- 삭제: 15개 파일 (미사용 5개 + PROGRESS_F*.md 9개 + Dockerfile.prod 내용)
- 신규: 5개 파일
- 총: +769줄, -2,044줄
