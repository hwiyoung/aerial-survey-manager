# 작업 진행 기록 — F5

## F5: 도엽 단위 클립+머지 기능 - 2026-03-16
### 요구사항
- 정사영상을 국가 표준 도엽(지도 격자) 단위로 잘라내기(클립)
- 여러 프로젝트의 정사영상을 하나의 도엽 범위로 합치기(머지)
- 도엽 격자를 지도에 오버레이 표시
- 도엽번호 입력으로 해당 도엽 위치로 이동
- 1:5,000 및 1:1,000 축척 모두 지원
- 납품/검수 시 도엽 단위 산출물 요구 대응

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
- [x] D1. UX 관점 검토 — 사용자 피드백 반영 (아래 F5-B 참조)
- [x] D2. 전체 변경사항 통합 검토 — 미사용 import 정리, 축척 변경 시 searchResult 초기화
- [x] D3. 배포 가능성 판단 — OK
- [ ] 🚪 최종 승인
- [ ] D4. 커밋

### 구현 계획

#### 기존 자산
- **도엽 격자 데이터** (경로: `data/`, 파일명 패턴: `TN_MAPINDX_{scale}K_5179.geojson`)
  - `TN_MAPINDX_5K_5179.geojson` — 1:5,000 (17,661개 피쳐, 7.5MB)
  - `TN_MAPINDX_1K_5179.geojson` — 1:1,000 (441,354개 피쳐, 190MB)
  - 공통 속성: `MAPIDCD_NO`(도엽번호), `MAPID_NM`(도엽명), `id`, `fid`
  - CRS: EPSG:5179, Geometry: Polygon
- **GDAL 유틸**: `gdalwarp`, `gdal_translate` 사용 가능 (download.py에 `_warp_if_needed()` 패턴 존재)
- **다운로드 토큰 시스템**: `create_download_token()` → `GET /batch/{download_id}` 패턴 재활용 가능
- **기존 내보내기 UI**: ExportDialog에 포맷/CRS/GSD 설정 + 다운로드 흐름 구현됨

#### BE-1. 도엽 격자 서빙 API (다중 축척 지원)
- **파일**: `backend/app/api/v1/sheets.py` (신규)
- **도엽 데이터 로더**: 경량 인덱스 방식
  - 서버 시작 시 GeoJSON에서 **bounds만 추출**하여 메모리 캐싱
    - 5K: 17K 피쳐 × bounds(4 float) ≈ ~0.5MB
    - 1K: 441K 피쳐 × bounds(4 float) ≈ ~14MB
    - 원본 GeoJSON 190MB를 메모리에 올리지 않음
  - `{mapid: {bounds_5179, bounds_wgs84, name}}` 딕셔너리 + STRtree
  - 파일명 패턴: `data/TN_MAPINDX_{scale}K_5179.geojson`
  - 파일 없으면 해당 축척 비활성화 (에러 아님)
- **Spatial index**: 축척별 shapely STRtree 구축
- `GET /api/v1/sheets?scale=5000&bounds=minlat,minlon,maxlat,maxlon`
  - WGS84 bounds → EPSG:5179 변환 → STRtree 교차 검색
  - 응답: `{ sheets: [{id, mapid, bounds_wgs84, resolution, region}], scale }`
- `GET /api/v1/sheets/search?mapid=37806043`
  - 도엽번호로 검색 → 해당 도엽의 bounds_wgs84 반환
  - 축척 자동 판별 (번호 길이 또는 전수 검색)
- `GET /api/v1/sheets/scales`
  - 현재 사용 가능한 축척 목록 반환 (데이터 보유 여부 기반)

#### BE-2. 도엽 클립 내보내기 API (Celery 비동기)
- **파일**: `backend/app/api/v1/download.py`에 추가, `backend/app/workers/tasks.py`에 태스크 추가
- `POST /api/v1/download/clip`
  - Input: `{ project_ids, sheet_ids, scale, crs, gsd }`
  - **단일 도엽 (1개 프로젝트 × 1개 도엽)**: 동기 처리 → 즉시 download_id 반환
  - **다중 도엽 배치**: Celery 태스크로 비동기 처리
    - 태스크 ID 반환 → 프론트에서 폴링으로 완료 확인
    - 완료 시 download_id 생성
  - 클립 로직:
    1. 도엽 bounds를 타겟 CRS로 변환 (pyproj)
    2. `gdalwarp -t_srs {crs} -te {minx} {miny} {maxx} {maxy} -r bilinear -co COMPRESS=LZW`
    3. 결과 파일명: `{도엽번호}_{프로젝트명}.tif`
  - 다중 결과물 → ZIP 패킹
  - 기존 `create_download_token()` 시스템 재활용

