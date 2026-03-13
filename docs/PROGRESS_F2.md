# 작업 완료 기록 — F2

## F2. 로컬 환경 이미지 불러오기 (Metashape 방식) - 2026-03-12

### 요구사항
기존 HTTP 업로드 방식을 로컬 경로 등록 방식으로 변경. 사용자가 폴더 경로를 입력하면 파일 복사 없이 DB에 경로만 등록하고, 처리 시 symlink로 원본 참조. (SPRINT5_PLAN.md F2 참조)

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
- [x] D4. 커밋 (82ef6de)

### A1. 구현 계획

#### 변경 대상 파일 (5개)

**1. `backend/app/api/v1/upload.py` — 신규 엔드포인트 추가**
- `POST /projects/{project_id}/local-import` 엔드포인트 신설
- 요청: `{ source_dir: "/path/to/images" }`
- 동작: 디렉토리 스캔 → Image 레코드 bulk 생성 → 썸네일 비동기 트리거
- 기존 업로드 엔드포인트는 삭제하지 않음 (백엔드 API 호환성 유지)

**2. `backend/app/workers/tasks.py` — `_prepare_images()` 수정**
- 현재: `storage.get_local_path(original_path)` → 스토리지 키 기반 경로 해석
- 변경: `original_path`가 절대 경로(`/`로 시작)이면 직접 사용, 아니면 기존 로직
- 파일 미존재 시 명확한 에러 메시지 (외장하드 분리 등)

**3. `src/components/Upload/UploadWizard.jsx` — UI 내부 동작 변경**
- 기존 "폴더 선택" / "이미지 선택" 카드 레이아웃 유지
- 클릭 시 경로 입력 필드 표시 → 사용자가 경로 문자열 입력
- "불러오기" 버튼 → `/local-import` API 호출
- 기존 HTTP 업로드 로직 비활성화 (FE에서만, BE API는 유지)

**4. `src/services/s3Upload.js` 또는 신규 서비스 — API 호출 함수 추가**
- `registerLocalPaths(projectId, sourceDirPath)` 함수 추가
- 기존 멀티파트 업로드 함수는 유지 (호출하지 않을 뿐)

**5. `backend/app/services/storage_local.py` — 변경 없음 (확인만)**
- `get_local_path()`: F2 경로는 이 함수를 거치지 않음을 확인

#### 구현 순서
1. BE: `/local-import` 엔드포인트 구현
2. BE: `_prepare_images()` 절대 경로 분기 추가
3. FE: UploadWizard 내부 동작 변경
4. FE: API 호출 함수 추가
5. 통합 테스트

### A2. 계획 검토 결과
- `_prepare_images()`의 분기 로직이 핵심 변경점. 기존 스토리지 키 기반 경로와 절대 경로를 구분하는 조건(`startswith("/")`)이 충분히 안전한지 확인 필요 → Linux 환경에서 절대 경로는 항상 `/`로 시작하므로 안전
- `upload_status`를 "completed"로 설정하면 기존 처리 시작 조건과 호환됨. 새로운 상태값 불필요
- 기존 BE 업로드 API를 삭제하지 않으므로 백엔드 호환성 유지

### A3. 과도 설계 검토 결과
- 경로 화이트리스트(`LOCAL_IMPORT_ALLOWED_PATHS`): 단일 사용자 로컬 환경이므로 구현하되, 환경변수 미설정 시 모든 경로 허용 (기본 동작을 제한하지 않음)
- 새로운 upload_status 값("registered") 불필요 → 기존 "completed" 사용으로 충분
- 경로 입력 UI: 별도 모달이나 복잡한 파일 트리 불필요 → 텍스트 입력 + 버튼으로 충분

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
- `original_path`에 절대 경로를 저장하면 기존 스토리지 키(`images/{project_id}/file`)와 형태가 다름 → `_prepare_images()`에서 `/` 시작 여부로 구분
- 썸네일 생성: 경로 등록 시 `generate_thumbnail.delay()` 호출하여 기존과 동일하게 비동기 생성

---

## F2 추가 개선사항 - 2026-03-12

### 요구사항
ServerFileBrowser 기반 파일 탐색 UX 개선 3건 + 1건

### 진행 체크리스트
- [x] B1. 내장 디스크(홈 디렉토리) 디바이스 목록에 표시
- [x] B2. Shift+클릭 시 텍스트 드래그 선택 방지 (select-none)
- [x] B3. EO 파일 선택을 네이티브 탐색기 대신 ServerFileBrowser로 통일
- [x] B4. EO FileBrowser 열 때 이미지 선택 경로(sourceDir)로 초기 이동
- [x] C1~C5. 코드 품질 검토 및 빌드 검증
- [x] 🚪 변경사항 보고
- [x] D1~D3. UX/통합/배포 검토
- [x] 🚪 최종 승인
- [x] D4. 커밋 (82ef6de)

### 변경 파일 요약

| 파일 | 변경 내용 |
|---|---|
| `backend/app/api/v1/filesystem.py` | ALLOWED_ROOTS·SCAN_DEPTHS에 /home 추가, EO_EXTENSIONS·FILE_TYPE_PRESETS 추가, browse에 file_types 파라미터, read-text 엔드포인트 신설 |
| `src/components/Upload/ServerFileBrowser.jsx` | select-none, fileTypes·initialPath prop, mode="eo" 단일선택 모드, FileText 아이콘 |
| `src/api/client.js` | readTextFile() 추가, browseFilesystem에 fileTypes 파라미터 |
| `src/components/Upload/UploadWizard.jsx` | Step 2 EO를 ServerFileBrowser로 교체, eoInputRef 제거, initialPath로 sourceDir 전달 |

### 추가 운영 개선 (동일 커밋)
- `docker-compose.yml`: worker-engine concurrency 4→1 (Metashape 단일 라이선스 제약)
- `backend/app/workers/tasks.py`: 처리 중 썸네일 생성 쓰로틀링 (Redis 플래그)
