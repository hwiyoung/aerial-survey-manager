# 작업 완료 기록 — F9

## F9: 처리화면 정보 통합 및 COG 삭제 UI 개선 - 2026-03-16
### 요구사항
1. 프로젝트 싱글클릭(ProjectDetailView)과 더블클릭(InspectorPanel) 시 보이는 정보를 통일
2. 원본 이미지 정보(원본사진, 원본 총 용량, 원본 이미지 삭제) 제거 → 정사영상 정보만 표시
3. "원본 이미지 삭제" 자리에 "COG 정사영상 삭제" 버튼 배치
4. COG 삭제된 프로젝트에서 "지도 로딩중" 무한대기 수정
5. 대시보드 지도 기본 높이 조정 (600px → 1000px)

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

**변경 1: 싱글/더블 클릭 뷰 통합**
- `App.jsx`: `onSelectProject` 핸들러에서 `setShowInspector(true)` 추가
- 효과: 싱글클릭도 InspectorPanel을 표시 (ProjectDetailView 대신)

**변경 2: InspectorPanel에서 원본 정보 제거 + 정사영상 정보만 표시**
- `InspectorPanel.jsx`: 원본사진, 원본 총 용량, 원본 이미지 삭제 버튼, 삭제됨 배지 제거
- 정사영상 용량, 정사영상 면적, GSD, 처리 모드 등 정사영상 관련 정보만 유지

**변경 3: COG 정사영상 삭제 버튼 추가**
- `InspectorPanel.jsx`: 원본 이미지 삭제 자리에 COG 정사영상 삭제 버튼 배치
- 조건: `project.status === 'completed' && project.ortho_path` (COG 존재 시)
- COG 삭제 완료 후 `onProjectUpdate` 호출하여 프로젝트 목록 갱신
- COG 이미 삭제된 경우 "COG 삭제됨" 배지 표시

**변경 4: 지도 로딩중 무한대기 수정**
- `ProjectMap.jsx`: `isLoading` 설정 조건에 `project.ortho_path` 존재 여부 추가
- COG 없으면 로딩 상태 설정하지 않음 → 무한대기 해소

**변경 5: 대시보드 지도 높이 조정**
- `DashboardView.jsx`: narrow 레이아웃 기본 지도 높이 600px → 1000px
- `DashboardView.jsx`: wide 레이아웃 전체 높이 `calc(100vh - 180px)` → `calc(100vh - 140px)`

### A2. 논리적 타당성 검토
- 싱글클릭=더블클릭 통합: InspectorPanel이 더 상세하므로 이를 기준으로 통합하는 것이 합리적
- COG 삭제는 기존 `api.deleteOrthoCog()` 메서드 활용 (F6에서 이미 구현됨)
- 로딩 수정: ortho_path가 null이면 TiTilerOrthoLayer가 렌더되지 않으므로 onLoadComplete 콜백이 호출되지 않음 → isLoading이 영원히 true

### A3. 과도 설계 검토
- 변경 범위: 3개 파일(App.jsx, InspectorPanel.jsx, ProjectMap.jsx) + DashboardView.jsx
- 새 API/DB 변경 없음 (기존 F6의 deleteOrthoCog API 재활용)
- 최소한의 변경으로 요구사항 충족

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
(없음)