#### BE-3. 도엽 머지 내보내기 API
- **파일**: `backend/app/api/v1/download.py`에 추가
- `POST /api/v1/download/merge`
  - Input: `{ project_ids, sheet_id, scale, crs, gsd }`
  - 여러 프로젝트의 COG를 하나의 도엽 범위로 합치기:
    1. 각 COG에서 도엽 범위 클립 (gdalwarp -te)
    2. 클립된 파일들을 gdalwarp로 모자이킹 (마지막 입력 우선)
    3. 결과: 단일 GeoTIFF
  - 기존 `create_download_token()` 시스템 재활용

#### FE-1. 도엽 격자 오버레이 컴포넌트
- **파일**: `src/components/Project/SheetGridOverlay.jsx` (신규)
- Leaflet `Rectangle`로 도엽 경계 표시
- 도엽 번호 라벨 (`Tooltip`)
- 정사영상 영역과 겹치는 도엽만 로드 (API 호출)
- 선택/해제 토글 (클릭)
- 선택된 도엽 하이라이트 (색상 변경)
- 축척 선택 드롭다운 (1:5,000 / 1:1,000) — 사용 가능한 축척만 표시

#### FE-2. 도엽번호 검색 및 이동 기능
- **파일**: `src/components/Project/SheetGridOverlay.jsx` 또는 InspectorPanel에 통합
- 도엽번호 입력 필드 + 검색 버튼
- 입력한 도엽번호의 bounds로 `map.fitBounds()` 호출
- 해당 도엽 자동 하이라이트 + 선택
- 존재하지 않는 번호 입력 시 "도엽을 찾을 수 없습니다" 안내

#### FE-3. InspectorPanel → FootprintMap 도엽 UI 이동 (F5-B)
- **파일**: `src/components/Dashboard/FootprintMap.jsx`에 추가
- 지도 헤더에 도엽 토글 버튼
- 지도 위 플로팅 컨트롤 패널 (SheetControlPanel)
- 축척 선택, 도엽번호 검색, 겹치는 도엽 목록, 클립+머지 버튼
- InspectorPanel의 도엽 섹션 제거

#### FE-4. API 클라이언트 확장
- **파일**: `src/api/client.js`
- `getSheets(scale, bounds)` — 도엽 목록 조회
- `searchSheet(mapid)` — 도엽번호 검색
- `getAvailableScales()` — 사용 가능 축척 조회
- `clipExport(projectIds, sheetIds, options)` — 도엽 클립 내보내기
- `mergeExport(projectIds, sheetId, options)` — 도엽 머지 내보내기
- `getClipTaskStatus(taskId)` — 배치 클립 진행 상태 조회

### 성능 분석 및 대응
| 시나리오 | 예상 소요 | 처리 방식 |
|----------|----------|----------|
| 1도엽 × 1프로젝트 (1:1,000) | 3~10초 | 동기 |
| 1도엽 × 1프로젝트 (1:5,000) | 20~60초 | 동기 (timeout 주의) |
| 10도엽 배치 (1:1,000) | 30초~2분 | Celery 비동기 |
| 10도엽 배치 (1:5,000) | 3~10분 | Celery 비동기 |
| 머지 (3프로젝트 × 1도엽) | 1~3분 | Celery 비동기 |

- **동기/비동기 자동 판별**: 도엽 1개 × 프로젝트 1개이면 동기, 그 외 비동기
- **COG 최적화**: COG 내부 타일 구조 덕에 전체 파일 읽기 불필요 (읽기는 빠름, 쓰기가 병목)
- **Celery 태스크**: 기존 `celery` 큐 사용 (metashape 큐와 분리)

### A2. 논리적 타당성 검토
- **경량 인덱스**: 190MB GeoJSON을 전체 로드하지 않고 bounds만 추출 → ~14MB 메모리. STRtree로 밀리초 교차 검색
- **다중 축척 확장성**: `TN_MAPINDX_{scale}K_5179.geojson` 패턴으로 자동 인식
- **좌표 변환 체인**: GeoJSON(EPSG:5179) → API 응답(WGS84) → 클립 시 타겟 CRS. pyproj Transformer로 정확
- **gdalwarp -te 방식**: 직사각형 도엽이므로 -cutline 대신 -te 사용 (더 빠르고 간단)
- **동기/비동기 분기**: 단일 도엽은 동기로 즉시 반환 (UX 좋음), 배치는 Celery로 백그라운드 처리 (안정성)
- **도엽번호 검색**: 전수 검색이지만 17K~170K 항목에서 딕셔너리 O(1) 조회 가능 (mapid를 키로 인덱싱)

### A3. 과도 설계 검토
- ✅ **DB 테이블 불필요**: bounds-only 메모리 캐시 + STRtree (5K ~0.5MB, 1K ~14MB)
- ✅ **원본 GeoJSON 메모리 미적재**: 190MB를 통째로 올리지 않고 bounds만 추출
- ✅ **WebSocket 불필요**: 배치 처리는 HTTP 폴링으로 충분 (기존 패턴)
- ✅ **결과 만료 정책 불필요**: 기존 1회 다운로드 후 임시 파일 자동 삭제
- ✅ **겹침 영역 정책 UI 불필요**: gdalwarp 기본 동작(마지막 우선)으로 충분
- ✅ **Celery 도입 범위 최소화**: 기존 celery 큐 + 단순 태스크 1개 추가만

