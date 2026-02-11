# Admin Guide (비공개 관리자용)

이 문서는 민감한 시스템 설정 및 라이선스 관리 정보를 포함하므로 외부에 공개되지 않도록 관리자만 접근해야 합니다.

---

## 📦 배포 패키지 생성 (2026-02-06 업데이트)

### 1. 개요

외부 기관에 배포할 패키지를 생성하는 절차입니다. **개발 PC**에서 실행합니다.

### 2. 배포 패키지 빌드

```bash
# 버전을 지정하여 빌드 (예: v1.0.3)
./scripts/build-release.sh v1.0.3
```

빌드 스크립트가 **자동으로** 다음 작업을 수행합니다:
1. 기존 **배포 이미지만** 삭제 (개발 이미지 `aerial-survey-manager-*`는 유지)
2. 별도 프로젝트명(`aerial-prod`)으로 프로덕션 이미지 빌드
3. `--no-cache` 옵션으로 항상 최신 코드 반영
4. `--profile engine` 옵션으로 worker-engine 포함
5. Python 소스코드(.py)를 바이트코드(.pyc)로 컴파일 후 소스 제거

> ℹ️ **개발 환경 영향 없음**: 배포 빌드는 `aerial-prod-*` 이미지를 사용하므로 개발용 이미지(`aerial-survey-manager-*`)는 그대로 유지됩니다.

### 3. 빌드 결과 확인

```bash
# 이미지 생성 시간 확인 (방금 만들어졌는지)
docker images | grep aerial-prod

# .pyc만 있는지 확인 (핵심!)
docker run --rm aerial-prod-worker-engine:latest ls -la /app/engines/metashape/dags/metashape/

# .py 파일 없는지 확인 (결과 비어있어야 정상)
docker run --rm aerial-prod-worker-engine:latest find /app/engines -name "*.py" -type f

# .pyc 파일 있는지 확인 (파일 목록 나와야 정상)
docker run --rm aerial-prod-worker-engine:latest find /app/engines -name "*.pyc" -type f
```

**정상 결과:**
- `.pyc` 파일만 보임
- `.py` 파일 검색 결과 없음

### 4. 배포 패키지 파일

빌드 완료 후 `releases/` 폴더에 생성됩니다:

```
releases/aerial-survey-manager-v1.0.3/
├── docker-compose.yml      # 배포용 (image: 사용)
├── .env.example            # 환경변수 템플릿
├── images.tar              # Docker 이미지 (대용량)
├── load-images.sh          # 이미지 로드 스크립트
├── nginx.conf              # Nginx 설정
├── init.sql                # DB 초기화
├── scripts/                # 관리 스크립트
└── data/                   # 초기 데이터
```

압축 파일: `releases/aerial-survey-manager-v1.0.3.tar.gz`

### 5. 배포 패키지 전달

생성된 `.tar.gz` 파일을 배포 PC로 전달합니다.

### 6. 빌드 후 로컬 .pyc 정리 (2026-02-06)

빌드 스크립트는 배포 패키지 생성 후 **로컬 디렉토리의 .pyc 파일을 자동 정리**합니다.
이는 개발 환경에서 배포용 .pyc 파일로 인한 "Bad magic number" 오류를 방지합니다.

```bash
# build-release.sh 10단계에서 자동 실행
find engines/ -name "*.pyc" -delete
find backend/ -name "*.pyc" -delete
```

### 7. 문제 해결

#### 이미지에 여전히 .py 파일이 있음
```bash
# 원인: 스크립트 자동 정리가 실패했거나 빌드 중 오류 발생
# 해결: 배포 이미지만 수동 삭제 후 재빌드
docker rmi $(docker images | grep aerial-prod | awk '{print $3}') -f
docker builder prune -af
./scripts/build-release.sh v1.0.3
```

#### worker-engine 이미지가 없음
```bash
# 원인: --profile engine 옵션 누락
# 해결: build-release.sh가 최신인지 확인
cat scripts/build-release.sh | grep "profile engine"
```

#### 이미지 생성 시간이 오래됨
```bash
# 원인: 빌드가 실패하고 이전 이미지 사용
# 해결: 빌드 로그 확인 후 오류 수정
```

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

### 7. 프로젝트 삭제 시 스토리지 정리 (2026-02-06 업데이트)

프로젝트 삭제 시 다음 데이터가 자동으로 삭제됩니다:

| 경로 | 설명 | 삭제 주체 |
|------|------|----------|
| `images/{project_id}/` | S3 Multipart로 업로드된 원본 이미지 | API |
| `uploads/{upload_id}/` | TUS로 업로드된 원본 이미지 (레거시) | API |
| `projects/{project_id}/` | 썸네일, 정사영상 결과물 | API |
| `/data/processing/{project_id}/` | 로컬 처리 캐시 | **worker-engine (Celery)** |

> ⚠️ **2026-02-06 변경**: 로컬 처리 데이터(`/data/processing/`)는 worker-engine이 root 권한으로 생성하므로, 삭제도 Celery 태스크(`delete_project_data`)를 통해 worker-engine에서 수행합니다. API(appuser)는 권한 부족으로 직접 삭제할 수 없습니다.

### 8. 고아 파일 정리 스크립트 (2026-02-02)

DB에 연결되지 않은 고아 파일들을 정리하는 스크립트입니다.

#### 사용법

```bash
# 로컬 processing 폴더만 정리
docker compose exec api python scripts/cleanup_orphaned_data.py

# MinIO uploads 폴더도 정리 (dry-run: 삭제 대상만 확인)
docker compose exec api python scripts/cleanup_orphaned_data.py --minio

# MinIO uploads 폴더 실제 삭제
docker compose exec api python scripts/cleanup_orphaned_data.py --minio --execute
```

#### 정리 대상

| 경로 | 조건 | 설명 |
|------|------|------|
| `/data/processing/{uuid}/` | DB에 해당 프로젝트 없음 | 삭제된 프로젝트의 로컬 캐시 |
| `uploads/{hash}` | DB Image.original_path에 없음 | 실패/취소된 TUS 업로드 임시 파일 |
| `uploads/{hash}.info` | 위와 동일 | TUS 메타데이터 파일 |

#### 안전 장치

