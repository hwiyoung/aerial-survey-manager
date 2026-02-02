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

## 📝 Docker 로그 관리

### 1. 로그 로테이션 설정

모든 컨테이너에 로그 로테이션이 설정되어 있습니다 (`docker-compose.yml`):

```yaml
# 기본 설정 (대부분의 서비스)
x-logging: &default-logging
  driver: "json-file"
  options:
    max-size: "10m"   # 로그 파일당 최대 10MB
    max-file: "3"     # 최대 3개 파일 유지 (총 30MB)

# 처리 워커용 설정 (디버깅 중요)
x-logging-worker: &worker-logging
  driver: "json-file"
  options:
    max-size: "50m"   # 로그 파일당 최대 50MB
    max-file: "5"     # 최대 5개 파일 유지 (총 250MB)
```

| 서비스 유형 | 로그 설정 | 최대 용량 | 적용 대상 |
|------------|---------|----------|---------|
| 기본 | `*default-logging` | 30MB | frontend, api, celery-beat, db, redis, minio, nginx, flower |
| 처리 워커 | `*worker-logging` | 250MB | worker-metashape, worker-odm, tusd |

> 💡 **팁**: 처리 워커는 이미지 처리 시 상세한 로그를 남기므로, 오류 분석을 위해 더 큰 로그 용량을 확보합니다.

### 2. 로그 확인 명령어

```bash
# 특정 컨테이너 로그 보기
docker logs aerial-survey-manager-api-1 --tail 100

# 실시간 로그 스트리밍
docker logs -f aerial-survey-manager-worker-metashape-1

# 로그 파일 크기 확인
du -sh /var/lib/docker/containers/*/
```

### 3. 수동 로그 정리

```bash
# 특정 컨테이너 로그 비우기 (컨테이너 실행 중에도 가능)
sudo truncate -s 0 $(docker inspect --format='{{.LogPath}}' aerial-survey-manager-api-1)

# 모든 컨테이너 로그 비우기
docker ps -q | xargs -I {} sh -c 'sudo truncate -s 0 $(docker inspect --format="{{.LogPath}}" {})'
```

### 4. Docker 시스템 정리

```bash
# 미사용 이미지, 컨테이너, 볼륨 정리
docker system prune -f

# 더 공격적인 정리 (미사용 볼륨 포함)
docker system prune -af --volumes

# Docker 사용량 확인
docker system df
```

### 5. 자동 정리 크론잡 (선택사항)

```bash
# /etc/cron.weekly/docker-cleanup 파일 생성
#!/bin/bash
docker system prune -f
```

> 💡 **팁**: 로그 로테이션 설정이 적용되려면 컨테이너를 재생성해야 합니다:
> ```bash
> docker compose down && docker compose up -d
> ```

---

## 📤 중단된 업로드 처리 (2026-02-02)

### 1. 업로드 중단 원인

업로드가 중단될 수 있는 상황:
- 브라우저 새로고침/종료
- 페이지 이탈 (뒤로가기, 로고 클릭 등)
- 네트워크 연결 끊김
- 시스템 재부팅

### 2. 업로드 상태 확인

```bash
# 모든 uploading 상태 이미지 조회
docker exec aerial-survey-manager-db-1 psql -U postgres -d aerial_survey -c \
  "SELECT project_id, filename, upload_status, created_at FROM images WHERE upload_status = 'uploading';"
```

### 3. 중단된 업로드 복구

중단된 업로드는 자동으로 복구되지 않습니다. 다음 두 가지 방법 중 선택하세요:

#### A. 완료된 이미지만으로 처리 진행

프론트엔드에서 처리 시작 시 확인 다이얼로그가 표시됩니다:
- "완료된 N개 이미지만으로 처리를 진행하시겠습니까?"
- 확인 선택 시 `force=true` 파라미터로 처리 시작

#### B. 수동으로 상태 변경 후 재업로드

