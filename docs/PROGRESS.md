# 작업 진행 상황

> 완료된 작업: [PROGRESS_F2.md](PROGRESS_F2.md) · [PROGRESS_F3.md](PROGRESS_F3.md) · [PROGRESS_F7.md](PROGRESS_F7.md)

## F8. 처리화면 지도 뷰 자유 이동 및 원래 범위 복귀 버튼 - 2026-03-13

### 요구사항
처리화면에서 지도 뷰포인트가 정사영상 바운더리에 고정되어 주변 이동이 불가능한 문제 해결.
사용자가 자유롭게 이동/축소확대 가능하게 하고, 버튼으로 원래 정사영상 범위로 복귀.

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
- [ ] 🚪 최종 승인
- [ ] D4. 커밋 및 PR

### A1. 구현 계획

#### 원인 분석
- `FitBounds` 컴포넌트: `images`, `projectBounds` 의존성으로 useEffect 실행
- `project` 객체가 폴링/상태변경으로 재생성되면 `images` 참조도 변경 → fitBounds 반복 실행
- `TiTilerOrthoLayer`도 로드 완료 시 `map.fitBounds()` 호출
- 결과: 사용자가 패닝해도 다시 원래 범위로 되돌아감

#### 변경 파일 (1개, FE만)

**`src/components/Project/ProjectMap.jsx`**
1. `FitBounds` 수정: `projectId`별 1회만 fitBounds 실행 (ref로 추적)
2. `MapRefSetter` 헬퍼: MapContainer 내부 map 인스턴스를 외부 ref에 노출
3. "원래 범위로" 플로팅 버튼 추가 (Crosshair 아이콘 40px, 배경지도 토글 아래)

### A2. 계획 검토 결과
- FitBounds를 projectId별 1회만 실행 → 프로젝트 전환 시 정상 fitBounds, 같은 프로젝트 내 패닝 시 재설정 안됨
- TiTilerOrthoLayer의 fitBounds는 fittedBoundsRef로 이미 관리됨 → 추가 수정 불필요

### A3. 과도 설계 검토 결과
- 변경 파일 1개, 최소 변경 — 과도하지 않음

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
(없음)