- **dry-run 기본**: `--minio`만 사용하면 삭제 대상만 출력하고 실제 삭제하지 않음
- **DB 연동 확인**: `Image.original_path`에 등록된 파일은 삭제하지 않음
- **현재 이미지 경로**: `images/{project_id}/` 경로는 정리 대상이 아님

#### 예시 출력

```
=== Cleaning up MinIO uploads ===
Found 50 image paths in DB.
Found 243 objects in MinIO uploads/
Found 243 orphaned upload bases.
  [DRY] Would delete: uploads/0046dd8f5c5bf879757e2d899c4d73da (2 objects, 1074.1 MB)
  ...
Dry run finished. Would delete 243 upload groups (100.70 GB).
Run with --execute to actually delete these files.
```

---

## 🔄 환경변수 변경 반영 (2026-02-06)

### 1. reload-env.sh 스크립트

`.env` 파일 수정 후 컨테이너에 반영하려면 `reload-env.sh` 스크립트를 사용합니다.

```bash
# 모든 앱 컨테이너에 반영 (api, frontend, worker-engine 등)
./scripts/reload-env.sh

# 특정 서비스만 반영
./scripts/reload-env.sh worker-engine
./scripts/reload-env.sh api worker-engine
```

### 2. 동작 원리

Docker Compose의 환경변수는 컨테이너 **생성 시**에만 적용됩니다.
`docker compose restart`는 환경변수를 갱신하지 않으므로, `--force-recreate` 옵션이 필요합니다.

```bash
# reload-env.sh 내부 동작
docker compose up -d --force-recreate $SERVICES
```

### 3. 적용 대상 서비스

| 서비스 유형 | 서비스명 | reload 대상 |
|------------|---------|------------|
| 앱 서비스 | api, frontend, worker-engine, celery-* | ✅ 기본 대상 |
| 외부 서비스 | db, redis, minio, nginx, titiler | ❌ 제외 (환경변수 변경 드묾) |

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
| 처리 워커 | `*worker-logging` | 250MB | worker-engine, worker-odm, tusd |

> 💡 **팁**: 처리 워커는 이미지 처리 시 상세한 로그를 남기므로, 오류 분석을 위해 더 큰 로그 용량을 확보합니다.

### 2. 로그 확인 명령어

```bash
# 특정 컨테이너 로그 보기
docker logs aerial-survey-manager-api-1 --tail 100

# 실시간 로그 스트리밍
docker logs -f aerial-survey-manager-worker-engine-1

# 로그 파일 크기 확인
du -sh /var/lib/docker/containers/*/
```