```bash
# 특정 프로젝트의 uploading 상태를 interrupted로 변경
docker exec aerial-survey-manager-db-1 psql -U postgres -d aerial_survey -c \
  "UPDATE images SET upload_status = 'interrupted' WHERE upload_status = 'uploading' AND project_id = '<project-id>';"
```

변경 후 사용자에게 이미지 재업로드를 안내하세요.

### 4. Stale 업로드 감지 기준

시스템은 `created_at`이 **1시간 이전**인 `uploading` 상태 이미지를 "stale"로 판단합니다.
- 이러한 이미지는 처리 시작 시 사용자에게 안내 메시지를 표시
- 사용자가 확인 후 진행 여부를 선택할 수 있음

### 5. 글로벌 업로드 시스템 (2026-02-02 업데이트)

프론트엔드에서는 업로드 중에도 앱 내 자유로운 네비게이션을 지원합니다:
- **앱 내 네비게이션**: 업로드 중에도 대시보드, 다른 프로젝트로 이동 가능 (업로드 계속 진행)
- **업로드 패널 글로벌 표시**: 어느 화면에서든 업로드 진행률 패널이 우측 하단에 표시됨
- **브라우저 종료/새로고침**: `beforeunload` 이벤트로 경고 표시 (실제 페이지 이탈 시에만)
- 브라우저를 완전히 닫거나 새로고침하면 업로드가 중단됨

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

---

## 📤 업로드 상태 검증 (2026-02-02)

### 1. 업로드 상태 자동 검증

처리 시작 시 이미지 업로드 상태를 자동으로 검증합니다:

| 상태 | 설명 | 처리 방식 |
|------|------|----------|
| `completed` | 업로드 완료 | 정상 처리 |
| `uploading` (최근) | 업로드 진행 중 | 처리 차단, 완료 대기 요청 |
| `uploading` (1시간 이상) | 업로드 중단됨 | 사용자 확인 후 진행 가능 |
| `failed` | 업로드 실패 | 사용자 확인 후 진행 가능 |

### 2. 사용자 확인 플로우

불완전한 업로드가 감지되면:

1. **업로드 완료 시**: 실패한 이미지가 있으면 즉시 알림 표시
2. **처리 시작 시**: 확인 다이얼로그 표시
   - "완료된 N개 이미지만으로 처리를 진행하시겠습니까?"
   - 확인 시 `force=true` 파라미터로 처리 진행
   - 취소 시 처리 중단

### 3. Stale 업로드 기준

- **1시간 기준**: `created_at`이 1시간 이전인 `uploading` 상태 이미지
- **원인**: 네트워크 단절, 브라우저 종료, 페이지 이탈 등
- **대응**: 사용자에게 상황 안내 후 진행 여부 선택권 제공

### 4. 관련 API 파라미터

```
POST /api/v1/processing/projects/{project_id}/start?force=true
```

- `force=false` (기본값): 불완전한 업로드 시 409 Conflict 반환
- `force=true`: 완료된 이미지만으로 처리 강제 진행

---

## 🔍 Metashape 디버깅 (2026-02-02)

### 1. Alignment 결과 로깅

처리 로그에서 카메라 정렬 결과를 확인할 수 있습니다:

```
📊 Alignment 결과: 520/528 카메라 정렬됨 (98.5%)
⚠️ 정렬 실패 카메라 (8개):
   - DJI_0123.JPG
   - DJI_0124.JPG
   ...
```

### 2. project.files 조건부 보존

처리 결과에 문제가 있을 경우 디버깅을 위해 프로젝트 파일이 보존됩니다:

| 조건 | 삭제 여부 | 이유 |
|------|----------|------|
| 처리 성공 + 정렬률 95% 이상 | ✅ 삭제 | 정상 완료 |
| 처리 실패 또는 정렬률 95% 미만 | ❌ 보존 | 디버깅 필요 |

보존된 파일 위치: `/data/processing/{project_id}/project.files/`

### 3. 로그 출력량 최적화

Metashape 워커 로그는 10% 단위로만 출력됩니다:
```
   Align Photos: 10%
   Align Photos: 20%
   ...
```
