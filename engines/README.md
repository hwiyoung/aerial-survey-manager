# Engines Directory (Monorepo)

이 디렉토리는 Aerial Survey Manager 플랫폼에 통합된 모든 처리 엔진을 관리합니다.

## 디렉토리 구조

- `/engines/odm`: OpenDroneMap 관련 설정 및 커스텀 스크립트가 위치합니다. (Docker 기반으로 동작)
- `/engines/metashape`: Agisoft Metashape 기반의 고성능 엔진입니다. 전용 GPU 워커를 통해 NVIDIA 가속 연산을 수행하며, 라이선스 영속화 볼륨을 사용합니다.
- `/engines/external-engine`: 사용자가 가져온 외부 처리 엔진 코드(FastAPI, Flask 등)가 위치하는 곳입니다.

## 통합 및 배포 가이드

1. **코드 배치**: 외부 엔진의 소스 코드를 `/engines/external-engine` 디렉토리에 복사하거나, Metashape 스크립트를 `/engines/metashape/dags`에 구성하십시오.
2. **Docker 통합**: `docker-compose.yml`에서 해당 디렉토리를 빌드 컨텍스트로 사용하거나 볼륨으로 마운트하여 하나의 환경으로 배포할 수 있습니다.
3. **통신**: 플랫폼 백엔드와 외부 엔진은 Celery 큐(Redis) 또는 Docker 내부 네트워크를 통해 통신합니다. (예: `metashape` 큐, `http://external-engine:5000`)

## Metashape EO Reference 처리

- EO 업로드 시 파싱된 데이터가 자동으로 `data/processing/{project_id}/images/metadata.txt`에 저장됩니다.
- Metashape `align_photos.py`는 위 파일을 우선 탐색해 `importReference`에 사용합니다.
- `metadata.txt`는 **이미지 파일명과 매칭된 행만** 저장됩니다. 매칭이 0건이면 `importReference`가 수행되지 않습니다.
- 매칭이 실패하면 `reference_normalized.txt`가 생성되지 않으며, 이후 DEM 단계에서 `Empty DEM` 오류가 발생할 수 있습니다.
- 필요 시 명시 경로를 사용하려면:
  - 스크립트 인자: `--reference_path /path/to/eo.txt`
  - 환경변수: `EO_REFERENCE_PATH` 또는 `METASHAPE_REFERENCE_PATH`

## Metashape 출력 파일 (GSD 이름 복사)

- 기본값: 비활성화
- 활성화하려면 `EXPORT_GSD_COPY=true` 환경변수를 설정하세요.
- 활성화 시 `result.tif_1_78cm.tif` 같은 GSD 표기 복사본이 생성됩니다.

## Metashape 출력 좌표계 (2026-02-04)

정사영상 생성 시 **출력 좌표계가 입력 좌표계와 동일하게** 자동 설정됩니다.

### 동작 방식

1. `align_photos.py`에서 EO reference 파일의 EPSG를 감지하여 `chunk.crs` 설정
2. `build_orthomosaic.py`에서 프로젝트의 `chunk.crs`를 그대로 사용하여 정사영상 내보내기
3. 별도의 `output_crs` 프리셋 설정 없이 입력 데이터의 좌표계 유지

### 관련 코드

```python
# build_orthomosaic.py
doc = Metashape.Document()
doc.open(output_path + '/project.psx')
chunk = doc.chunk

# 출력 좌표계를 프로젝트에 설정된 입력 좌표계와 동일하게 사용
proj = Metashape.OrthoProjection()
proj.crs = chunk.crs
print(f"출력 좌표계: {chunk.crs} (입력 좌표계와 동일)")
```

### 이점

- **좌표 변환 오류 방지**: 입력/출력 좌표계 불일치로 인한 정밀도 손실 없음
- **설정 간소화**: 프리셋에서 `output_crs` 설정 불필요
- **유연성**: EO 파일의 좌표계에 따라 자동 적용

## Metashape COG 변환 (2026-02-04)

처리 완료 후 `result.tif`를 Cloud Optimized GeoTIFF(COG)로 변환합니다.

### 원본 GSD 유지

COG 변환 시 **원본 정사영상의 해상도(GSD)가 그대로 유지**됩니다:

```bash
# 변환 명령 (TILING_SCHEME 제거로 원본 GSD 유지)
gdal_translate \
  -of COG \
  -co COMPRESS=LZW \
  -co BLOCKSIZE=256 \
  -co OVERVIEW_RESAMPLING=AVERAGE \
  -co BIGTIFF=YES \
  result.tif result_cog.tif
```

> ⚠️ 이전에는 `TILING_SCHEME=GoogleMapsCompatible` 옵션이 있어 GSD가 Google Maps 타일 스킴에 맞게 변경되었으나, 2026-02-04부터 제거되어 원본 해상도를 유지합니다.

---
*Created on 2026-01-27 / Updated on 2026-02-04*