### 변경 파일 목록
| 파일 | 변경 유형 |
|------|----------|
| `backend/app/api/v1/sheets.py` | 신규 — 도엽 조회/검색 API |
| `backend/app/api/v1/download.py` | 수정 — 클립/머지 API 추가 |
| `backend/app/api/v1/__init__.py` | 수정 — sheets 라우터 등록 |
| `backend/app/main.py` | 수정 — sheets 라우터 등록 |
| `src/components/Project/SheetGridOverlay.jsx` | 신규 — 도엽 격자 오버레이 |
| `src/components/Dashboard/FootprintMap.jsx` | 수정 — 도엽 UI (헤더버튼, 플로팅패널) |
| `src/components/Dashboard/DashboardView.jsx` | 수정 — sheet props 전달 |
| `src/components/Project/InspectorPanel.jsx` | 수정 — 도엽 섹션 제거 |
| `src/App.jsx` | 수정 — sheetState 관리 |
| `src/api/client.js` | 수정 — 도엽 관련 API 메서드 |

### 회귀 기록
🔄 A1으로 회귀: 1:1,000 지원, 도엽번호 검색/이동 기능, 대용량 클립 비동기 처리 반영

### 발견된 이슈 및 결정사항
- 도엽 데이터 확보 완료: `data/TN_MAPINDX_{1K,5K}_5179.geojson` (통일된 패턴)
- 1K 파일 190MB → bounds-only 캐시로 ~14MB 메모리만 사용
- 두 파일 모두 동일 속성 구조: `MAPIDCD_NO`, `MAPID_NM`, `id`, `fid` + EPSG:5179 Polygon
- GeoJSON CRS가 EPSG:5179 → API 응답은 WGS84로 변환 필요
- 대용량 정사영상 클립 시 1:5,000 도엽 1개당 20~60초 소요 → 배치는 Celery 비동기 처리
- 도엽번호 검색은 메모리 딕셔너리로 O(1) 조회

---

## F5-B: 도엽 UI 개선 (지도 상단 이동 + 머지) — 2026-03-16

### 사용자 피드백
1. 도엽 선택을 촬영영역/권역 버튼처럼 **지도 상단 헤더에 배치**
2. 눌렀을 때 **지도 위에서 직접 도엽 선택** 가능하게
3. **도엽 머지(합치기) 기능** 추가

### 진행 체크리스트
- [x] A1. 계획 수립
- [x] A2/A3. 검토
- [x] 🚪 사용자 승인
- [x] B1. FootprintMapHeader에 도엽 토글 버튼 추가
- [x] B2. 지도 위 플로팅 도엽 컨트롤 패널 구현 (SheetControlPanel)
- [x] B3. 머지 내보내기 버튼 추가 (클립 + 머지 2개 버튼)
- [x] B4. InspectorPanel 도엽 섹션 제거
- [x] B5. 지도 클릭으로 도엽 직접 선택 (Canvas 렌더러 우회 — map.on('click') + bounds 판정)
- [x] B6. 뷰포트 기반 도엽 로드 (프로젝트 미선택 시)
- [x] B7. 축척별 줌 레벨 제한 (1:1000→줌14, 1:5000→줌12) + 백엔드 200개 제한 → 버벅임 해결
- [x] B8. 겹치는 도엽 목록 좌상단→우하단 정렬 (위도↓ 경도→)
- [x] B9. 도엽/촬영영역 버튼 상호 배타 (도엽 ON→촬영영역 OFF, 반대도 동일)
- [x] C1~C5. 코드 품질 검토
- [x] 🚪 변경사항 보고
- [x] D1~D3. 최종 검증
- [ ] 🚪 최종 승인
- [ ] D4. 커밋

### 구현 변경 파일
| 파일 | 변경 |
|---|---|
| `FootprintMap.jsx` | Header에 도엽 버튼, 플로팅 패널, 도엽/촬영영역 상호배타, 도엽 정렬 |
| `SheetGridOverlay.jsx` | map.on('click') 기반 선택, 줌 레벨 제한, truncated 경고 |
| `InspectorPanel.jsx` | 도엽 섹션 제거 (지도로 이동) |
| `backend/sheets.py` | 최대 200개 제한 + truncated 플래그 |

### 발견된 이슈 및 결정사항
- Canvas 렌더러(`preferCanvas={true}`) 환경에서 Rectangle 클릭 이벤트 미동작 → `map.on('click')` + bounds 판정으로 우회
- 뷰포트 기반 도엽 로드 시 1:1000/1:5000에서 수백~수천 개 렌더링으로 버벅임 → 줌 레벨 제한 + 백엔드 200개 캡