> 💡 **처리 로그 확인**: Metashape 처리의 단계별 소요 시간은 `docker compose logs -f worker-engine`에서 실시간으로 확인할 수 있습니다. 상세한 Metashape 출력은 각 프로젝트의 `.work/.processing.log` 파일을 참조하세요. 자세한 내용은 [Metashape 디버깅](#-metashape-디버깅-2026-02-08-업데이트) 섹션을 참고하세요.

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

### 5. 글로벌 업로드 시스템 (2026-02-04 업데이트)

프론트엔드에서는 업로드 중에도 앱 내 자유로운 네비게이션을 지원합니다:
- **앱 내 네비게이션**: 업로드 중에도 대시보드, 다른 프로젝트로 이동 가능 (업로드 계속 진행)
- **업로드 패널 글로벌 표시**: 어느 화면에서든 업로드 진행률 패널이 우측 하단에 표시됨
- **브라우저 종료/새로고침**: `beforeunload` 이벤트로 경고 표시 (실제 페이지 이탈 시에만)
- 브라우저를 완전히 닫거나 새로고침하면 업로드가 중단됨

**업로드 취소 UX (2026-02-04)**:
- 취소 버튼 클릭 시 확인 다이얼로그 표시
- 확인 후 "업로드가 취소되었습니다" 알림 메시지 표시
- 알림 확인 후 업로드 패널 자동 닫힘

### 6. 멀티 프로젝트 동시 업로드 (2026-02-02 추가)

단일 브라우저 탭에서 여러 프로젝트를 동시에 업로드할 수 있습니다:
- **대시보드**: 모든 프로젝트의 업로드 현황을 동시에 표시
  - 2개 이상 프로젝트 업로드 시 프로젝트별로 그룹화
  - 각 프로젝트 헤더 클릭으로 접기/펼치기 가능
- **처리 옵션 화면**: 현재 선택된 프로젝트의 업로드 현황만 표시
- **데이터 구조**: `uploadsByProject` 객체로 프로젝트별 업로드 상태 관리

---

## 🔑 Metashape Licensing Management

`worker-engine` 컨테이너의 라이선스 관리 전략에 대한 상세 기술 문서입니다.

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
   docker-compose up -d --force-recreate worker-engine
   ```
3. **수동 활성화**: 컨테이너 시작 후 `activate.py`를 실행하여 라이선스를 활성화합니다.
   ```bash
   docker exec worker-engine python3 /app/engines/metashape/dags/metashape/activate.py
   ```
   성공 시 `.lic` 파일이 `/var/tmp/agisoft/licensing/licenses/` 폴더에 생성되며, 이후에는 영구적으로 유지됩니다.

### 3. 수동 복구 (Manual Recovery)
컨테이너가 실수로 삭제되었으나 라이선스를 다른 물리 서버로 옮기고 싶은 경우:
1. `docker-compose.yml`에 정의된 것과 동일한 MAC 주소로 임시 컨테이너를 실행합니다.
2. `deactivate.py` (또는 배포환경에서는 `deactivate.pyc`)를 실행하여 명시적으로 라이선스를 반납합니다.
   ```bash
   # 배포 환경 (.pyc)
   docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.pyc
   # 개발 환경 (.py)
   docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.py
   ```

---

## 처리 진행 상태 캐시 (운영/디버깅)

처리 화면 재진입 시 마지막 단계 메시지와 진행률을 즉시 복구하기 위해,
워커가 처리 상태를 파일로 캐시합니다.

- 경로: `/data/processing/{project_id}/.work/processing_status.json`
- 예시 내용:
  ```json
  {"status":"processing","progress":42,"message":"이미지 정렬 (Align Photos)","updated_at":"..."}
  ```

## Known Issue: 취소 후 재시작 오류

- 동일 프로젝트에서 **처리 중단 직후 재시작**할 경우 Metashape 파이프라인에서 `Empty DEM` 등의 오류가 발생할 수 있습니다.
- 이 경우 EO 파일명 매칭 실패/metadata.txt 불일치 가능성이 높으므로, 아래를 우선 확인하세요:
  - `/data/processing/{project_id}/images/metadata.txt`의 이미지 파일명과 실제 이미지 파일명이 일치하는지
  - `worker-engine` 로그에서 `reference_normalized.txt exists=True` 여부
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

## 🔍 Metashape 디버깅 (2026-02-08 업데이트)

### 1. 처리 디렉토리 구조

처리 중간 산출물은 숨김 폴더(`.work/`)에 저장되고, 최종 결과물만 `output/`에 배치됩니다:

```
/data/processing/{project-id}/
├── images/                  ← 업로드된 원본 이미지
├── output/
│   └── result_cog.tif       ← 최종 결과물 (COG)
└── .work/                   ← 숨김 폴더 (중간 산출물)
    ├── status.json          ← 단계별 진행률 + result_gsd
    ├── .processing.log      ← 상세 처리 로그
    ├── result.tif            ← (성공 시 삭제)
    ├── project.psx           ← (성공 시 삭제)
    └── project.files/        ← (조건부 삭제)
```

**정리 정책**:

| 처리 결과 | `.work/` 내 파일 | 설명 |
|-----------|-----------------|------|
| 성공 | `status.json`, `.processing.log`만 유지 | 나머지 중간 산출물 삭제 |
| 실패 | 모든 파일 보존 | 디버깅용 |

### 2. 처리 로그 확인

#### A. Celery 콘솔 로그 (단계별 타이밍)

`docker compose logs`로 각 단계의 소요 시간을 확인할 수 있습니다:

```bash
docker compose logs -f worker-engine
```

출력 예시:
```
[Metashape] Step 1/5: 이미지 정렬 (align_photos.py)
[Metashape] Step 1/5: 완료 - 3분 42초
[Metashape] Step 2/5: DEM 생성 (build_dem.py)
[Metashape] Step 2/5: 완료 - 1분 15초
...
[Metashape] ========================================
[Metashape] 전체 처리 완료 - 총 12분 30초
[Metashape]   1. align_photos.py          : 3분 42초
[Metashape]   2. build_dem.py             : 1분 15초
[Metashape]   3. build_orthomosaic.py     : 5분 20초
[Metashape]   4. export_orthomosaic.py    : 2분 13초
[Metashape] ========================================
```

#### B. 상세 로그 (`.processing.log`)

각 단계의 Metashape stdout 출력이 `.processing.log`에 기록됩니다:

```bash
# 처리 중 실시간 확인
docker compose exec worker-engine tail -f /data/processing/{project-id}/.work/.processing.log

# 처리 완료 후 확인
docker compose exec worker-engine cat /data/processing/{project-id}/.work/.processing.log
```

로그 파일 내용 예시:
```
============================================================
[Step 1/5] align_photos.py - 이미지 정렬
[Started: 2026-02-08 14:30:00]
============================================================
   Align Photos: 10%
   Align Photos: 20%
   ...
[Step 1/5] 완료: 3분 42초
```

#### C. 실패 시 에러 확인

처리 실패 시 Celery 로그에 `.processing.log`의 마지막 20줄이 자동으로 출력됩니다.
추가 확인이 필요하면 `.processing.log` 전체를 확인하세요.

### 3. Alignment 결과 로깅

처리 로그에서 카메라 정렬 결과를 확인할 수 있습니다:

```
📊 Alignment 결과: 520/528 카메라 정렬됨 (98.5%)
⚠️ 정렬 실패 카메라 (8개):
   - DJI_0123.JPG
   - DJI_0124.JPG
   ...
```

### 4. project.files 조건부 보존

처리 중 Metashape 프로젝트 파일이 조건부로 삭제됩니다:

| 조건 | 삭제 여부 | 이유 |
|------|----------|------|
| 처리 성공 + 정렬률 80% 이상 | ✅ 삭제 | 정상 완료 |
| 처리 실패 또는 정렬률 80% 미만 | ❌ 보존 | 디버깅 필요 |

> ℹ️ **2026-02-10 변경**: 정렬률 기준을 95% → 80%로 하향. 도서 지역 등 해수면/단조로운 배경이 많은 촬영에서는 정렬률이 낮을 수 있으므로, 실사용 환경에 맞춰 기준을 완화했습니다.

보존된 파일 위치: `/data/processing/{project_id}/.work/project.files/`

### 5. 로그 출력량 최적화

Metashape 스크립트 내부 진행률 로그는 10% 단위로만 출력됩니다:
```
   Align Photos: 10%
   Align Photos: 20%
   ...
```

---

## 🔧 외부 COG 삽입 (2026-02-12)

외부에서 생성한 COG(Cloud Optimized GeoTIFF) 또는 일반 GeoTIFF를 프로젝트에 삽입하여, 처리를 거치지 않고도 완료 상태를 만들 수 있습니다.

### 1. 전제조건

| 항목 | 요구사항 |
|------|----------|
| **COG 파일** | 유효한 GeoTIFF (CRS/투영 메타데이터 포함). 일반 GeoTIFF도 가능 (자동 COG 변환) |
| **프로젝트** | DB에 프로젝트가 존재해야 함 |
| **Docker** | worker-engine, db, minio, api 컨테이너 실행 중 |
| **GSD** | Projected CRS (EPSG:5186 등)인 경우 자동 추출. Geographic CRS (EPSG:4326)인 경우 `--gsd` 수동 지정 권장 |

### 2. 사용법

```bash
# 기본 사용 (GSD 자동 추출)
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif

# GSD 수동 지정 (cm/pixel)
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --gsd 5.0

# 처리 중인 작업을 강제 취소하고 삽입
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --force

# 복합 옵션
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --gsd 3.5 --force
```

### 3. 동작 흐름

```
호스트                          worker-engine (Docker)
──────                          ──────────────────────
1. 파일 검증
2. COG → 스테이징 복사
3. docker exec로 태스크 전송 →  4. GeoTIFF 유효성 검증 (gdalinfo)
                                5. GSD/bounds 자동 추출
                                6. COG 아닌 경우 자동 변환 (gdal_translate)
                                7. /data/processing/{id}/output/ 배치
                                8. MinIO 업로드
                                9. SHA256 체크섬 계산
                                10. DB 업데이트 (ProcessingJob + Project)
                                11. PostGIS 면적 계산 + 권역 자동 배정
                                12. WebSocket 완료 브로드캐스트
```

### 4. 수행되는 상태 변경

| 구분 | 필드 | 값 |
|------|------|-----|
| **디스크** | `output/result_cog.tif` | COG 파일 배치 |
| **MinIO** | `projects/{id}/ortho/result_cog.tif` | COG 업로드 |
| **ProcessingJob** | status, completed_at, result_gsd, result_size, result_checksum, progress | completed, now(), 자동, 자동, SHA256, 100 |
| **Project** | status, progress, ortho_path, ortho_size, bounds, area, region | completed, 100, MinIO경로, 자동, gdalinfo, PostGIS, 자동 |

### 5. 활용 사례

- **외부 처리 결과 통합**: 다른 소프트웨어(PIX4D, DJI Terra 등)에서 생성한 정사영상을 시스템에 등록
- **처리 실패 대체**: Metashape 처리가 반복 실패하는 프로젝트에 외부 결과물 삽입
- **테스트/데모**: 처리 없이 프로젝트 완료 상태를 빠르게 구성

### 6. 주의사항

- 기존 결과물(MinIO, 디스크)이 있으면 **덮어씁니다**
- `--force` 없이 처리 중인 프로젝트에 삽입하면 거부됩니다
- Geographic CRS(EPSG:4326)인 파일은 GSD 자동 추출이 부정확합니다 → `--gsd` 옵션 사용 권장
- 입력 파일이 COG가 아닌 경우 자동 변환되므로 대용량 파일은 시간이 걸릴 수 있습니다

### 7. 트러블슈팅

#### 증상: "파일을 찾을 수 없습니다"
```
원인: 스테이징 복사 실패 또는 PROCESSING_DATA_PATH 마운트 문제
확인: docker inspect aerial-worker-engine --format '{{range .Mounts}}{{if eq .Destination "/data/processing"}}{{.Source}}{{end}}{{end}}'
해결: PROCESSING_DATA_PATH가 올바른지 확인
```

#### 증상: "유효한 GeoTIFF가 아닙니다"
```
원인: 입력 파일에 CRS/투영 메타데이터 없음
확인: gdalinfo /path/to/file.tif | grep "Coordinate System"
해결: 올바른 CRS가 포함된 GeoTIFF 파일 사용
```

#### 증상: "처리 중인 작업이 있습니다"
```
원인: 프로젝트가 현재 처리 중
해결: --force 옵션 추가하여 기존 작업 취소 후 삽입
```

### 8. 관련 파일

| 파일 | 설명 |
|------|------|
| `scripts/inject-cog.sh` | 호스트 실행 스크립트 |
| `backend/app/workers/tasks.py` | `inject_external_cog` Celery 태스크 |

---

## 🚀 S3 Multipart Upload (2026-02-02)

### 1. 아키텍처 개요

TUS 프로토콜 대신 S3 Multipart Upload를 사용하여 업로드 성능을 개선했습니다.

```
기존 (TUS):     Browser → nginx → TUS → MinIO (15-20 MB/s)
변경 (S3):      Browser → nginx(/storage/) → MinIO (80-100 MB/s 목표)
                       ↑
                 Presigned URLs (백엔드에서 발급)
```

### 2. 핵심 설정: MINIO_PUBLIC_ENDPOINT

**가장 중요한 설정**입니다. 이 값은 브라우저에서 접속하는 nginx 주소와 **정확히 동일**해야 합니다.

```bash
# .env 파일
# 브라우저가 http://192.168.10.203:8081 로 접속한다면:
MINIO_PUBLIC_ENDPOINT=192.168.10.203:8081
```

#### 왜 중요한가?
- Presigned URL의 호스트가 이 값으로 생성됨
- 프론트엔드와 다른 포트/호스트면 **CORS 오류** 발생
- Same-origin이어야 preflight 없이 빠른 업로드 가능

#### 설정 변경 후
```bash
# API 컨테이너 재생성 필요 (restart가 아닌 up -d)
docker-compose up -d api
```

### 3. nginx 설정

`/storage/` 경로가 MinIO로 프록시됩니다:

```nginx
location /storage/ {
    # CORS 헤더 (cross-origin 상황 대비)
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Expose-Headers' 'ETag' always;

    rewrite ^/storage/(.*) /$1 break;
    proxy_pass http://minio;

    # 중요: Host 헤더는 presigned URL 서명과 일치해야 함
    proxy_set_header Host minio:9000;
}
```

### 4. 업로드 흐름

1. **초기화** (`POST /api/v1/upload/projects/{id}/multipart/init`)
   - Image 레코드 생성/업데이트
   - S3 multipart upload 시작
   - 각 파트별 presigned URL 발급

2. **파트 업로드** (브라우저 → nginx → MinIO)
   - 10MB 단위 파트 병렬 업로드
   - 파일당 4개 파트 동시 업로드
   - 6개 파일 동시 업로드

3. **완료** (`POST /api/v1/upload/projects/{id}/multipart/complete`)
   - S3 multipart upload 완료
   - Image 레코드 상태 업데이트
   - 썸네일 생성 태스크 트리거

### 5. 트러블슈팅

#### 증상: CORS Failed / NS_ERROR_NET_RESET
```
원인: MINIO_PUBLIC_ENDPOINT가 브라우저 접속 주소와 불일치
해결: .env에서 MINIO_PUBLIC_ENDPOINT를 브라우저 주소와 동일하게 설정
     → docker-compose up -d api
```

#### 증상: 403 SignatureDoesNotMatch
```
원인: nginx의 Host 헤더가 presigned URL 서명과 불일치
해결: nginx.conf에서 proxy_set_header Host minio:9000; 확인
     → docker-compose restart nginx
```

#### 증상: 업로드 속도가 여전히 느림 (20MB/s)
```
원인: CORS preflight 요청이 발생 중
확인: 브라우저 Network 탭에서 OPTIONS 요청 확인
해결: MINIO_PUBLIC_ENDPOINT가 same-origin인지 확인
```

### 6. 관련 파일

| 파일 | 설명 |
|------|------|
| `backend/app/services/s3_multipart.py` | S3 multipart 서비스 (boto3) |
| `backend/app/api/v1/upload.py` | Multipart API 엔드포인트 |
| `src/services/s3Upload.js` | 프론트엔드 S3 업로더 |
| `nginx.conf` | `/storage/` 프록시 설정 |

### 7. TUS 서비스 (레거시)

TUS 서비스(tusd)는 docker-compose.yml에서 주석 처리되어 있습니다.
기존 TUS로 업로드된 이미지는 `uploads/{upload_id}/` 경로에 저장되어 있으며,
새 S3 multipart로 업로드된 이미지는 `images/{project_id}/` 경로에 저장됩니다.

---

## 📷 카메라 모델 관리 (2026-02-02)

### 1. 카메라 모델 시드 스크립트

`data/io.csv` 파일에서 카메라 모델을 데이터베이스에 등록할 수 있습니다.

```bash
# 기본 실행 (기존 데이터 유지, 새 데이터만 추가)
docker compose exec api python /app/scripts/seed_camera_models.py -f /app/io.csv

# 기존 데이터 모두 삭제 후 새로 등록
docker compose exec api python /app/scripts/seed_camera_models.py -f /app/io.csv --clear
```

### 2. io.csv 파일 형식

io.csv는 다음 형식의 카메라 정보를 포함합니다:

```
$CAMERA
,$CAMERA_NAME:,DMC-III,
,$LENS_SN:,회사1,회사2,
,$FOCAL_LENGTH:,92.0,
,$SENSOR_SIZE:,17216,14656,
,$PIXEL_SIZE:,5.6,
$END_CAMERA
```

### 3. 파싱 규칙

- `$CAMERA_NAME`: 카메라 모델명 (고유 키로 사용)
- `$FOCAL_LENGTH`: 초점거리 (mm)
- `$SENSOR_SIZE`: 센서 크기 (가로 픽셀, 세로 픽셀)
- `$PIXEL_SIZE`: 픽셀 크기 (µm)
- 센서 물리 크기(mm)는 `픽셀수 × 픽셀크기 / 1000`으로 자동 계산

### 4. 중복 처리

- 동일한 `$CAMERA_NAME`을 가진 카메라는 한 번만 등록됩니다
- `--clear` 옵션 사용 시 기존 **모든** 카메라 모델이 삭제됩니다 (커스텀 포함)

---

## ⚙️ 처리 엔진 설정 (2026-02-04 업데이트)

### 1. Metashape 전용 모드

현재 시스템은 **Metashape만 지원**하도록 설정되어 있습니다.

- ODM, External 엔진은 `docker-compose.yml`에서 주석 처리됨
- 프론트엔드 처리 옵션에서 엔진 선택 UI 제거됨
- 기본 엔진: `metashape`

### 2. 처리 프리셋 (2026-02-04)

시스템 기본 프리셋이 간소화되었습니다:

| 프리셋 이름 | 처리 모드 | GSD | 설명 |
|------------|----------|-----|------|
| **정밀 처리** | Normal | 5cm | 일반적인 정사영상 생성 (기본값) |
| **고속 처리** | Preview | 10cm | 빠른 처리용 저해상도 설정 |

> ⚠️ **변경사항**: "표준 정사영상"→"정밀 처리", "빠른 미리보기"→"고속 처리"로 이름 변경, "고해상도 정사영상" 프리셋 제거

### 3. EO 파일 설정 (2026-02-06 업데이트)

업로드 위자드에서 EO 파일 구분자 및 좌표계를 설정할 수 있습니다:

| 설정 | 옵션 | 기본값 |
|------|------|--------|
| **구분자** | 공백(Space), 탭(Tab), 콤마(,) | 공백(Space) |
| **좌표계** | TM 중부/서부/동부, UTM-K, WGS84 | TM 중부 (EPSG:5186) |
| **헤더 행** | 첫 줄 제외 / 포함 | 첫 줄 제외 |

**EO 메타데이터 저장 (2026-02-06 변경)**:
- EO 업로드 시 `metadata.txt` 파일이 `/data/processing/{project_id}/images/`에 저장됨
- 저장은 **Celery 태스크**(`save_eo_metadata`)를 통해 worker-engine에서 수행
- 이유: `/data/processing` 디렉토리가 root 소유이므로 API(appuser)가 직접 파일 생성 불가

**데이터 불일치 경고**: 이미지 수와 EO 데이터 수가 일치하지 않으면 경고 다이얼로그가 표시됩니다:
- "계속 진행하시겠습니까?" 메시지와 함께 "돌아가기" / "계속 진행" 버튼 제공
- "계속 진행" 클릭 시 불일치 상태에서도 프로젝트 생성 가능

### 4. 출력 좌표계 설정 (2026-02-04)

정사영상 생성 시 **출력 좌표계가 입력 좌표계와 동일하게** 설정됩니다:

- 이전: 프리셋에서 지정한 `output_crs` (예: EPSG:5186) 사용
- 현재: 프로젝트에 설정된 입력 좌표계 (`chunk.crs`) 그대로 사용
- EO 파일에서 EPSG가 감지되면 해당 좌표계로 자동 설정됨

**관련 파일**: `engines/metashape/dags/metashape/build_orthomosaic.py`

```python
# 출력 좌표계를 프로젝트에 설정된 입력 좌표계와 동일하게 사용
proj = Metashape.OrthoProjection()
proj.crs = chunk.crs
```

### 5. Orthomosaic Seamline 설정 (2026-02-08)

정사영상 생성 시 **Seamline Refinement**가 활성화되어 이미지 간 이음선 품질이 향상됩니다:

- `refine_seamlines=True`: 이미지 경계선 최적화 (활성)
- `refine_roof_edges`: 지붕 경계선 보정 (비활성, 주석 처리)

**관련 파일**: `engines/metashape/dags/metashape/build_orthomosaic.py`

### 6. COG 생성 파이프라인 (2026-02-10 업데이트)

COG(Cloud Optimized GeoTIFF) 변환은 **엔진 우선** 방식으로 동작합니다:

1. **Metashape 엔진**이 `export_orthomosaic.py`에서 `result.tif` → `result_cog.tif` COG 변환 수행
2. **Celery worker**(`tasks.py`)가 `.work/result_cog.tif` 존재 여부를 확인
   - 있으면: 엔진이 만든 COG를 그대로 사용 (변환 스킵)
   - 없으면: `gdal_translate`로 COG 변환 수행 (ODM 등 다른 엔진용 폴백)

> ℹ️ **2026-02-10 변경**: 이전에는 Metashape 엔진과 Celery worker가 각각 COG를 생성하여 **동일한 변환이 2번** 수행되었습니다. 대용량 정사영상에서 불필요한 처리 시간이 소요되던 문제를 수정했습니다.

**COG 변환 옵션** (원본 GSD 유지):

```python
# 엔진(export_orthomosaic.py): GDAL Python API
gdal.TranslateOptions(format="COG", creationOptions=[
    "BLOCKSIZE=256", "COMPRESS=LZW", "RESAMPLING=LANCZOS",
    "PREDICTOR=2", "BIGTIFF=YES"
])

# 폴백(tasks.py): gdal_translate CLI
gdal_translate -of COG -co COMPRESS=LZW -co BLOCKSIZE=256
               -co OVERVIEW_RESAMPLING=AVERAGE -co BIGTIFF=YES
```

> 💡 **참고**: Metashape에서 내보낸 `result.tif`는 타일링과 오버뷰가 포함되어 있지만, 완전한 COG 표준은 아닙니다. `gdal.Translate`로 변환하여 HTTP Range Request에 최적화된 COG를 생성합니다.

### 2. 비활성화된 서비스

```yaml
# docker-compose.yml에서 주석 처리된 서비스:
# - worker-odm: OpenDroneMap 처리 워커
# - worker-external: 외부 API 처리 워커
# - tusd: TUS 업로드 서버 (S3 Multipart로 대체)
```

### 3. 다른 엔진 활성화 방법

ODM 또는 외부 엔진을 다시 활성화하려면:

1. `docker-compose.yml`에서 해당 서비스 주석 해제
2. `src/components/Processing/ProcessingSidebar.jsx`에서 엔진 선택 UI 복원
3. `backend/app/schemas/project.py`에서 engine 기본값 수정
4. 컨테이너 재빌드: `docker compose up -d --build`

---

## 🗺️ TiTiler COG 타일 서버 (2026-02-02)

### 1. S3 접근 설정

TiTiler가 MinIO의 COG 파일에 접근하려면 GDAL S3 환경 변수가 올바르게 설정되어야 합니다.

```yaml
# docker-compose.yml - titiler 서비스
environment:
  - AWS_ACCESS_KEY_ID=${MINIO_ACCESS_KEY:-minioadmin}
  - AWS_SECRET_ACCESS_KEY=${MINIO_SECRET_KEY:-minioadmin}
  - AWS_S3_ENDPOINT=minio:9000        # http:// 없이 호스트:포트만
  - AWS_VIRTUAL_HOSTING=FALSE         # path-style 접근
  - AWS_HTTPS=NO                      # MinIO는 HTTP 사용
  - AWS_NO_SIGN_REQUEST=NO            # 인증 사용
```

### 2. COG URL 형식

백엔드에서 프론트엔드로 S3 URL 형식을 반환합니다:

```
s3://aerial-survey/projects/{project_id}/ortho/result_cog.tif
```

### 3. 타일 요청 흐름

```
브라우저 → /titiler/cog/tiles/{z}/{x}/{y}.png?url=s3://...
         → nginx (CORS 헤더 추가)
         → TiTiler (GDAL /vsis3/)
         → MinIO (S3 프로토콜)
```

### 4. 트러블슈팅

#### 증상: TiTiler 500 에러 (`does not exist in the file system`)
```
원인: GDAL이 MinIO S3에 접근하지 못함
확인: docker compose exec titiler env | grep AWS
해결: docker-compose.yml의 titiler 환경변수 확인 후 컨테이너 재생성
     → docker compose up -d titiler --force-recreate
```

#### 증상: 정사영상이 지도에 표시되지 않음
```
원인: COG URL이 presigned HTTP URL로 반환됨 (S3 URL이어야 함)
확인: 브라우저 Network 탭에서 /cog-url 응답 확인
해결: backend/app/api/v1/download.py의 get_cog_url() 함수 확인
```

### 5. 관련 파일

| 파일 | 설명 |
|------|------|
| `docker-compose.yml` | TiTiler 환경변수 설정 |
| `nginx.conf` | `/titiler/` 프록시 및 CORS |
| `backend/app/api/v1/download.py` | COG URL 반환 API |
| `src/components/Dashboard/FootprintMap.jsx` | TiTiler 타일 레이어 |

### 6. GDAL 환경변수 (2026-02-03 업데이트)

TiTiler의 GDAL 성능 최적화를 위해 다음 환경변수가 추가되었습니다:

```yaml
# docker-compose.yml - titiler 서비스
environment:
  # 기존 설정
  - AWS_S3_ENDPOINT=minio:9000        # http:// 없이!
  - AWS_VIRTUAL_HOSTING=FALSE
  - AWS_HTTPS=NO
  # 추가된 GDAL 최적화 설정
  - GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR  # 불필요한 디렉토리 리스팅 방지
  - CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff  # TIFF 파일만 허용
  - VSI_CACHE=TRUE                    # 캐시 활성화
  - VSI_CACHE_SIZE=50000000           # 50MB 캐시
```

> ⚠️ `AWS_S3_ENDPOINT`에 `http://` 프로토콜을 포함하면 "Could not resolve host: http" 오류가 발생합니다.

---

## 🔄 배포 PC 재부팅 시 자동 시작 (2026-02-03)

### 1. Docker 컨테이너 자동 재시작

모든 주요 서비스에 `restart: always` 정책이 설정되어 있습니다:

```yaml
# docker-compose.yml
services:
  api:
    restart: always
  worker-engine:
    restart: always
  nginx:
    restart: always
  # ... 기타 서비스
```

### 2. Docker 서비스 자동 시작 확인

시스템 재부팅 시 Docker 서비스가 자동으로 시작되어야 합니다:

```bash
# Docker 서비스 자동 시작 활성화
sudo systemctl enable docker
sudo systemctl enable containerd

# 상태 확인
sudo systemctl is-enabled docker
```

### 3. 재부팅 후 확인 명령

```bash
# 모든 컨테이너 실행 상태 확인
docker ps

# 특정 서비스 로그 확인
docker compose logs -f worker-engine --tail=50
```

---

## 🔒 Metashape 라이센스 자동 비활성화 (2026-02-03)

### 1. Graceful Shutdown 설정

컨테이너 종료 시 Metashape 라이센스를 자동으로 비활성화하기 위한 설정:

```yaml
# docker-compose.yml - worker-engine 서비스
worker-engine:
  stop_signal: SIGTERM           # 종료 시그널
  stop_grace_period: 60s         # 종료 대기 시간 (60초)
```

### 2. 동작 원리

1. `docker compose stop` 또는 `docker compose down` 실행
2. 컨테이너에 SIGTERM 시그널 전송
3. 엔트리포인트 스크립트에서 SIGTERM 핸들러 실행
4. `deactivate.py` 호출하여 라이센스 비활성화
5. 60초 이내에 완료되지 않으면 강제 종료 (SIGKILL)

### 3. 수동 비활성화

필요 시 수동으로 라이센스를 비활성화할 수 있습니다:

```bash
# 배포 환경 (.pyc)
docker compose exec worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.pyc
# 개발 환경 (.py)
docker compose exec worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.py
```

### 4. 로그 확인

종료 시 라이센스 비활성화 로그 확인:

```bash
docker compose logs worker-engine | grep -i "deactivat"
```

### 5. 주의사항

- **SIGKILL 종료 시 비활성화 안됨**: `docker kill` 명령이나 시스템 강제 종료 시 라이센스가 비활성화되지 않습니다
- **정상 종료 권장**: 항상 `docker compose stop` 또는 `docker compose down` 사용
- **시스템 종료**: 리눅스 시스템의 정상 종료 (`shutdown`, `reboot`)는 SIGTERM을 전송하므로 안전합니다

---

## 🗺️ 오프라인 타일맵 설정 (2026-02-10 업데이트)

### 1. 환경변수 설정

오프라인 타일맵을 사용하려면 `.env` 파일에서 다음을 설정합니다:

```bash
# .env
VITE_MAP_OFFLINE=true
VITE_TILE_URL=/tiles/{z}/{x}/{y}       # 확장자 없음 (nginx가 자동 감지)
TILES_PATH=/media/innopam/InnoPAM-8TB/data/vworld_tiles/  # 호스트의 타일 디렉토리
```

> ℹ️ **확장자 자동 감지**: `VITE_TILE_URL`에 확장자를 지정하지 않아도 nginx의 `try_files`가 `.jpg`, `.png` 확장자를 자동으로 탐색합니다. 기존에 확장자를 지정한 경우에도 정상 동작합니다.

### 2. 타일 디렉토리 구조

타일은 `z/x/y.확장자` 형식이어야 합니다:

```
/path/to/tiles/
├── 5/
│   ├── 27/
│   │   └── 12.jpg
│   └── 28/
│       └── 12.jpg
├── 6/
│   └── ...
└── 16/
    └── ...
```

타일 구조 확인 명령:
```bash
# 특정 줌 레벨의 타일 확인
ls /path/to/tiles/7/109/
# 출력 예: 49.jpg  50.jpg  51.jpg
```

### 3. 환경변수별 적용 방법

| 환경변수 | 적용 시점 | 변경 시 필요한 작업 |
|----------|----------|-------------------|
| `VITE_MAP_OFFLINE` | 빌드 타임 | 프론트엔드 **재빌드** 필요 |
| `VITE_TILE_URL` | 빌드 타임 | 프론트엔드 **재빌드** 필요 |
| `TILES_PATH` | 런타임 (볼륨 마운트) | nginx **재시작**만 필요 |

### 4. 설정 변경 후 적용 명령

```bash
# VITE_* 변수 변경 시: 프론트엔드 재빌드 + nginx 재시작
docker compose build frontend --no-cache && docker compose up -d frontend nginx

# TILES_PATH만 변경 시: nginx 재시작만
docker compose up -d nginx
```

### 5. Docker Compose 설정

```yaml
# docker-compose.yml
nginx:
  volumes:
    - ${TILES_PATH:-./data/tiles}:/data/tiles:ro
```

### 6. Nginx 설정

```nginx
# nginx.prod.conf (2026-02-10 업데이트)
location /tiles/ {
    alias /data/tiles/;
    add_header 'Access-Control-Allow-Origin' '*' always;
    try_files $uri $uri.jpg $uri.png @empty_tile;
    expires 1d;
    access_log off;
}

# 타일이 없는 경우: 캐시하지 않고 204 반환
location @empty_tile {
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Cache-Control' 'no-cache' always;
    return 204;
}
```

> ℹ️ **캐시 정책 변경** (2026-02-10):
> - 이전: `expires 30d` + `immutable` → 타일 교체 시 브라우저 캐시가 만료될 때까지 이전 타일(또는 빈 응답)이 표시됨
> - 현재: `expires 1d` → 타일 교체 후 최대 1일 내에 새 타일 반영, 하드 리프레시(Ctrl+Shift+R)로 즉시 갱신 가능
> - 없는 타일 응답(204)은 `no-cache`로 설정되어 캐시되지 않음

### 7. 온라인/오프라인 전환

| VITE_MAP_OFFLINE | 동작 |
|------------------|------|
| `false` (기본값) | OpenStreetMap 온라인 타일 사용 |
| `true` | 로컬 `/tiles/` 경로에서 타일 로드 |

### 8. 타일 교체 절차

배포 후 타일 데이터를 교체하는 올바른 절차입니다.

#### A. 기존 폴더 안의 파일만 교체 (권장)

```bash
# 기존 타일 삭제 후 새 타일 복사 (폴더 자체는 유지)
rm -rf /path/to/tiles/*
cp -r /new/tiles/source/* /path/to/tiles/

# nginx 재시작 불필요 (bind mount가 유지됨)
```

#### B. 폴더 자체를 삭제 후 재생성한 경우

```bash
# 이미 폴더를 삭제 후 새로 만들었다면 nginx 재시작 필요
docker compose restart nginx
```

> ⚠️ **Docker bind mount 주의사항**: Docker bind mount는 디렉토리의 **inode**를 참조합니다.
> 호스트에서 디렉토리를 삭제(`rm -rf /tiles`)하고 같은 경로에 새로 생성(`mkdir /tiles`)하면,
> inode가 변경되어 컨테이너 내부에서 "No such file or directory" 오류가 발생합니다.
> 이 경우 반드시 `docker compose restart nginx`로 nginx를 재시작해야 합니다.

### 9. 트러블슈팅

#### 증상: 지도가 회색 배경만 표시됨
```
원인 1: VITE_MAP_OFFLINE=true인데 타일 파일이 없음
확인: curl http://localhost:8081/tiles/7/109/49.jpg
해결: TILES_PATH가 올바른 경로인지 확인

원인 2: 타일 폴더 교체 후 Docker bind mount가 끊어짐
확인: docker compose exec nginx ls /data/tiles/
      → "No such file or directory" 출력 시 bind mount 문제
해결: docker compose restart nginx

원인 3: 브라우저에 빈 타일 응답이 캐시됨 (이전 버전의 nginx 설정 사용 시)
해결: Ctrl+Shift+R (하드 리프레시) 또는 브라우저 캐시 삭제
```

#### 증상: 타일 요청이 404 반환
```bash
# 타일 경로 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/tiles/7/109/49.jpg

# 컨테이너 내부에서 타일 파일 확인
docker compose exec nginx ls -la /data/tiles/7/109/
```

#### 증상: 타일 교체 후에도 이전 타일이 표시됨
```
원인: 브라우저 캐시 (expires 1d)
해결: Ctrl+Shift+R (하드 리프레시) 또는 시크릿 모드에서 확인
```

#### 증상: 빌드 후에도 온라인 타일 사용
```
원인: 브라우저 캐시
해결: Ctrl+Shift+R (하드 리프레시) 또는 시크릿 모드에서 확인
```

### 10. 관련 파일

| 파일 | 설명 |
|------|------|
| `src/config/mapConfig.js` | 타일 설정 로직 |
| `Dockerfile.frontend` | VITE_MAP_OFFLINE 빌드 인자 |
| `nginx.prod.conf` | `/tiles/` 라우팅 (프로덕션) |
| `nginx.conf` | `/tiles/` 라우팅 (개발) |
| `.env` | 환경변수 설정 |

---

## 📷 카메라 모델 확장 필드 (2026-02-03)

### 1. 새로 추가된 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `ppa_x` | Float | 주점 X 오프셋 (mm) |
| `ppa_y` | Float | 주점 Y 오프셋 (mm) |
| `sensor_width_px` | Integer | 이미지 가로 픽셀 수 |
| `sensor_height_px` | Integer | 이미지 세로 픽셀 수 |

### 2. 사용 위치

- **카메라 모델 추가 폼**: 업로드 위자드 3단계에서 입력
- **카메라 정보 표시**: 처리 옵션 사이드바의 IO 패널
- **API 응답**: `/api/v1/camera-models` 엔드포인트

### 3. 기존 데이터 마이그레이션

기존 카메라 모델에 새 필드가 없으면 기본값(0 또는 null)으로 표시됩니다.
필요시 DB에서 직접 업데이트:

```bash
docker compose exec db psql -U postgres -d aerial_survey -c \
  "UPDATE camera_models SET ppa_x = 0, ppa_y = 0, sensor_width_px = 17310, sensor_height_px = 11310 WHERE name = 'UltraCam Eagle';"
```

---

## 📤 스토리지 엔드포인트 분리 (2026-02-03)

### 1. 아키텍처 변경

업로드와 다운로드가 서로 다른 엔드포인트를 사용합니다:

| 용도 | 엔드포인트 | 포트 | 경로 |
|------|----------|------|------|
| 업로드 (S3 Multipart) | nginx 프록시 | 8081 | `/storage/` |
| 다운로드 (썸네일, projects/) | 직접 MinIO | 9002 | 없음 (직접 접근) |

### 2. 환경변수 설정

```bash
# .env
# 업로드용 nginx 프록시 주소
MINIO_PUBLIC_ENDPOINT=192.168.10.203:8081
```

### 3. storage.py 로직

```python
def get_presigned_url(self, object_name, ...):
    # projects/ 경로: 직접 MinIO 접근 (port 9002)
    if object_name.startswith("projects/"):
        host = public_endpoint.split(':')[0]
        return f"http://{host}:9002/{bucket}/{object_name}"

    # 그 외: nginx 프록시 presigned URL
    return presigned_url_via_nginx
```

### 4. 왜 분리했나?

1. **업로드**: nginx의 `/storage/` 프록시 필요 (path rewriting, CORS)
2. **다운로드 (public)**: presigned URL signature 문제 회피
   - S3 V4 서명은 Host 헤더를 포함하므로, nginx 프록시와 MinIO 직접 접근 시 서명 불일치 발생
   - `projects/` 버킷 정책을 public으로 설정하고 직접 접근하면 서명 불필요

### 5. 트러블슈팅

#### 증상: 업로드 실패 (ERR_CONNECTION_RESET)
```
PUT http://192.168.10.203:9002/storage/aerial-survey/... net::ERR_CONNECTION_RESET
```

**원인**: MINIO_PUBLIC_ENDPOINT가 9002로 설정되어 nginx 프록시를 거치지 않음

**해결**:
```bash
# .env
MINIO_PUBLIC_ENDPOINT=192.168.10.203:8081

# API 컨테이너 재생성
docker compose up -d --force-recreate api
```

#### 증상: 썸네일 403 Forbidden
```
원인: presigned URL 서명 불일치
해결: storage.py에서 projects/ 경로는 직접 MinIO 접근 (이미 적용됨)
```
