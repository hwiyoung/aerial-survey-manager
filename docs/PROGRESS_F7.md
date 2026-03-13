# 작업 진행 상황

> 완료된 작업: [PROGRESS_F2.md](PROGRESS_F2.md) · [PROGRESS_F3.md](PROGRESS_F3.md)

## F7. 대시보드/처리화면 베이스맵 on/off 토글 - 2026-03-13

### 요구사항
대시보드(FootprintMap)와 처리화면(ProjectMap)에 표출되는 베이스맵 레이어를 껐다 켤 수 있게 한다.
정사영상 위에 베이스맵이 불필요하거나 방해되는 경우 끌 수 있다.

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
- [ ] 🚪 변경사항 보고
- [ ] D1. UX 관점 검토
- [ ] D2. 전체 변경사항 통합 검토
- [ ] D3. 배포 가능성 판단
- [ ] 🚪 최종 승인
- [ ] D4. 커밋 및 PR

### A1. 구현 계획

#### 기존 코드 현황
- **FootprintMap.jsx**: TileLayer 고정 렌더링 (955-966행). FootprintMapHeader에 "촬영 영역"/"권역" 토글 버튼 이미 존재 (696-711행)
- **ProjectMap.jsx**: TileLayer 고정 렌더링 (71-77행). 레이어 컨트롤 UI 없음
- **mapConfig.js**: `getTileConfig()`로 오프라인/온라인 설정 반환

#### 변경 파일 (2개, FE만)

**1. `src/components/Dashboard/FootprintMap.jsx`**
- `showBasemap` 상태 추가 (기본값: localStorage에서 읽거나 `true`)
- FootprintMapHeader에 "배경지도" 토글 버튼 추가 (기존 "촬영 영역"/"권역" 버튼과 동일 패턴)
- TileLayer를 `showBasemap` 조건부 렌더링

**2. `src/components/Project/ProjectMap.jsx`**
- `showBasemap` 상태 추가 (동일 localStorage 키 사용)
- 지도 위 플로팅 토글 버튼 추가 (우상단)
- TileLayer를 `showBasemap` 조건부 렌더링

#### 공통 사항
- localStorage 키: `basemap_visible` (두 화면 공유 → 새로고침 시 동기화)
- 토글 방식: 조건부 렌더링 (`{showBasemap && <TileLayer .../>}`)
- 아이콘: lucide-react의 `Map` / `MapOff` 또는 기존 `Eye`/`EyeOff` 패턴 활용

### A2. 계획 검토 결과
- 조건부 렌더링이 opacity 0보다 나음: 불필요한 타일 요청 방지
- localStorage 동기화: 같은 키를 쓰므로 대시보드에서 끄면 처리화면 진입 시에도 꺼진 상태. 단, 같은 페이지에서 두 컴포넌트가 동시 마운트되진 않으므로 실시간 동기화 불필요
- 백엔드 변경 없음 — 순수 프론트엔드 작업
- 기존 토글 버튼 패턴을 그대로 따르므로 UI 일관성 유지

### A3. 과도 설계 검토 결과
- 별도 `BasemapToggle` 공통 컴포넌트 분리: 두 곳의 UI 배치가 다름 (헤더 바 vs 플로팅 버튼). 공통 컴포넌트로 묶으면 오히려 복잡해짐 → 각각 인라인 구현이 적절
- React Context로 상태 공유: 두 맵이 동시 렌더링되지 않으므로 localStorage로 충분
- 베이스맵 opacity 슬라이더: 요구사항은 on/off뿐. 슬라이더는 불필요

### 회귀 기록
(없음)

### 발견된 이슈 및 결정사항
(없음)
