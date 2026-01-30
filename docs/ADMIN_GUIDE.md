# Admin Guide (비공개 관리자용)

이 문서는 민감한 시스템 설정 및 라이선스 관리 정보를 포함하므로 외부에 공개되지 않도록 관리자만 접근해야 합니다.

---

## 💾 MinIO 저장소 관리

### 1. 저장소 위치 설정의 중요성

MinIO는 모든 업로드 파일(원본 이미지, 처리 결과물)을 저장하는 핵심 스토리지입니다.
**디스크 용량이 부족하면 업로드가 완전히 중단**되므로, 반드시 충분한 여유 공간이 있는 드라이브에 설정해야 합니다.

#### 증상: 업로드 실패 (HTTP 507)
```
XMinioStorageFull: Storage backend has reached its minimum free drive threshold.
Please delete a few objects to proceed.
```

MinIO는 기본적으로 **디스크 여유 공간이 10% 이하**로 떨어지면 모든 쓰기 작업을 거부합니다.
이 경우 TUS 서버(tusd)가 MinIO에 청크를 업로드하지 못해 클라이언트에 500 에러가 반환됩니다.

### 2. 환경변수 설정

`.env` 파일에서 MinIO 데이터 경로를 설정합니다:

```bash
# MinIO data path (mapped to /data in minio container)
# Use large storage drive to avoid disk full issues
MINIO_DATA_PATH=/media/innopam/InnoPAM-8TB/data/minio
```

`docker-compose.yml`에서 이 환경변수를 참조합니다:

```yaml
minio:
  volumes:
    - ${MINIO_DATA_PATH:-./data/minio}:/data
```

> ⚠️ 기본값(`./data/minio`)은 루트 디스크에 저장되므로, 프로덕션 환경에서는 반드시 대용량 드라이브 경로를 명시적으로 설정하세요.

### 3. 용량 모니터링

#### 호스트에서 확인
```bash
df -h /media/innopam/InnoPAM-8TB/data/minio
```

#### MinIO 컨테이너 내부에서 확인
```bash
docker exec aerial-survey-manager-minio-1 df -h /data
```

#### MinIO 버킷별 사용량 확인
```bash
docker exec aerial-survey-manager-minio-1 mc alias set local http://localhost:9000 minioadmin <password>
docker exec aerial-survey-manager-minio-1 mc du local/aerial-survey/ --depth 1
```

### 4. 긴급 대응: 공간 부족 시

#### A. 실패한 업로드 파일 정리
TUS 업로드 중 실패한 임시 파일들이 `uploads/` 폴더에 누적됩니다:

```bash
# 업로드 임시 파일 크기 확인
docker exec aerial-survey-manager-minio-1 mc du local/aerial-survey/uploads/

# 삭제 (주의: 현재 업로드 중인 파일도 삭제됨)
docker exec aerial-survey-manager-minio-1 mc rm --recursive --force local/aerial-survey/uploads/
```

#### B. Docker 캐시 정리
```bash
docker system prune -f
```

#### C. 오래된 프로젝트 데이터 정리
```bash
# 특정 프로젝트의 원본 이미지 삭제 (프로젝트 ID 확인 필요)
docker exec aerial-survey-manager-minio-1 mc rm --recursive --force local/aerial-survey/projects/<project-id>/images/
```

### 5. 저장소 마이그레이션 (경로 변경)

기존 데이터를 새 위치로 이동하려면:

```bash
# 1. MinIO 컨테이너 중지
cd /path/to/aerial-survey-manager
docker compose stop minio

# 2. 새 디렉토리 생성 (권한 설정 중요)
sudo mkdir -p /new/path/minio
sudo chown -R 1000:1000 /new/path/minio

# 3. 기존 데이터 복사
sudo docker cp aerial-survey-manager-minio-1:/data/. /new/path/minio/
sudo chown -R 1000:1000 /new/path/minio

# 4. .env 파일 수정
# MINIO_DATA_PATH=/new/path/minio

# 5. 컨테이너 재시작
docker compose up -d minio

# 6. 검증
docker exec aerial-survey-manager-minio-1 mc ls local/aerial-survey/
```

### 6. 권장 디스크 용량

| 항목 | 최소 권장 | 비고 |
|------|----------|------|
| MinIO 저장소 | **1TB 이상** | 원본 이미지 + 처리 결과물 |
| 처리 데이터 | **500GB 이상** | `/data/processing` 경로 |
| 루트 디스크 | 100GB | Docker 이미지, 로그 등 |

> 💡 **팁**: 항공 이미지 1장당 약 50~200MB, 프로젝트당 수백~수천 장을 업로드하므로, 여유롭게 TB 단위 스토리지를 확보하는 것이 좋습니다.

### 7. 프로젝트 삭제 시 스토리지 정리 (2026-01-31)

프로젝트 삭제 시 다음 데이터가 자동으로 삭제됩니다:

| 경로 | 설명 |
|------|------|
| `uploads/{upload_id}` | TUS로 업로드된 원본 이미지 |
| `uploads/{upload_id}.info` | TUS 메타데이터 파일 |
| `projects/{project_id}/thumbnails/` | 생성된 썸네일 |
| `projects/{project_id}/ortho/` | 정사영상 결과물 |
| `/data/processing/{project_id}/` | 로컬 처리 캐시 |

> ⚠️ **주의**: 2026-01-31 이전 버전에서는 `uploads/` 경로의 원본 이미지가 삭제되지 않아 스토리지가 누적되는 버그가 있었습니다. 해당 버전을 사용 중이라면 수동으로 정리하거나 최신 버전으로 업데이트하세요.

---

## 🔑 Metashape Licensing Management

`worker-metashape` 컨테이너의 라이선스 관리 전략에 대한 상세 기술 문서입니다.

### 1. Persistence Strategy (불사조 전략)
Docker 환경 특성상 컨테이너가 빈번하게 생성/삭제되므로, 라이선스 유실 방지를 위해 다음 두 가지 방어 기제를 적용했습니다.

#### A. MAC 주소 고정 (Static ID)
Agisoft의 Node-Locked 라이선스는 기기의 MAC 주소를 "Machine ID"로 사용합니다. 컨테이너가 변경되어도 동일 기기로 인식되도록 강제합니다.
- **설정 파일**: `docker-compose.yml`
- **적용 값**: `mac_address: "02:42:AC:17:00:64"`
- **주의**: 이 값을 변경하면 Agisoft 서버는 이를 "새로운 컴퓨터"로 인식하여 라이선스 재인증을 요구합니다. 절대 임의 변경하지 마세요.

#### B. 라이선스 파일 이중 저장 (Volume Mount)
Metashape 엔진이 로컬에 저장하는 라이선스 파일(`.lic`)을 영구 보존하기 위해 네임드 볼륨에 마운트합니다.
- **볼륨명**: `metashape-license`
- **컨테이너 내부 경로**: `/var/tmp/agisoft/licensing` (Metashape 2.2.0 기준)

### 2. Troubleshooting: "Key Already In Use"
만약 라이선스 오류(`Activation key is already in use`)가 발생한다면, 이는 **현재 컨테이너의 상태와 Agisoft 서버의 기록이 불일치**하기 때문입니다.

#### 해결 절차
1. **Agisoft Support Contact**: 기술지원팀에 해당 라이선스 키의 "Deactivation(초기화)"를 요청합니다.
   - 사유: "Docker 컨테이너 교체 중 기존 인스턴스 소실로 인한 재설정"
2. **Force Recreate**: 리셋 승인 후, 컨테이너를 강제로 재생성하여 정해진 MAC 주소로 다시 시작합니다.
   ```bash
   docker-compose up -d --force-recreate worker-metashape
   ```
3. **수동 활성화**: 컨테이너 시작 후 `activate.py`를 실행하여 라이선스를 활성화합니다.
   ```bash
   docker exec worker-metashape python3 /app/engines/metashape/dags/metashape/activate.py
   ```
   성공 시 `.lic` 파일이 `/var/tmp/agisoft/licensing/licenses/` 폴더에 생성되며, 이후에는 영구적으로 유지됩니다.

### 3. 수동 복구 (Manual Recovery)
컨테이너가 실수로 삭제되었으나 라이선스를 다른 물리 서버로 옮기고 싶은 경우:
1. `docker-compose.yml`에 정의된 것과 동일한 MAC 주소로 임시 컨테이너를 실행합니다.
2. `deactivate.py`를 실행하여 명시적으로 라이선스를 반납합니다.
   ```bash
   docker exec worker-metashape python3 /app/engines/metashape/dags/metashape/deactivate.py
   ```

---

## 처리 진행 상태 캐시 (운영/디버깅)

처리 화면 재진입 시 마지막 단계 메시지와 진행률을 즉시 복구하기 위해,
워커가 처리 상태를 파일로 캐시합니다.

- 경로: `/data/processing/{project_id}/processing_status.json`
- 예시 내용:
  ```json
  {"status":"processing","progress":42,"message":"이미지 정렬 (Align Photos)","updated_at":"..."}
  ```

## Known Issue: 취소 후 재시작 오류

- 동일 프로젝트에서 **처리 중단 직후 재시작**할 경우 Metashape 파이프라인에서 `Empty DEM` 등의 오류가 발생할 수 있습니다.
- 이 경우 EO 파일명 매칭 실패/metadata.txt 불일치 가능성이 높으므로, 아래를 우선 확인하세요:
  - `/data/processing/{project_id}/images/metadata.txt`의 이미지 파일명과 실제 이미지 파일명이 일치하는지
  - `worker-metashape` 로그에서 `reference_normalized.txt exists=True` 여부
  - 필요 시 EO 재업로드 또는 프로젝트 재생성
