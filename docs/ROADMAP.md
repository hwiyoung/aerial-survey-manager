# 개발 로드맵

## 현재 상태

모든 핵심 기능이 완료되었습니다.

| Phase | 상태 | 설명 |
|-------|------|------|
| Phase 1: Foundation | ✅ | 백엔드, DB, JWT 인증 |
| Phase 2: File Transfer | ✅ | S3 Multipart Upload, Resumable Download |
| Phase 3: Processing | ✅ | Metashape GPU 엔진, Celery 워커 |
| Phase 4: Dashboard | ✅ | 지도 시각화, EO 파싱, 프로젝트 관리 |
| Phase 5: Advanced | ✅ | TiTiler 통합, 통계 API, 내보내기 |
| Phase 6: Hardening | ✅ | TB급 업로드, 라이선스 안정화 |
| Phase 7: UX Polish | ✅ | 멀티 프로젝트 업로드, UI 개선 |

---

## 향후 개선 예정

### 고우선순위
- [ ] 다중 사용자 권한 관리 (관리자/편집자/뷰어)
- [ ] 그룹 단위 일괄 작업

### 중우선순위
- [ ] 조직 스토리지 할당량 관리
- [ ] COG 로딩 성능 개선 (Web Worker)

### 저우선순위
- [ ] ODM/External 엔진 재활성화

---

## Known Issues

### 지도
- **권역 툴팁 우선순위**: 권역과 프로젝트 중첩 시 일부 상황에서 권역 툴팁 표시됨
- **오프라인 타일**: `VITE_MAP_OFFLINE=true` 설정 시 로컬 타일 필요

### 시스템
- **COG Loading**: MinIO 외부 접근 시 `MINIO_PUBLIC_ENDPOINT` 설정 필요
- **처리 중단 후 재시작**: `Empty DEM` 오류 발생 가능 (EO 재업로드 권장)

### 저장소
- **MinIO 용량 부족**: 디스크 여유 10% 미만 시 HTTP 507 오류
  - 해결: `MINIO_DATA_PATH`를 대용량 드라이브로 설정
  - 상세: [ADMIN_GUIDE.md](./ADMIN_GUIDE.md#minio-저장소-관리)

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Frontend | React, Vite, TailwindCSS, Leaflet |
| Backend | FastAPI, PostgreSQL, PostGIS, MinIO |
| Processing | Metashape 2.2.0 (GPU, Celery) |
| Tiles | TiTiler (COG 스트리밍) |

---

## 주요 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-02-08 | 처리 로그 개선 (단계별 타이밍, .processing.log), 중간산출물 숨김폴더(.work/) 분리 |
| 2026-02-06 | 개발/배포 이미지 분리, 코드 보호 (.pyc) |
| 2026-02-05 | result_gsd 표시 수정, 조건부 내보내기, 저장공간 최적화 |
| 2026-02-04 | 출력 좌표계 자동 설정, COG 원본 GSD 유지 |
| 2026-02-03 | 썸네일 생성 분리, 오프라인 지도, 라이센스 관리 |
| 2026-02-02 | 멀티 프로젝트 업로드, 글로벌 업로드 상태 |
| 2026-01-29 | 대시보드 메타데이터, 썸네일 시스템 |
| 2026-01-27 | Metashape Celery 통합, GPU 가속 |
| 2026-01-22 | TiTiler 통합 (메모리 90% 절감) |

---

*마지막 업데이트: 2026-02-08*
