# 작업 완료 기록 — F6

## F6: 내보내기 후 COG 삭제 선택 - 2026-03-13
### 요구사항
- 정사영상 내보내기 완료 후, 사용자에게 COG 파일 삭제 여부를 선택할 수 있게 한다
- 저장공간 확보를 위해 COG를 삭제할 수 있되, 삭제 전 충분한 경고 제공

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
- [x] D4. 커밋

### 구현 계획

**백엔드:**
1. `DELETE /api/v1/projects/{project_id}/ortho/cog` API 추가
   - COG 삭제 전 GDAL로 저해상도 썸네일 PNG 생성 (1024px)
   - COG 파일 삭제 + `project.ortho_path = null`, `project.ortho_size = null`
   - `project.ortho_thumbnail_path`에 썸네일 경로 저장
   - 프로젝트 상태, bounds, area, GSD 등 메타데이터는 보존
2. `ortho_thumbnail_path` 컬럼 추가 (projects 테이블)

**프론트엔드:**
1. ExportDialog에서 다운로드 완료 후 COG 삭제 확인 다이얼로그 표시
   - 파일 크기 표시, "되돌릴 수 없습니다" 경고
   - "삭제" / "보관" 버튼
2. 삭제 성공 시 프로젝트 목록 갱신
3. 대시보드/처리화면에서 COG 없고 썸네일 있으면 ImageOverlay로 표시

### A2. 논리적 타당성 검토
- ExportDialog에서 다운로드 완료 시점을 감지 가능: `prepareBatchExport` → `triggerDirectDownload` 후 시점
- COG 삭제 전 GDAL `gdal_translate -outsize 1024 0`으로 빠르게 썸네일 생성 (COG overviews 활용)
- 기존 `/api/v1/storage/files/` 엔드포인트로 썸네일 서빙 (별도 API 불필요)

### A3. 과도 설계 검토
- 썸네일은 COG 삭제 시에만 생성 (처리 파이프라인 변경 없음)
- DB 마이그레이션: 단순 nullable 컬럼 1개 추가

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
(검토 과정에서 발견된 사항 기록)
