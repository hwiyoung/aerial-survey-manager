# 개발 로드맵 (Roadmap)

> 📌 이 문서는 [README.md](../README.md)와 연계된 상세 개발 이력 및 향후 계획입니다.

---

## 현재 진행 상황

| Phase | 상태 | 설명 |
|-------|------|------|
| Phase 1: Foundation | ✅ 완료 | 백엔드 구조, DB 스키마, JWT 인증 |
| Phase 2: File Transfer | ✅ 완료 | S3 Multipart Upload, Resumable Download |
| Phase 3: Processing | ✅ 완료 | Metashape GPU 엔진, Celery 워커 |
| Phase 4: Dashboard | ✅ 완료 | 지도 시각화, EO 파싱, 프로젝트 관리 |
| Phase 5: Advanced | ✅ 완료 | TiTiler 통합, 통계 API, 내보내기, 그루핑 |
| Phase 6: Hardening | ✅ 완료 | TB급 업로드, 라이선스 안정화, Monorepo 구조 |
| Phase 7: UX Polish | ✅ 완료 | 멀티 프로젝트 업로드, UI 개선, 버그 수정 |

---

## 향후 개선 예정

### 고우선순위
- [ ] 다중 사용자 권한 관리 (관리자/편집자/뷰어 역할 분리)
- [ ] 그룹 단위 일괄 작업 (다중 프로젝트 처리/내보내기)

### 중우선순위
- [ ] 조직 스토리지 할당량 관리 (버킷별 용량 제한)
- [ ] COG 로딩 성능 개선 (Web Worker 재활성화)

### 저우선순위
- [ ] ODM/External 엔진 재활성화 (현재 Metashape 전용)

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Frontend | React + Vite + TailwindCSS + Leaflet + Recharts |
| Backend | FastAPI + PostgreSQL + PostGIS + MinIO |
| Upload | S3 Multipart (Presigned URLs via nginx) |
| Processing | Metashape 2.2.0 (GPU, Celery Worker) |
| Tiles | TiTiler (COG 타일 스트리밍) |

---

## ⚠️ Known Issues

### 지도 및 상호작용
- **권역 툴팁 우선순위**: 권역과 프로젝트 중첩 시 일부 상황에서 권역 툴팁 표시됨

### 시스템
- **COG Loading**: MinIO 외부 접근 시 `MINIO_PUBLIC_ENDPOINT` 설정 필요
- **처리 중단 후 재시작**: Metashape에서 `Empty DEM` 오류 발생 가능 (EO 재업로드 권장)

### 저장소
- **MinIO 용량 부족**: 디스크 여유 10% 미만 시 HTTP 507 오류
  - 해결: `MINIO_DATA_PATH`를 대용량 드라이브로 설정

---

## 최근 변경 이력

| 날짜 | 항목 | 내용 |
|------|------|------|
| 2026-02-02 | 권역명 표준화 | "충청권역" → "충청 권역" 등 공백 추가 |
| 2026-02-02 | 스토리지 정리 | TUS 청크 파일 완전 삭제 (`delete_recursive`) |
| 2026-02-02 | 고아 파일 정리 | `cleanup_orphaned_data.py` 스크립트 추가 |
| 2026-02-02 | 대시보드 UI | 지도 높이 2배 증가, 파이차트 레전드 하단 배치 |
| 2026-02-02 | 헤더 클릭 리셋 | 로고 클릭 시 지도 초기 뷰로 리셋 |
| 2026-02-02 | 멀티 프로젝트 업로드 | 단일 탭에서 여러 프로젝트 동시 업로드 지원 |
| 2026-02-02 | 글로벌 업로드 | 앱 내 네비게이션 중 업로드 유지 |
| 2026-02-02 | 업로드 검증 | 처리 시작 전 불완전한 업로드 감지 |
| 2026-02-02 | Metashape | Point Cloud 선택적 생성, Alignment 로깅 개선 |
| 2026-01-30 | 처리 상태 복구 | 재진입 시 마지막 진행률 즉시 동기화 |
| 2026-01-29 | 대시보드 메타데이터 | 단일 클릭으로 상세 통계 표시 |
| 2026-01-29 | 썸네일 시스템 | 업로드 즉시 생성 및 백필 자동화 |
| 2026-01-29 | 지도 상호작용 | 중첩 프로젝트 선택 팝업, 레이어 우선순위 조정 |
| 2026-01-29 | Metashape 2.2.0 | 호환성 패치, 라이선스 볼륨 영속화 |
| 2026-01-27 | Metashape 통합 | Celery 워커 기반 통합, GPU 가속 |
| 2026-01-23 | 내보내기 고도화 | 단일 TIF 직접 다운로드, ZIP 손상 수정 |
| 2026-01-22 | TiTiler 통합 | COG 타일 스트리밍 (메모리 90%+ 절감) |
| 2026-01-19 | 업로드 최적화 | TB급 업로드, Nginx 버퍼링 해제 |
| 2026-01-19 | 일괄 내보내기 | 다중 프로젝트 ZIP 다운로드 |
| 2026-01-12 | 통계 API | 월별/지역별 통계 엔드포인트 구현 |
| 2026-01-12 | 프로젝트 그루핑 | 폴더 트리, 드래그앤드롭 구현 |

---

*마지막 업데이트: 2026-02-02*
