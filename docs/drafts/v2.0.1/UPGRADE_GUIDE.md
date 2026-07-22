# Aerial Survey Manager v2.0.1 업데이트 설치 가이드

> 상태: 작성 중인 초안. `v2.0.1` 릴리즈 후보가 만들어지기 전에는 이
> 절차로 운영 PC를 업데이트하지 마십시오.

이 문서는 기존 배포 PC에서 운영 중인 Aerial Survey Manager를
`v2.0.1`로 안전하게 업데이트하기 위한 작업 절차입니다.

- 기준 이전 릴리스: `v1.0.0`
- 설치 대상 릴리스: `v2.0.1`
- 대상 운영체제: Ubuntu 20.04/22.04 LTS
- 대상 사용자: Docker와 터미널 사용이 익숙하지 않은 현장 운영자
- 기본 원칙: 기존 DB, 프로젝트 파일, 정사영상, 지도 타일 및 엔진
  라이선스를 보존하면서 새 버전 폴더로 전환

운영 데이터가 있는 PC에서는 정식 패키지가 확정된 뒤에도 이 문서의 백업과
사전검사를 생략하지 마십시오.

---

## 0. `[필수]` 먼저 보는 실행 요약

이 장은 실제 업데이트 작업에서 입력할 핵심 명령만 순서대로 모은
요약입니다. 처음 작업하는 사람은 **0장으로 전체 순서를 파악한 다음,
표시된 필수 본문을 열어 상세 설명과 중단 기준을 확인하면서
실행하십시오.**

### 표시 의미

| 표시 | 의미 | 생략 가능 여부 |
|---|---|---|
| `[필수]` | 데이터 보존과 업데이트 성공에 반드시 필요한 절차 | 생략 금지 |
| `[운영 필수]` | 재부팅 자동 시작을 사용하는 운영 PC에서 필수 | 운영 PC는 생략 금지 |
| `[조건부]` | MinIO, 외장 디스크, SSL 등 해당 환경에서만 실행 | 해당하는 경우 필수 |
| `[참고]` | 변경사항과 배경 설명 | 작업 전 읽기 권장 |
| `[문제 발생 시]` | 정상 절차가 실패했을 때만 사용 | 정상 설치에서는 생략 |

### 특히 놓치면 안 되는 4개 중단 게이트

전체 문서 중 다음 네 곳이 데이터 보존에 가장 중요합니다.

1. **7장 사전검사:** 결과가 모두 `(0 rows)`가 아니면 중단
2. **8장 DB 백업:** dump가 비어 있거나 목록을 읽을 수 없으면 중단
3. **10장 `.env`:** 스토리지 방식·경로·비밀값·프로젝트명을 보존하지
   못했으면 기존 서비스 중지 금지
4. **12.2 DB 볼륨 비교:** 기존/새 DB 볼륨명이 다르면 API 시작 금지

### 반드시 확인할 본문

| 실행 순서 | 필수로 볼 위치 | 확인 목적 | 통과 조건 |
|---:|---|---|---|
| 1 | **1장** | 금지 명령 확인 | `install.sh`, `down -v`를 사용하지 않음 |
| 2 | **6장** | 기존 프로젝트명·볼륨·스토리지 확인 | 기존 DB 볼륨 이름이 기록됨 |
| 3 | **7장** | DB 마이그레이션 사전검사 | 모든 쿼리가 `(0 rows)` |
| 4 | **8장** | `.env`와 DB 백업 | dump가 생성되고 `pg_restore -l`로 읽힘 |
| 5 | **9장** | 패키지 검증·이미지 로드 | SHA-256 `OK`, 이미지 로드 완료 |
| 6 | **10장** | 기존 `.env`를 v2에 맞게 보완 | Compose config 통과 |
| 7 | **11장** | 기존 서비스 안전 중지 | 컨테이너는 내려가고 DB 볼륨은 남음 |
| 8 | **12장** | 기존 DB 볼륨으로 v2 시작 | 기존/새 DB 볼륨 이름이 완전히 같음 |
| 9 | **13장** | 데이터·GPU·지도 검증 | `/health` 200, 프로젝트 수 동일 |
| 10 | **14.3~14.4** | systemd 고정 경로 전환 | symlink가 v2를 가리킴 |
| 11 | **15장** | 재부팅 검증 | 재부팅 후 데이터와 서비스 정상 |
| 12 | **19장** | 최종 인수 확인 | 모든 필수 체크 항목 완료 |

### 핵심 명령어 실행 순서

아래 명령은 요약본입니다. `/기존/설치경로`는 실제 기존 버전 설치
폴더로 바꿉니다.

#### 0-A. `[필수]` 기존 설치 폴더와 백업 폴더 지정

```bash
cd /기존/설치경로

OLD_DIR="$(pwd -P)"
BACKUP_DIR="$HOME/aerial-upgrade-backup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

printf '기존 폴더: %s\n백업 폴더: %s\n' "$OLD_DIR" "$BACKUP_DIR"
```

이후 명령은 가능하면 같은 터미널에서 계속 실행합니다.

#### 0-B. `[필수]` 현재 서비스·프로젝트명·DB 볼륨 확인

```bash
sudo docker compose ps

DB_CONTAINER="$(sudo docker compose ps -q db)"

OLD_PROJECT="$(sudo docker inspect "$DB_CONTAINER" \
    --format '{{ index .Config.Labels "com.docker.compose.project" }}')"

OLD_DB_VOLUME="$(sudo docker inspect "$DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

printf '기존 Compose 프로젝트명: %s\n기존 DB 볼륨: %s\n' \
    "$OLD_PROJECT" "$OLD_DB_VOLUME"

printf '%s\n' "$OLD_PROJECT" > "$BACKUP_DIR/old-compose-project.txt"
printf '%s\n' "$OLD_DB_VOLUME" > "$BACKUP_DIR/old-db-volume.txt"
```

`OLD_PROJECT` 또는 `OLD_DB_VOLUME`이 비어 있으면 **여기서 중단**하고
6장을 확인합니다.

기존 스토리지 방식을 확인합니다.

```bash
OLD_STORAGE="$(sudo grep '^STORAGE_BACKEND=' .env 2>/dev/null \
    | tail -n 1 | cut -d= -f2-)"

if [ -z "$OLD_STORAGE" ]; then
    if sudo docker compose ps --services --status running | grep -qx minio; then
        OLD_STORAGE="minio"
    else
        OLD_STORAGE="local"
    fi
fi

echo "기존 스토리지 방식: $OLD_STORAGE"
printf '%s\n' "$OLD_STORAGE" > "$BACKUP_DIR/old-storage-backend.txt"
```

#### 0-C. `[필수]` DB 마이그레이션 사전검사

**7장의 SQL 블록 전체를 그대로 실행합니다.**

다음 항목이 모두 `(0 rows)`여야 합니다.

- 중복 이미지 파일명
- 프로젝트별 중복 활성 작업
- 이름이 빈 카메라 모델
- 공유 범위가 잘못된 카메라 모델
- 같은 공유 범위의 중복 카메라 모델명

한 건이라도 나오면 **서비스를 중지하지 말고 업데이트를 중단**합니다.

#### 0-D. `[필수]` `.env`와 DB 백업

```bash
sudo cp "$OLD_DIR/.env" "$BACKUP_DIR/old.env"
sudo chown "$(id -u):$(id -g)" "$BACKUP_DIR/old.env"
chmod 600 "$BACKUP_DIR/old.env"

sudo docker compose exec -T db \
    pg_dump -U postgres -d aerial_survey -Fc \
    > "$BACKUP_DIR/aerial_survey_before_v2.dump"

test -s "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    && echo "DB 백업 파일 생성: 정상" \
    || echo "중단: DB 백업 파일이 비어 있음"

sudo docker compose exec -T db pg_restore -l \
    < "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    | sed -n '1,20p'
```

프로젝트 수를 기록합니다.

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;" \
    > "$BACKUP_DIR/project-count-before.txt"

printf '업데이트 전 프로젝트 수: '
cat "$BACKUP_DIR/project-count-before.txt"
```

DB dump가 비어 있거나 `pg_restore -l`에서 오류가 나오면 **여기서
중단**합니다.

#### 0-E. `[필수]` 새 패키지 검증·압축 해제·이미지 로드

패키지 두 파일을 홈 디렉터리에 둔 예시입니다.

```bash
cd "$HOME"

NEW_DIR="$HOME/aerial-survey-manager-v2.0.1"

if [ -e "$NEW_DIR" ]; then
    echo "중단: 새 버전 폴더가 이미 존재함: $NEW_DIR"
else
    echo "새 버전 압축 해제 가능"
fi
```

`새 버전 압축 해제 가능`이 출력된 경우에만 다음 명령을 실행합니다.

```bash
sha256sum -c aerial-survey-manager-v2.0.1.sha256
tar -xzf aerial-survey-manager-v2.0.1.tar.gz

cd "$NEW_DIR"

cat VERSION
cat BUILD_INFO.txt
./load-images.sh
```

통과 조건:

```text
aerial-survey-manager-v2.0.1.tar.gz: OK
VERSION: 2.0.1
모든 Docker 이미지 로드 완료
```

#### 0-F. `[필수]` 기존 `.env`를 새 폴더로 복사

```bash
sudo cp "$BACKUP_DIR/old.env" "$NEW_DIR/.env"
sudo chown "$(id -u):$(id -g)" "$NEW_DIR/.env"
chmod 600 "$NEW_DIR/.env"

cd "$NEW_DIR"
cp .env .env.before-v2-merge
```

이후 **10.2~10.10을 반드시 실행**하여 다음을 보완합니다.

- `COMPOSE_PROJECT_NAME`: 0-B에서 확인한 기존 프로젝트명
- `STORAGE_BACKEND`: 기존 `local` 또는 `minio` 유지
- 기존 MinIO 사용 시 `COMPOSE_PROFILES=minio`
- `AERIAL_WEB_PORT`: 기존 접속 포트 유지
- `AERIAL_CONTAINER_UID/GID`
- 기존 프로젝트·정사영상·타일·MinIO 경로 유지
- DB/JWT/MinIO/라이선스 비밀값 유지
- 저장소 쓰기 권한 확인
- 네트워크 충돌 확인

마지막으로 Compose 설정을 검사합니다.

```bash
cd "$NEW_DIR"
sudo docker compose config >/dev/null \
    && echo "Compose 설정: 정상" \
    || echo "중단: Compose 설정 오류"
```

Compose 오류가 있으면 기존 서비스를 중지하지 않습니다.

#### 0-G. `[필수]` 기존 서비스 중지

백업과 Compose 검증이 모두 통과한 뒤에만 실행합니다.

```bash
sudo systemctl stop aerial-survey 2>/dev/null || true

cd "$OLD_DIR"
sudo docker compose --profile engine down --remove-orphans
```

`-v`는 절대 붙이지 않습니다.

DB 볼륨이 남아 있는지 확인합니다.

```bash
sudo docker volume inspect "$OLD_DB_VOLUME" >/dev/null \
    && echo "기존 DB 볼륨 보존: 정상" \
    || echo "중단: 기존 DB 볼륨을 찾을 수 없음"
```

#### 0-H. `[필수]` 새 DB 컨테이너의 볼륨 일치 확인

```bash
cd "$NEW_DIR"
sudo docker compose up -d db
sudo docker compose ps db

NEW_DB_CONTAINER="$(sudo docker compose ps -q db)"

NEW_DB_VOLUME="$(sudo docker inspect "$NEW_DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

printf '기존 DB 볼륨: %s\n새 DB 볼륨: %s\n' \
    "$OLD_DB_VOLUME" "$NEW_DB_VOLUME"
```

두 값이 완전히 같아야 합니다.

```bash
if [ "$OLD_DB_VOLUME" = "$NEW_DB_VOLUME" ]; then
    echo "DB 볼륨 일치: 업데이트 계속 가능"
else
    echo "중단: DB 볼륨 불일치"
fi
```

불일치하면 전체 서비스를 시작하지 말고 다음을 실행한 뒤 12.2를
확인합니다.

```bash
sudo docker compose down
```

#### 0-I. `[필수]` 전체 서비스 시작

DB 볼륨이 일치할 때만 실행합니다.

```bash
cd "$NEW_DIR"
sudo docker compose up -d

sleep 60

sudo docker compose ps
sudo docker compose logs --tail=250 api
```

실제 포트를 `.env`에서 읽어 헬스체크합니다.

```bash
CURRENT_WEB_PORT="$(grep '^AERIAL_WEB_PORT=' .env \
    | tail -n 1 | cut -d= -f2-)"
CURRENT_WEB_PORT="${CURRENT_WEB_PORT:-18100}"

curl -i "http://127.0.0.1:${CURRENT_WEB_PORT}/health"
```

통과 조건:

```text
HTTP/1.1 200 OK
version: 2.0.1
Migrations applied successfully.
Application startup complete.
```

첫 10초 안에만 502가 나온 경우 30~60초 후 다시 확인합니다. 계속 502면
16장을 확인합니다.

#### 0-J. `[필수]` 데이터와 GPU 확인

```bash
cd "$NEW_DIR"

sudo bash scripts/healthcheck.sh

sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;" \
    > "$BACKUP_DIR/project-count-after.txt"

printf '업데이트 전 프로젝트 수: '
cat "$BACKUP_DIR/project-count-before.txt"
printf '업데이트 후 프로젝트 수: '
cat "$BACKUP_DIR/project-count-after.txt"

nvidia-smi
sudo docker compose exec worker-engine nvidia-smi
```

업데이트 전후 프로젝트 수가 같아야 합니다. 브라우저에서 기존 계정,
프로젝트, 정사영상, 타일도 확인합니다.

#### 0-K. `[운영 필수]` systemd를 새 버전으로 전환

기능 검증이 끝난 후 새 버전 폴더에서 실행합니다.

```bash
cd "$NEW_DIR"
sudo bash scripts/secure-deployment.sh

readlink -f "$(dirname "$NEW_DIR")/aerial-survey-manager-current"

systemctl status aerial-survey --no-pager
systemctl status aerial-gpu-watchdog.timer --no-pager
```

symlink 결과가 `aerial-survey-manager-v2.0.1`을 가리켜야 합니다.

외장 디스크를 사용하면 **14.1~14.2도 필수**입니다. MinIO를 사용하면
**14.5도 필수**입니다.

#### 0-L. `[운영 필수]` 재부팅 검증

```bash
sudo reboot
```

재부팅 후:

```bash
findmnt
aerial-status
curl -i http://127.0.0.1:18100/health
```

기존 포트를 유지했다면 `18100` 대신 실제 포트를 사용합니다. 브라우저에서
프로젝트·정사영상·타일을 다시 확인합니다.

---

## 1. `[필수]` 가장 중요한 주의사항

업데이트를 시작하기 전에 다음 내용을 먼저 읽으십시오.

1. **처리 중인 프로젝트가 없어야 합니다.**
   업로드, 정사영상 처리, 내보내기가 실행 중이면 완료되거나 안전하게
   중지될 때까지 기다립니다.
2. **기존 설치 폴더에서 작업을 시작합니다.**
   현재 사용 중인 `.env`와 Docker 볼륨을 먼저 확인해야 합니다.
3. **새 버전에서는 `./scripts/install.sh`를 실행하지 않습니다.**
   `install.sh`는 신규 설치용입니다. 실행하면 DB 비밀번호, JWT 키,
   저장소 경로 등이 새 값으로 바뀔 수 있습니다.
4. **`docker compose down -v`를 실행하지 않습니다.**
   `-v`는 PostgreSQL DB와 엔진 라이선스가 들어 있는 Docker 볼륨을
   삭제할 수 있습니다.
5. **기존 `.env`를 버리지 않습니다.**
   DB 비밀번호, JWT 키, 저장소 경로, MinIO 계정, 엔진 라이선스 키를
   그대로 보존해야 합니다.
6. **기존 폴더에 새 압축을 덮어 풀지 않습니다.**
   새 버전은 반드시 `aerial-survey-manager-v2.0.1`이라는 별도
   폴더에 설치합니다.
7. **백업 파일이 생성되고 읽을 수 있는지 확인한 후 서비스를 중지합니다.**
8. **업데이트 완료 확인 전에는 기존 폴더와 기존 Docker 볼륨을 삭제하지
   않습니다.**

### 절대 실행하지 말아야 할 명령

```bash
# 실행 금지: DB 및 라이선스 볼륨이 삭제될 수 있음
docker compose down -v

# 실행 금지: 기존 환경 설정이 재생성될 수 있음
./scripts/install.sh

# 실행 금지: 기존 버전 폴더 위에 새 패키지 덮어쓰기
tar -xzf aerial-survey-manager-v2.0.1.tar.gz -C 기존설치폴더
```

---

## 2. `[참고]` v1.0.0 대비 주요 업데이트

`v1.0.0` 이후 `v2.0.1`까지 처리, 배포, 보안, 스토리지 구조 전반의
변경이 반영되었습니다. 운영자가 알아야 할 주요 차이는 다음과 같습니다.

사용자 기능을 포함한 번호별 전체 비교는
[v1.0.0 대비 v2.0.1 주요 업데이트](MAJOR_UPDATES.md)를
참조하세요.

| 구분 | v1.0.0 및 이전 운영 방식 | v2.0.1 변경 내용 | 업데이트 시 확인할 사항 |
|---|---|---|---|
| 버전 관리 | 파일별 버전 표기가 분산될 수 있음 | 루트 `VERSION`을 단일 버전 기준으로 사용 | `/health`와 `VERSION`이 `2.0.1`인지 확인 |
| 배포 패키지 | 소스 또는 일부 이미지 중심 설치 | 애플리케이션과 외부 Docker 이미지를 포함한 오프라인 패키지 제공 | 먼저 `sha256sum`, 그다음 `load-images.sh` 실행 |
| 웹 접속 포트 | 기본 `WEB_PORT=8081`, HTTPS 443 노출 가능 | `HOST_BIND`와 `AERIAL_WEB_PORT`를 사용하고 기본 포트는 `18100` | 기존 접속 주소를 유지하려면 기존 `WEB_PORT` 값을 `AERIAL_WEB_PORT`로 설정 |
| Docker 네트워크 | 기본 `172.23.0.0/16` | 프로덕션 기본 `10.253.0.0/24`로 개발 스택과 분리 | 해당 대역을 다른 Docker 네트워크가 사용 중인지 확인 |
| 스토리지 | v1.0.0은 MinIO 중심 | 로컬 스토리지가 기본이며 MinIO는 선택 프로필 | 기존 MinIO 설치를 임의로 `local`로 바꾸지 말 것 |
| 저장소 경로 | `PROCESSING_DATA_PATH`, `MINIO_DATA_PATH`, `TILES_PATH` 중심 | `AERIAL_DATA_ROOT`, `LOCAL_STORAGE_PATH`, `EXPORT_ROOT_PATH` 추가 | 기존 경로는 유지하고 새 변수만 보완 |
| 공유 경로 | 설치별 경로 구분이 불명확할 수 있음 | 프로젝트, 최종 정사영상, 타일 경로를 분리 가능 | 공유 `orthomosaic`, `tiles` 경로를 그대로 유지 |
| 처리 엔진 | `--profile engine`, `metashape` 큐 중심 | `worker-engine`이 기본 서비스이며 `gpu-engine` 큐로 통일 | `ENGINE_LICENSE_KEY`와 라이선스 볼륨 보존 |
| GPU 복구 | 수동 확인 중심 | GPU 진단 스크립트와 2분 주기 watchdog 제공 | `check-gpu-stack.sh`, watchdog timer 확인 |
| 작업 워커 | 일반 Celery 워커와 Beat 중심 | 썸네일 전용 워커 분리, 미사용 Celery Beat 제거 | `celery-worker-thumbnail`이 실행 중인지 확인 |
| 처리 안정성 | 중단 작업과 중복 실행 복구가 제한적 | 작업 redelivery, 체크포인트 재시작, 프로젝트별 활성 작업 1개 제약 추가 | 업데이트 전 중복 활성 작업 조회 필수 |
| 처리 단계 | API와 엔진의 단계 정의가 분산 | 처리 단계명, 순서, 진행 메시지를 단일 정의로 통합 | 기존 작업 이력은 유지되며 새 작업부터 통합 표시 사용 |
| 처리 옵션 | 일부 옵션이 작업 레코드에 남지 않음 | 처리 모드, GSD, CRS, EO 정합, 체크포인트 등의 옵션 저장 | DB 마이그레이션 정상 완료 확인 |
| EO 포인트 미리보기 | EO 포인트 클릭 시 썸네일 비율과 상세 정보 표시가 제한적 | 실제 이미지 가로·세로 비율을 유지하는 미리보기, 중앙 정렬 파일명, X/Y/Z 및 Omega/Phi/Kappa 정보 카드 추가 | 기존 프로젝트의 EO 포인트를 클릭하여 세로·가로 이미지가 찌그러지지 않는지 확인 |
| 처리 중 좌표계(원점) 변경 | EO 원본 좌표계를 잘못 선택하면 처리를 중지하고 프로젝트를 다시 만드는 방식이 필요할 수 있음 | 처리 대기·진행 중 올바른 원본 좌표계를 변경 예약하거나 취소 가능, EO 지도 위치를 즉시 다시 계산하고 최종 COG/재투영 전에 적용 | 최종 결과 저장 단계에 들어가면 변경할 수 없음. 테스트 처리에서 예약 상태와 EO 위치를 확인 |
| EO 가져오기 편의성 | EO 파일을 불러온 뒤 실제 적용 내용을 사전에 확인하기 어려움 | 서버에서 EO 파일을 선택하고 파일명·경로·행 수·CRS·이미지 매칭 상태와 X/Y/Z/Omega/Phi/Kappa 내용을 표와 지도에서 미리 확인, 제외할 행 선택 가능 | 테스트 EO 파일을 불러와 표·지도·미매칭/중복 경고가 정상인지 확인 |
| 카메라 모델 | 사용자·조직별 정책이 혼재 | 기본 모델은 공용, 사용자 정의 모델은 조직 공유로 통일 | 빈 이름, 중복 이름, 잘못된 공유 범위 사전검사 |
| 계정 정책 | 관리자/일반 사용자 및 조직 관리 UI가 존재 | 조직 공동 운영 모델로 단순화, 관리 UI/API 제거 | 기존 DB의 기존 계정과 비밀번호는 그대로 사용 |
| 프로젝트 보안 | 일부 산출물·타일 URL에 직접 접근 가능 | 썸네일·정사영상 직접 접근 차단, 단기 서명 URL 적용 | 로그인 후 기존 썸네일과 정사영상 표시 확인 |
| 업로드 | HTTP/TUS 업로드 중심 | 서버 로컬 경로 등록과 파일 스캔 지원, 레거시 TUS 경로 제거 | 기존 자동화가 TUS API를 직접 호출했다면 별도 점검 |
| 처리 예약 | 수동 처리 시작 중심 | 업로드 완료 후 즉시 처리 예약 가능 | 야간 자동 처리 옵션 확인 |
| 도엽 기능 | 제한적 클립/머지 | 1:5,000 및 1:1,000 도엽 단위 클립·머지 지원 | 권역 및 도엽 GeoJSON 초기 데이터 확인 |
| 정사영상 관리 | COG 보존·삭제 흐름이 제한적 | 다운로드 후 COG 삭제, 삭제 전 썸네일 생성, 내보내기 취소 지원 | 기존 정사영상 경로와 썸네일 표시 확인 |
| 지도 UX | 기본 베이스맵과 자동 범위 이동 | 베이스맵 토글, 자유 이동, 원래 범위 복귀, 줌 19 지원 | 공유 타일 경로와 브라우저 캐시 확인 |
| 레거시 엔진 | Airflow, ODM, 외부 API 관련 코드가 남아 있음 | 미사용 Airflow·ODM·외부 처리 엔진 제거, Metashape Celery 경로로 통일 | 외부에서 레거시 엔진 API를 호출했다면 전환 필요 |
| 서비스 보안 | 일반 사용자 환경파일 접근 가능 | `.env`를 root 전용 `600`으로 보호하고 systemd 운영 명령 제공 | 보안 설정 후 `aerial-status`, `aerial-restart`, `aerial-logs` 사용 |
| 재부팅 복구 | 외장 디스크·GPU 초기화 순서에 민감 | 외장 디스크 마운트 의존성과 GPU watchdog 지원 | 외장 디스크가 `/etc/fstab`으로 부팅 시 마운트되는지 확인 |

### v2에서 추가되는 DB 마이그레이션

업데이트 시 API가 시작되면서 다음 9개 마이그레이션을 자동 실행합니다.

| 변경 | 목적 |
|---|---|
| `projects.source_deleted` | 원본 이미지 삭제 여부 기록 |
| `projects.ortho_thumbnail_path` | 정사영상 썸네일 경로 저장 |
| `images.project_id` 인덱스 | 프로젝트 이미지 조회 성능 개선 |
| 이미지 검증 상태 필드 | 이미지 검증 결과와 오류 기록 |
| 처리 작업 CRS 보정 필드 | 잘못된 CRS 복구 상태와 오류 기록 |
| 프로젝트별 이미지 파일명 고유 제약 | 동일 프로젝트의 중복 파일명 방지 |
| 처리 작업 생성·대기 시각 및 활성 작업 제약 | 프로젝트별 동시 활성 작업 1개 보장 |
| 처리 옵션 JSON 저장 | 작업별 실제 처리 옵션 보존 |
| 카메라 모델 공유 제약·인덱스 | 기본/조직 카메라 모델 정책 통일 |

중복 이미지명, 중복 활성 작업 또는 카메라 모델 정합성 문제가 있으면
마이그레이션은 데이터를 임의로 삭제하지 않고 중단됩니다. 따라서 아래
사전검사를 반드시 실행해야 합니다.

---

## 3. `[필수]` 업데이트 후 유지되어야 하는 데이터

업데이트는 애플리케이션 이미지만 바꾸는 작업입니다. 다음 데이터는 기존
위치와 값을 유지해야 합니다.

| 데이터 | 보관 위치 | 보호 방법 |
|---|---|---|
| 프로젝트·사용자·작업 이력 | PostgreSQL `pgdata` Docker 볼륨 | DB dump 생성 및 기존 Compose 프로젝트명 재사용 |
| Redis 작업 큐 | `redis_data` Docker 볼륨 | 처리 작업이 없는 상태에서 업데이트 |
| Metashape 라이선스 상태 | `engine-license` Docker 볼륨 | 기존 Compose 프로젝트명 재사용 |
| DB/JWT/MinIO/라이선스 비밀값 | 기존 `.env` | 권한 `600`으로 백업 후 새 버전에 복사 |
| 프로젝트 원본·처리 파일 | `PROCESSING_DATA_PATH`, `LOCAL_STORAGE_PATH/projects` | 기존 절대경로 유지 |
| 최종 정사영상 | `EXPORT_ROOT_PATH` | 기존 절대경로 유지 |
| 오프라인 지도 타일 | `TILES_PATH` | 기존 절대경로 유지 |
| MinIO 객체 | `MINIO_DATA_PATH` | MinIO 사용 시 경로와 계정값 유지 |
| SSL 인증서 | 기존 설치 폴더의 `ssl/` | 필요한 경우 새 폴더로 복사 |

DB dump에는 외장 디스크의 프로젝트 파일, 정사영상, 타일 및 MinIO 객체가
포함되지 않습니다. 이 데이터는 원래 디렉터리를 삭제하지 말고, 가능하면
디스크 스냅샷이나 별도 백업 장치에도 보관합니다.

### 공유 디스크를 사용하는 권장 예시

다른 스택과 `orthomosaic`, `tiles`를 공유하는 환경의 예시입니다.

```text
/media/innopam/Innopam_4TB/
├── aerial-survey/
│   ├── projects/       # Aerial Survey Manager 프로젝트/처리 데이터
│   └── minio/          # Aerial Survey Manager MinIO 데이터
├── orthomosaic/        # 다른 스택과 공유하는 최종 정사영상
└── tiles/              # 다른 스택과 공유하는 오프라인 지도 타일
```

이에 대응하는 환경변수 예시는 다음과 같습니다.

```dotenv
AERIAL_DATA_ROOT=/media/innopam/Innopam_4TB
PROCESSING_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/projects
LOCAL_STORAGE_PATH=/media/innopam/Innopam_4TB/aerial-survey
EXPORT_ROOT_PATH=/media/innopam/Innopam_4TB/orthomosaic
MINIO_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/minio
TILES_PATH=/media/innopam/Innopam_4TB/tiles
```

위 예시는 실제 배포 PC의 경로가 정확히 같을 때만 사용합니다. 기존
`.env`의 경로가 다르면 기존 값을 우선 보존합니다.

---

## 4. `[필수]` 전체 작업 순서

업데이트는 다음 순서로 진행합니다.

1. 기존 서비스와 처리 작업 상태 확인
2. 기존 Compose 프로젝트명·볼륨·스토리지 방식 확인
3. DB 마이그레이션 사전검사
4. `.env`, DB, 인증서 및 운영 정보 백업
5. 새 패키지 무결성 확인, 압축 해제, Docker 이미지 로드
6. 기존 `.env`를 새 버전으로 복사하고 신규 환경변수 보완
7. 새 Compose가 기존 DB 볼륨을 재사용하는지 확인
8. 기존 서비스를 중지
9. 새 DB 컨테이너만 먼저 시작하여 볼륨 일치 여부 재확인
10. 전체 서비스 시작 및 DB 마이그레이션 확인
11. 웹·DB·스토리지·GPU·타일·정사영상 기능 확인
12. systemd 고정 경로와 외장 디스크 부팅 순서 갱신
13. 운영 승인 후 기존 버전 보관 또는 정리

이미지 로드는 기존 서비스가 실행 중인 상태에서도 할 수 있습니다. 이를
먼저 수행하면 실제 서비스 중단 시간을 줄일 수 있습니다.

---

## 5. `[필수]` 작업 전 준비

### 5.1 준비물

배포 PC에 다음 두 파일을 같은 디렉터리에 준비합니다.

```text
aerial-survey-manager-v2.0.1.tar.gz
aerial-survey-manager-v2.0.1.sha256
```

패키지 정보:

| 항목 | 값 |
|---|---|
| 버전 | `2.0.1` |
| 빌드 Git 커밋 | `3e7c420c2cc8f6ed12417c4d16c7a4dd89f217a0` |
| SHA-256 | `eaf1ea75484eea1964879463007b00070796b05bffe4798cbb3a47f69c158fe3` |
| 기본 웹 포트 | `18100` |

### 5.2 호스트 환경 확인

```bash
docker --version
docker compose version
nvidia-smi
nvidia-ctk --version
df -h
```

권장 기준:

- Docker 24 이상
- Docker Compose v2
- NVIDIA 드라이버 525 이상
- NVIDIA Container Toolkit 설치
- 패키지 압축 해제와 이미지 로드를 위한 충분한 시스템 디스크 공간
- 프로젝트·정사영상 저장 디스크 여유 공간

Docker 권한 오류가 발생하면 이후 `docker` 또는 `docker compose` 명령
앞에 `sudo`를 붙입니다.

### 5.3 작업 시간 확보

- 패키지 검증: 디스크 속도에 따라 수 분
- Docker 이미지 로드: 수 분에서 수십 분
- 실제 서비스 중단: 일반적으로 10~30분
- DB가 크거나 사전 데이터 문제가 있으면 더 오래 걸릴 수 있음

---

## 6. `[필수]` 기존 설치 상태 확인

이 절의 명령은 **기존 버전 설치 폴더**에서 실행합니다.

### 6.1 기존 설치 폴더로 이동

기존 서비스 폴더를 모르면 다음 명령으로 systemd 설정을 확인합니다.

```bash
systemctl cat aerial-survey.service | grep -E 'WorkingDirectory|EnvironmentFile|ExecStart'
```

고정 symlink가 있다면 다음으로 실제 폴더를 확인할 수 있습니다.

```bash
readlink -f "$HOME/aerial-survey-manager-current"
```

기존 설치 폴더로 이동한 뒤 현재 경로를 변수에 저장합니다.

```bash
cd /기존/Aerial-Survey-Manager/설치경로

OLD_DIR="$(pwd -P)"
BACKUP_DIR="$HOME/aerial-upgrade-backup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

printf '기존 폴더: %s\n백업 폴더: %s\n' "$OLD_DIR" "$BACKUP_DIR"
```

이후 절차는 같은 터미널에서 계속 진행하는 것이 가장 안전합니다.

### 6.2 현재 서비스와 버전 확인

```bash
sudo docker compose ps
curl -fsS http://127.0.0.1:18100/health || true
curl -fsS http://127.0.0.1:8081/health || true
```

현재 사용 중인 포트에 따라 둘 중 하나만 성공할 수 있습니다.

브라우저에서도 현재 주소로 로그인하여 다음을 확인합니다.

- 기존 계정으로 로그인 가능
- 프로젝트 목록 표시
- 처리 중인 프로젝트 없음
- 업로드 또는 내보내기 작업 없음

처리 중인 작업이 있으면 여기서 중단합니다.

### 6.3 실제 Compose 프로젝트명 확인

Docker 볼륨 이름은 Compose 프로젝트명에 따라 결정됩니다. 새 버전에서
이 값을 동일하게 사용해야 기존 DB와 엔진 라이선스 볼륨이 연결됩니다.

```bash
DB_CONTAINER="$(sudo docker compose ps -q db)"

if [ -z "$DB_CONTAINER" ]; then
    echo "중단: 실행 중인 DB 컨테이너를 찾을 수 없습니다."
else
    OLD_PROJECT="$(sudo docker inspect "$DB_CONTAINER" \
        --format '{{ index .Config.Labels "com.docker.compose.project" }}')"
    echo "기존 Compose 프로젝트명: $OLD_PROJECT"
fi
```

값이 비어 있으면 업데이트를 진행하지 말고 기존 서비스 상태부터
확인합니다.

확인된 값을 백업 폴더에 기록합니다.

```bash
printf '%s\n' "$OLD_PROJECT" > "$BACKUP_DIR/old-compose-project.txt"
```

### 6.4 DB와 라이선스 볼륨 이름 확인

```bash
OLD_DB_VOLUME="$(sudo docker inspect "$DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

OLD_LICENSE_VOLUME="$(sudo docker inspect \
    "$(sudo docker compose ps -q worker-engine 2>/dev/null)" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/tmp/agisoft/licensing"}}{{.Name}}{{end}}{{end}}' \
    2>/dev/null || true)"

printf 'DB 볼륨: %s\n라이선스 볼륨: %s\n' \
    "$OLD_DB_VOLUME" "$OLD_LICENSE_VOLUME"

printf '%s\n' "$OLD_DB_VOLUME" > "$BACKUP_DIR/old-db-volume.txt"
printf '%s\n' "$OLD_LICENSE_VOLUME" > "$BACKUP_DIR/old-license-volume.txt"
```

DB 볼륨 값이 비어 있으면 중단합니다.

```bash
if [ -z "$OLD_DB_VOLUME" ]; then
    echo "중단: 기존 PostgreSQL 데이터 볼륨을 확인할 수 없습니다."
fi
```

### 6.5 기존 스토리지 방식 확인

먼저 `.env`에 `STORAGE_BACKEND`가 있는지 확인합니다.

```bash
sudo grep -E '^(STORAGE_BACKEND|COMPOSE_PROJECT_NAME|AERIAL_DATA_ROOT|LOCAL_STORAGE_PATH|PROCESSING_DATA_PATH|EXPORT_ROOT_PATH|MINIO_DATA_PATH|TILES_PATH|HOST_BIND|AERIAL_WEB_PORT|WEB_PORT)=' .env \
    || true
```

비밀번호, JWT 키, MinIO 비밀키 및 엔진 라이선스 키는 화면에 출력하지
않습니다.

스토리지 방식을 다음 명령으로 판정합니다.

```bash
OLD_STORAGE="$(sudo grep '^STORAGE_BACKEND=' .env 2>/dev/null \
    | tail -n 1 | cut -d= -f2-)"

if [ -z "$OLD_STORAGE" ]; then
    if sudo docker compose ps --services --status running | grep -qx minio; then
        OLD_STORAGE="minio"
    else
        OLD_STORAGE="local"
    fi
fi

echo "기존 스토리지 방식: $OLD_STORAGE"
printf '%s\n' "$OLD_STORAGE" > "$BACKUP_DIR/old-storage-backend.txt"
```

판정 결과가 `local` 또는 `minio`가 아니면 중단합니다.

### 6.6 외장 디스크 경로 확인

```bash
sudo grep -E '^(AERIAL_DATA_ROOT|LOCAL_STORAGE_PATH|PROCESSING_DATA_PATH|EXPORT_ROOT_PATH|MINIO_DATA_PATH|TILES_PATH)=' .env \
    || true

findmnt
df -h
```

각 경로가 실제 대용량 디스크를 가리키고 있는지 확인합니다.

`/media/사용자명/디스크명`처럼 데스크톱 로그인 후 자동 마운트되는 경로는
재부팅 시 Docker보다 늦게 준비될 수 있습니다. 운영용 디스크는 가능하면
`/etc/fstab`으로 부팅 시 자동 마운트되게 설정합니다.

---

## 7. `[필수]` DB 마이그레이션 사전검사

다음 쿼리는 데이터를 변경하지 않고, v2 마이그레이션을 방해할 수 있는
기존 데이터만 조회합니다.

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey <<'SQL'
\echo '1) 동일 프로젝트의 중복 이미지 파일명'
SELECT project_id, filename, COUNT(*) AS duplicate_count
FROM images
GROUP BY project_id, filename
HAVING COUNT(*) > 1;

\echo '2) 프로젝트별 중복 활성 처리 작업'
SELECT project_id, COUNT(*) AS active_count
FROM processing_jobs
WHERE status IN ('scheduled', 'queued', 'processing')
GROUP BY project_id
HAVING COUNT(*) > 1;

\echo '3) 이름이 비어 있는 카메라 모델'
SELECT id, name
FROM camera_models
WHERE btrim(name) = '';

\echo '4) 공유 범위가 잘못된 카메라 모델'
SELECT id, name, is_custom, organization_id
FROM camera_models
WHERE NOT (
    (is_custom = false AND organization_id IS NULL)
    OR
    (is_custom = true AND organization_id IS NOT NULL)
);

\echo '5) 같은 공유 범위의 중복 카메라 모델명'
SELECT organization_id,
       lower(btrim(name)) AS normalized_name,
       COUNT(*) AS duplicate_count
FROM camera_models
GROUP BY organization_id, lower(btrim(name))
HAVING COUNT(*) > 1;
SQL
```

각 조회 결과가 모두 `(0 rows)`여야 합니다.

하나라도 데이터가 나오면 업데이트를 중단합니다. 해당 레코드를 임의로
삭제하지 말고 결과를 개발 담당자에게 전달하여 정리 방법을 결정합니다.

---

## 8. `[필수]` 백업

### 8.1 기존 환경 설정 백업

```bash
sudo cp "$OLD_DIR/.env" "$BACKUP_DIR/old.env"
sudo chown "$(id -u):$(id -g)" "$BACKUP_DIR/old.env"
chmod 600 "$BACKUP_DIR/old.env"

cp "$OLD_DIR"/docker-compose*.yml "$BACKUP_DIR/" 2>/dev/null || true
sudo systemctl cat aerial-survey.service \
    > "$BACKUP_DIR/aerial-survey.service.txt" 2>/dev/null || true
sudo systemctl cat aerial-gpu-watchdog.timer \
    > "$BACKUP_DIR/aerial-gpu-watchdog.timer.txt" 2>/dev/null || true
```

SSL 인증서를 사용하는 경우 함께 백업합니다.

```bash
if [ -d "$OLD_DIR/ssl" ]; then
    sudo cp -a "$OLD_DIR/ssl" "$BACKUP_DIR/"
    sudo chown -R "$(id -u):$(id -g)" "$BACKUP_DIR/ssl"
fi
```

### 8.2 PostgreSQL DB 백업

기존 서비스가 실행 중인 상태에서 custom-format dump를 생성합니다.

```bash
cd "$OLD_DIR"

sudo docker compose exec -T db \
    pg_dump -U postgres -d aerial_survey -Fc \
    > "$BACKUP_DIR/aerial_survey_before_v2.dump"
```

파일이 비어 있지 않은지 확인합니다.

```bash
test -s "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    && echo "DB 백업 파일 생성: 정상" \
    || echo "중단: DB 백업 파일이 비어 있음"

ls -lh "$BACKUP_DIR/aerial_survey_before_v2.dump"
```

백업 목록을 읽을 수 있는지 확인합니다.

```bash
sudo docker compose exec -T db pg_restore -l \
    < "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    | sed -n '1,20p'
```

오류 없이 객체 목록이 나오면 DB dump가 읽히는 상태입니다.

### 8.3 업데이트 전 프로젝트 수 기록

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;" \
    > "$BACKUP_DIR/project-count-before.txt"

sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM images;" \
    > "$BACKUP_DIR/image-count-before.txt"

printf '프로젝트 수: '; cat "$BACKUP_DIR/project-count-before.txt"
printf '이미지 레코드 수: '; cat "$BACKUP_DIR/image-count-before.txt"
```

### 8.4 외부 데이터 경로 기록

실제 `.env`에서 확인한 경로를 사용하여 용량과 파일 수를 기록합니다.

예:

```bash
du -sh /media/innopam/Innopam_4TB/aerial-survey 2>/dev/null || true
du -sh /media/innopam/Innopam_4TB/orthomosaic 2>/dev/null || true
du -sh /media/innopam/Innopam_4TB/tiles 2>/dev/null || true
```

MinIO를 사용한다면 `MINIO_DATA_PATH`도 반드시 확인합니다.

```bash
MINIO_PATH="$(sudo grep '^MINIO_DATA_PATH=' "$OLD_DIR/.env" \
    | tail -n 1 | cut -d= -f2-)"

if [ -n "$MINIO_PATH" ]; then
    du -sh "$MINIO_PATH"
fi
```

### 8.5 백업 완료 게이트

다음 항목이 모두 확인되어야 다음 단계로 이동합니다.

- [ ] `old.env`가 있고 크기가 0이 아님
- [ ] DB dump가 있고 `pg_restore -l`로 읽힘
- [ ] 업데이트 전 프로젝트 수를 기록함
- [ ] 기존 Compose 프로젝트명을 기록함
- [ ] 기존 DB 볼륨 이름을 기록함
- [ ] 기존 스토리지 방식이 `local` 또는 `minio`로 판정됨
- [ ] 프로젝트·정사영상·타일·MinIO 실제 경로를 확인함
- [ ] 처리 중인 작업이 없음

---

## 9. `[필수]` 새 패키지 준비

이 단계는 기존 서비스가 실행 중인 상태에서 수행할 수 있습니다.

아래 예시는 패키지 두 파일을 사용자의 홈 디렉터리에 복사한 경우입니다.

### 9.1 무결성 확인

```bash
cd "$HOME"

sha256sum -c aerial-survey-manager-v2.0.1.sha256
```

정상 결과:

```text
aerial-survey-manager-v2.0.1.tar.gz: OK
```

`FAILED`가 나오면 압축을 풀지 말고 파일을 다시 복사합니다.

### 9.2 기존 새 버전 폴더 존재 여부 확인

```bash
NEW_DIR="$HOME/aerial-survey-manager-v2.0.1"

if [ -e "$NEW_DIR" ]; then
    echo "중단: 새 버전 폴더가 이미 존재합니다: $NEW_DIR"
else
    echo "압축 해제 가능"
fi
```

이미 같은 이름의 폴더가 있다면 기존 설치인지 중간 실패 폴더인지 확인한
후 이름을 바꾸거나 안전하게 정리합니다. 내용을 확인하지 않고 삭제하지
마십시오.

### 9.3 압축 해제

```bash
cd "$HOME"
tar -xzf aerial-survey-manager-v2.0.1.tar.gz
cd "$NEW_DIR"
```

패키지 버전과 빌드 정보를 확인합니다.

```bash
cat VERSION
cat BUILD_INFO.txt
```

정상 값:

```text
2.0.1
```

### 9.4 Docker 이미지 로드

```bash
cd "$NEW_DIR"
./load-images.sh
```

이미지 로드는 시간이 오래 걸릴 수 있습니다. 각 이미지에 `Loaded image`
또는 정상 로드 메시지가 나오면 기다립니다.

Docker 권한 오류가 발생하면 다음처럼 실행합니다.

```bash
sudo ./load-images.sh
```

---

## 10. `[필수]` 새 버전 `.env` 준비

**이 절에서도 `install.sh`는 실행하지 않습니다.**

### 10.1 기존 `.env` 복사

```bash
sudo cp "$BACKUP_DIR/old.env" "$NEW_DIR/.env"
sudo chown "$(id -u):$(id -g)" "$NEW_DIR/.env"
chmod 600 "$NEW_DIR/.env"

cd "$NEW_DIR"
cp .env .env.before-v2-merge
```

### 10.2 안전한 환경변수 갱신 함수 준비

아래 함수는 동일한 키가 있으면 값을 바꾸고, 없으면 마지막 줄에
추가합니다.

```bash
upsert_env() {
    key="$1"
    value="$2"

    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}
```

### 10.3 기존 Compose 프로젝트명 고정

이 값이 기존 DB와 라이선스 볼륨을 재사용하는 핵심입니다.

```bash
OLD_PROJECT="$(cat "$BACKUP_DIR/old-compose-project.txt")"
upsert_env COMPOSE_PROJECT_NAME "$OLD_PROJECT"
```

기존 `.env`에 이 값이 없었더라도 반드시 추가합니다.

### 10.4 기존 스토리지 방식 유지

```bash
OLD_STORAGE="$(cat "$BACKUP_DIR/old-storage-backend.txt")"
upsert_env STORAGE_BACKEND "$OLD_STORAGE"
```

#### `[조건부: local]` 기존 스토리지가 local인 경우

```bash
upsert_env COMPOSE_PROFILES ""
```

`LOCAL_STORAGE_PATH`, `PROCESSING_DATA_PATH`, `EXPORT_ROOT_PATH`,
`TILES_PATH`를 기존 경로와 동일하게 유지합니다.

#### `[조건부: MinIO]` 기존 스토리지가 minio인 경우

```bash
upsert_env COMPOSE_PROFILES "minio"
```

다음 값은 기존 `.env` 값을 그대로 유지해야 합니다.

```text
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
MINIO_DATA_PATH
```

기존 MinIO 데이터를 로컬 스토리지로 옮기는 작업은 단순 버전 업데이트와
다른 데이터 마이그레이션입니다. 이 업데이트 과정에서
`STORAGE_BACKEND=minio`를 `local`로 바꾸지 마십시오.

### 10.5 기존 웹 포트 유지

v1 계열에서 `AERIAL_WEB_PORT`가 없고 `WEB_PORT`만 있다면 기존 포트를 새
변수로 옮깁니다.

```bash
CURRENT_WEB_PORT="$(grep '^AERIAL_WEB_PORT=' .env \
    | tail -n 1 | cut -d= -f2-)"

if [ -z "$CURRENT_WEB_PORT" ]; then
    CURRENT_WEB_PORT="$(grep '^WEB_PORT=' .env \
        | tail -n 1 | cut -d= -f2-)"
fi

CURRENT_WEB_PORT="${CURRENT_WEB_PORT:-18100}"

upsert_env HOST_BIND "0.0.0.0"
upsert_env AERIAL_WEB_PORT "$CURRENT_WEB_PORT"

echo "업데이트 후 웹 포트: $CURRENT_WEB_PORT"
```

기존 URL을 바꾸고 싶다면 이 단계에서만 새 포트로 지정합니다. 방화벽과
다른 스택의 포트 충돌도 함께 확인해야 합니다.

기존 설치에서 실제 SSL 인증서를 사용했다면 백업한 인증서를 새 폴더에
복사합니다.

```bash
if [ -f "$BACKUP_DIR/ssl/cert.pem" ] \
    && [ -f "$BACKUP_DIR/ssl/key.pem" ]; then
    cp "$BACKUP_DIR/ssl/cert.pem" "$NEW_DIR/ssl/cert.pem"
    cp "$BACKUP_DIR/ssl/key.pem" "$NEW_DIR/ssl/key.pem"
    chmod 600 "$NEW_DIR"/ssl/*.pem
fi
```

v2 배포 Compose의 표준 외부 진입점은 `AERIAL_WEB_PORT`의 HTTP 포트
하나입니다. 기존 v1 환경에서 `HTTPS_PORT=443`으로 직접 접속했다면 이
값만 복사해서는 443 포트가 다시 열리지 않습니다. 기존 외부 reverse
proxy를 계속 사용하거나, HTTPS 노출 방식을 담당자와 별도로 결정한 뒤
전환합니다.

### 10.6 v2 필수·권장 변수 보완

```bash
upsert_env ALLOW_WEAK_JWT_SECRET "false"
upsert_env AERIAL_CONTAINER_UID "$(id -u)"
upsert_env AERIAL_CONTAINER_GID "$(id -g)"
upsert_env AUTO_EXPORT_ENABLED "false"
upsert_env AUTO_EXPORT_TARGET_CRS "EPSG:5186"
upsert_env ENABLE_GPU_ENGINE "true"
upsert_env NVIDIA_VISIBLE_DEVICES "all"
upsert_env NVIDIA_DRIVER_CAPABILITIES "compute,utility"
upsert_env TZ "Asia/Seoul"
upsert_env VITE_MAP_OFFLINE "true"
upsert_env VITE_TILE_URL "/tiles/{z}/{x}/{y}"
```

`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `MINIO_SECRET_KEY`,
`ENGINE_LICENSE_KEY`는 새로 생성하지 않고 기존 값을 유지합니다.

기존 DB에 사용자가 있으면 `ADMIN_EMAIL`, `ADMIN_PASSWORD`는 기존 계정의
비밀번호를 덮어쓰지 않습니다. 업데이트를 위해 새 계정을 만들 필요도
없습니다.

비밀값 자체를 출력하지 않고 필수값 존재 여부를 확인합니다.

```bash
POSTGRES_PASSWORD_LENGTH="$(awk '
    /^POSTGRES_PASSWORD=/ {
        sub(/^POSTGRES_PASSWORD=/, "")
        print length($0)
        exit
    }
' .env)"

JWT_SECRET_LENGTH="$(awk '
    /^JWT_SECRET_KEY=/ {
        sub(/^JWT_SECRET_KEY=/, "")
        print length($0)
        exit
    }
' .env)"

ENGINE_LICENSE_LENGTH="$(awk '
    /^ENGINE_LICENSE_KEY=/ {
        sub(/^ENGINE_LICENSE_KEY=/, "")
        print length($0)
        exit
    }
' .env)"

printf 'DB 비밀번호 설정: %s\n' \
    "$([ "${POSTGRES_PASSWORD_LENGTH:-0}" -gt 0 ] && echo yes || echo no)"
printf 'JWT 키 길이 기준 충족: %s\n' \
    "$([ "${JWT_SECRET_LENGTH:-0}" -ge 32 ] && echo yes || echo no)"
printf '엔진 라이선스 키 설정: %s\n' \
    "$([ "${ENGINE_LICENSE_LENGTH:-0}" -gt 0 ] && echo yes || echo no)"
```

DB 비밀번호가 비어 있거나 JWT 키가 32자 미만이면 서비스를 중지하지
말고 기존 `.env`와 백업을 다시 확인합니다. 기존 JWT 키를 임의로 새로
만들면 기존 로그인 세션은 무효화되므로 담당자 승인 없이 변경하지
않습니다.

### 10.7 저장소 경로 확인

```bash
grep -E '^(STORAGE_BACKEND|COMPOSE_PROFILES|AERIAL_DATA_ROOT|LOCAL_STORAGE_PATH|PROCESSING_DATA_PATH|EXPORT_ROOT_PATH|MINIO_DATA_PATH|TILES_PATH|HOST_BIND|AERIAL_WEB_PORT|COMPOSE_PROJECT_NAME)=' .env
```

비밀번호가 포함된 키는 출력하지 않습니다.

다른 스택과 정사영상 및 타일을 공유하는 예시는 다음과 같습니다.

```dotenv
AERIAL_DATA_ROOT=/media/innopam/Innopam_4TB
PROCESSING_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/projects
LOCAL_STORAGE_PATH=/media/innopam/Innopam_4TB/aerial-survey
EXPORT_ROOT_PATH=/media/innopam/Innopam_4TB/orthomosaic
MINIO_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/minio
TILES_PATH=/media/innopam/Innopam_4TB/tiles
```

주의:

- `LOCAL_STORAGE_PATH`에는 `projects`까지 쓰지 않습니다.
  Compose가 뒤에 `/projects`를 붙입니다.
- `PROCESSING_DATA_PATH`는 프로젝트 디렉터리 자체를 지정합니다.
- `EXPORT_ROOT_PATH`와 `TILES_PATH`는 공유 경로를 그대로 사용합니다.
- `MINIO_DATA_PATH`를 `PROCESSING_DATA_PATH`와 같은 디렉터리로 지정하지
  않습니다.

### 10.8 저장소 권한 사전확인

v2의 API와 일반 Celery 워커는 `.env`의 `AERIAL_CONTAINER_UID/GID`로
실행됩니다. v1에서 root가 만든 기존 파일은 새 컨테이너가 읽거나 쓰지
못할 수 있습니다.

```bash
id

PROCESSING_PATH="$(grep '^PROCESSING_DATA_PATH=' .env \
    | tail -n 1 | cut -d= -f2-)"
LOCAL_PATH="$(grep '^LOCAL_STORAGE_PATH=' .env \
    | tail -n 1 | cut -d= -f2-)"
EXPORT_PATH="$(grep '^EXPORT_ROOT_PATH=' .env \
    | tail -n 1 | cut -d= -f2-)"
TILE_PATH="$(grep '^TILES_PATH=' .env \
    | tail -n 1 | cut -d= -f2-)"

for path in \
    "$PROCESSING_PATH" \
    "$LOCAL_PATH" \
    "$EXPORT_PATH" \
    "$TILE_PATH"; do
    if [ -n "$path" ]; then
        ls -ld "$path"
    fi
done
```

프로젝트·처리·정사영상 경로에는 설치 사용자의 쓰기 권한이 필요하고,
타일 경로는 읽기 권한만 있으면 됩니다.

간단한 쓰기 확인:

```bash
check_write_dir() {
    path="$1"
    label="$2"
    test_file="$path/.aerial-write-test-$$"

    if [ -z "$path" ] || [ ! -d "$path" ]; then
        echo "확인 필요: $label 경로가 없거나 비어 있음: $path"
        return 1
    fi

    if touch "$test_file"; then
        rm "$test_file"
        echo "$label 쓰기: 정상"
    else
        echo "확인 필요: $label 쓰기 실패"
        return 1
    fi
}

check_write_dir "$PROCESSING_PATH" "프로젝트/처리 경로"
check_write_dir "$LOCAL_PATH/projects" "로컬 프로젝트 경로"
check_write_dir "$EXPORT_PATH" "정사영상 경로"
```

`Permission denied`가 나오면 서비스를 중지하기 전에 권한 정책부터
결정합니다.

- Aerial Survey Manager 전용 경로는 설치 사용자 UID/GID가 쓰도록 조정
- 다른 스택과 공유하는 `orthomosaic`은 양쪽 스택이 사용하는 공통 그룹
  또는 ACL로 쓰기 권한 부여
- 공유 `tiles`는 Aerial Survey Manager에 읽기 권한만 부여
- MinIO 데이터 폴더는 MinIO 컨테이너 소유권을 확인하고 임의로 전체
  `chown -R`하지 않음

대용량 공유 폴더 전체에 무조건 `chmod 777` 또는 `chown -R`을 실행하지
마십시오.

### 10.9 네트워크 충돌 확인

v2 프로덕션 기본 대역은 `10.253.0.0/24`입니다.

```bash
ip route | grep '10\.253\.0\.0/24' || true
sudo docker network inspect \
    $(sudo docker network ls -q) \
    --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}' \
    2>/dev/null | grep '10\.253\.0\.0/24' || true
```

다른 스택이 이미 사용 중이면 `.env`에 충돌하지 않는 사설 대역을
지정합니다.

```dotenv
AERIAL_NETWORK_SUBNET=10.254.0.0/24
```

### 10.10 Compose 설정 검증

```bash
cd "$NEW_DIR"

sudo docker compose config >/dev/null \
    && echo "Compose 설정: 정상" \
    || echo "중단: Compose 설정 오류"

sudo docker compose config --images
```

오류가 나오면 서비스를 중지하지 말고 `.env`부터 수정합니다.

---

## 11. `[필수]` 기존 서비스 중지

이 단계부터 실제 서비스 중단이 시작됩니다.

브라우저 사용자에게 유지보수 시작을 알리고 다시 한번 처리 작업이 없는지
확인합니다.

### 11.1 systemd 서비스 중지

```bash
sudo systemctl stop aerial-survey 2>/dev/null || true
```

### 11.2 기존 폴더에서 Compose 서비스 중지

```bash
cd "$OLD_DIR"

sudo docker compose --profile engine down --remove-orphans
```

`-v`는 절대 붙이지 않습니다.

기존 프로젝트 컨테이너가 남아 있는지 확인합니다.

```bash
sudo docker ps -a \
    --filter "label=com.docker.compose.project=$OLD_PROJECT"
```

컨테이너 목록이 비어 있으면 정상입니다. Docker 볼륨은 남아 있어야
합니다.

```bash
sudo docker volume inspect "$OLD_DB_VOLUME" >/dev/null \
    && echo "기존 DB 볼륨 보존: 정상" \
    || echo "중단: 기존 DB 볼륨을 찾을 수 없음"
```

---

## 12. `[필수]` 새 버전 시작

### 12.1 DB만 먼저 시작

```bash
cd "$NEW_DIR"
sudo docker compose up -d db
```

DB가 healthy 상태가 될 때까지 기다립니다.

```bash
sudo docker compose ps db
```

### 12.2 기존 DB 볼륨 재사용 확인

```bash
NEW_DB_CONTAINER="$(sudo docker compose ps -q db)"

NEW_DB_VOLUME="$(sudo docker inspect "$NEW_DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

printf '기존 DB 볼륨: %s\n새 컨테이너 DB 볼륨: %s\n' \
    "$OLD_DB_VOLUME" "$NEW_DB_VOLUME"
```

두 값이 완전히 같아야 합니다.

```bash
if [ "$OLD_DB_VOLUME" = "$NEW_DB_VOLUME" ]; then
    echo "DB 볼륨 일치: 업데이트 계속 가능"
else
    echo "중단: 새 컨테이너가 기존 DB 볼륨을 사용하지 않음"
fi
```

값이 다르면 API를 시작하지 않습니다.

```bash
sudo docker compose down
```

그다음 `.env`의 `COMPOSE_PROJECT_NAME`이
`old-compose-project.txt`와 정확히 같은지 확인합니다.

### 12.3 API 시작 전 기존 프로젝트 수 확인

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;"
```

이 값이 `project-count-before.txt`와 같아야 합니다. `0`이거나 DB 자체가
없다는 오류가 나오면 중단합니다.

### 12.4 전체 서비스 시작

```bash
cd "$NEW_DIR"
sudo docker compose up -d
```

MinIO 방식이면 `.env`의 `COMPOSE_PROFILES=minio`에 의해 MinIO도 함께
시작됩니다.

초기 상태를 확인합니다.

```bash
sudo docker compose ps
```

### 12.5 최초 기동 대기

API가 다음 작업을 수행하므로 첫 시작에는 시간이 걸릴 수 있습니다.

- PostgreSQL 연결 대기
- 9개 DB 마이그레이션
- 카메라 모델 동기화
- 권역 데이터 확인
- 기존 사용자 확인

최초 10초 안에는 Nginx에서 `502 Bad Gateway`가 잠시 나올 수 있습니다.
이때 설치나 업데이트가 실패했다고 판단하지 말고 30~60초 기다립니다.

```bash
sleep 60
curl -i "http://127.0.0.1:${CURRENT_WEB_PORT}/health"
```

정상 결과:

```text
HTTP/1.1 200 OK
```

응답 JSON의 버전은 다음과 같아야 합니다.

```json
{"status":"healthy","app":"Aerial Survey Manager","version":"2.0.1"}
```

### 12.6 API 마이그레이션 로그 확인

```bash
sudo docker compose logs --tail=250 api
```

정상 로그의 핵심 문구:

```text
Migrations applied successfully.
Migrations completed.
Initial data seeding completed.
Application startup complete.
```

다음과 같은 문구가 나오면 마이그레이션이 중단된 것입니다.

```text
duplicate rows exist
one active processing job per project
camera model sharing scope
camera model name uniqueness
```

이 경우 서비스를 반복 재시작하거나 DB 레코드를 임의 삭제하지 말고,
로그와 사전검사 결과를 개발 담당자에게 전달합니다.

### 12.7 `[조건부: v2.0.0 운영 이력]` UUID 폴더 결과 변환

`v2.0.0`에서 생성된
`EXPORT_ROOT_PATH/{project_uuid}/...tif` 결과가 있을 때만 수행합니다.
DB와 `EXPORT_ROOT_PATH` 전체 백업이 끝났고 모든 정사영상 처리가 종료된
상태에서 먼저 dry-run을 확인합니다.

```bash
cd "$NEW_DIR"
sudo ./scripts/migrate-orthomosaic-layout.sh
```

`Migration plan`의 `OLD`/`NEW`가 올바르고 누락·추가 파일 경고가 없을 때만
파일 이동과 DB 경로 갱신을 함께 적용합니다.

```bash
sudo ./scripts/migrate-orthomosaic-layout.sh --apply
```

파일만 수동으로 옮기면 DB가 이전 경로를 계속 가리키므로 수동 `mv`는
사용하지 않습니다. 이 도구는 로컬 스토리지 배포 전용이며, MinIO 배포는
별도 이전 계획이 필요합니다.

---

## 13. `[필수]` 업데이트 후 검증

### 13.1 전체 헬스체크

```bash
cd "$NEW_DIR"
sudo bash scripts/healthcheck.sh
```

첫 실행에서 API만 `502`이고 나머지가 정상이라면 30~60초 후 다시
실행합니다.

### 13.2 컨테이너 상태

```bash
sudo docker compose ps
```

다음 서비스가 실행 중이어야 합니다.

```text
db
redis
api
frontend
nginx
celery-worker
celery-worker-thumbnail
flower
titiler
worker-engine
```

MinIO 방식이면 다음도 확인합니다.

```text
minio
```

`minio-init`는 초기화 후 정상 종료될 수 있습니다.

### 13.3 DB 데이터 수 비교

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;" \
    > "$BACKUP_DIR/project-count-after.txt"

sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM images;" \
    > "$BACKUP_DIR/image-count-after.txt"

printf '업데이트 전 프로젝트 수: '; cat "$BACKUP_DIR/project-count-before.txt"
printf '업데이트 후 프로젝트 수: '; cat "$BACKUP_DIR/project-count-after.txt"
printf '업데이트 전 이미지 수: '; cat "$BACKUP_DIR/image-count-before.txt"
printf '업데이트 후 이미지 수: '; cat "$BACKUP_DIR/image-count-after.txt"
```

프로젝트와 이미지 수가 업데이트 전과 같아야 합니다.

### 13.4 GPU와 처리 워커

```bash
nvidia-smi
sudo docker compose exec worker-engine nvidia-smi
sudo ./scripts/check-gpu-stack.sh
```

GPU 처리 워커 확인:

```bash
sudo docker compose exec celery-worker \
    celery -A app.workers.tasks inspect active --json
```

### 13.5 기존 계정 로그인

브라우저에서 기존에 사용하던 계정과 비밀번호로 로그인합니다.

- 기존 DB에 사용자가 있으면 새 `.env`의 `ADMIN_*` 값으로 비밀번호가
  변경되지 않습니다.
- 로그인이 안 되면서 프로젝트도 비어 있으면 새 DB 볼륨을 잘못 사용했을
  가능성이 큽니다.
- `install.sh`를 다시 실행하여 해결하려고 하지 마십시오.

### 13.6 프로젝트와 정사영상 확인

브라우저에서 다음을 확인합니다.

- 프로젝트 목록과 개수가 업데이트 전과 같음
- 프로젝트 상세 화면이 열림
- 기존 이미지 및 EO 정보가 표시됨
- EO 포인트 클릭 시 이미지가 실제 가로·세로 비율로 표시됨
- EO 미리보기 아래에 파일명과 X/Y/Z, Omega/Phi/Kappa 값이 표시됨
- 기존 정사영상이 지도에 표시됨
- RC.1 UUID 폴더를 변환했다면 최종 COG와 DB 경로가 같은 평면 파일을 가리킴
- 썸네일이 표시됨
- 처리 이력이 표시됨

정사영상이 보이지 않으면 경로를 확인합니다.

```bash
grep '^EXPORT_ROOT_PATH=' .env
sudo docker compose exec nginx ls -la /data/storage/orthomosaic | head
sudo docker compose exec api ls -la /data/storage/orthomosaic | head
```

### 13.7 EO 가져오기 개선 기능 확인

새 테스트 프로젝트 생성 화면에서 다음을 확인합니다.

- 서버 파일 브라우저에서 EO 파일을 선택할 수 있음
- 선택한 EO 파일명과 서버 경로가 표시됨
- EO의 X/Y/Z, Omega/Phi/Kappa 내용이 표에 표시됨
- 선택한 이미지와 일치한 행 수, 미매칭 행, 중복 이미지명, CRS 경고가 표시됨
- 유효한 EO 위치가 오른쪽 지도에 표시되고 필요한 행을 처리에서 제외할 수 있음

이 확인은 프로젝트를 실제로 생성하지 않고 EO 확인 화면까지만 진행해도 됩니다.

### 13.8 처리 중 좌표계(원점) 변경 확인

이 항목은 **테스트 처리 작업이 있을 때만 확인**합니다.

1. 테스트 프로젝트의 처리를 시작합니다.
2. 작업 상태가 `scheduled`, `queued`, `processing` 중 하나일 때 프로젝트
   처리 화면에서 **좌표계 변경**을 엽니다.
3. EO 파일의 원본 좌표가 실제로 사용하는 좌표계를 선택하고
   **변경 예약**을 누릅니다.
4. 예약된 좌표계가 표시되고 EO 포인트의 지도 위치가 새 좌표계 기준으로
   갱신되는지 확인합니다.
5. 최종 결과 저장 전에 예약을 다시 바꾸거나 취소할 수 있는지 확인합니다.

변경 예약은 결과 파일의 픽셀을 즉시 변환하는 작업이 아닙니다. 처리 워커가
최종 COG 생성과 목표 좌표계 재투영을 수행하기 직전에 원본 좌표계 태그를
바르게 지정하도록 예약하는 기능입니다. **최종 결과 저장 단계에 들어간
뒤에는 변경하거나 취소할 수 없습니다.**

### 13.9 오프라인 지도 타일 확인

```bash
grep '^TILES_PATH=' .env
sudo docker compose exec nginx \
    sh -c 'find /data/tiles -type f | head'
```

파일이 보이면 브라우저에서 `Ctrl+Shift+R`로 강력 새로고침합니다.

타일 구조:

```text
TILES_PATH/{z}/{x}/{y}.png
TILES_PATH/{z}/{x}/{y}.jpg
TILES_PATH/{z}/{x}/{y}.jpeg
```

기존 타일 폴더 안의 파일만 교체한 경우 Nginx 재시작이 필요 없습니다.
타일 폴더 자체를 삭제 후 재생성했다면 다음을 실행합니다.

```bash
sudo docker compose restart nginx
```

### 13.10 저장소 쓰기 권한 확인

```bash
grep -E '^(AERIAL_CONTAINER_UID|AERIAL_CONTAINER_GID|LOCAL_STORAGE_PATH|PROCESSING_DATA_PATH|EXPORT_ROOT_PATH)=' .env
```

API 로그에서 `Permission denied`가 없어야 합니다.

```bash
sudo docker compose logs --since=10m api celery-worker celery-worker-thumbnail \
    | grep -i 'permission denied' || true
```

### 13.11 기능 점검 체크리스트

- [ ] 기존 계정 로그인
- [ ] 프로젝트 목록 및 개수
- [ ] 기존 프로젝트 상세 화면
- [ ] EO 포인트 실제 비율 미리보기와 EO 값 표시
- [ ] EO 가져오기 표·지도 미리보기와 경고 표시
- [ ] 테스트 처리 중 좌표계(원점) 변경 예약·취소와 EO 위치 갱신
- [ ] 기존 썸네일
- [ ] 기존 정사영상
- [ ] 대시보드 오프라인 타일
- [ ] 새 테스트 프로젝트 생성
- [ ] 소량 이미지 등록 또는 업로드
- [ ] GPU 인식
- [ ] 처리 워커 활성
- [ ] API `/health` 200
- [ ] 버전 `2.0.1`

---

## 14. `[조건부·운영 필수]` 외장 디스크와 자동 시작 설정

기능 검증이 끝난 후 적용합니다.

### 14.1 `[조건부: 외장 디스크]` 외장 디스크 마운트 확인

예:

```bash
findmnt /media/innopam/Innopam_4TB
grep -F '/media/innopam/Innopam_4TB' /etc/fstab || true
```

데스크톱 로그인 후에만 자동 마운트되는 디스크라면 Docker보다 늦게
마운트되어 빈 디렉터리로 서비스가 시작될 수 있습니다. 운영 디스크는
가능하면 `/etc/fstab`에 등록합니다.

### 14.2 `[조건부: 외장 디스크]` Docker 마운트 의존성 설정

아래 경로는 실제 배포 PC의 마운트 지점으로 바꿉니다.

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d

printf '[Unit]\nRequiresMountsFor=/media/innopam/Innopam_4TB\n' \
    | sudo tee \
      /etc/systemd/system/docker.service.d/aerial-survey-mounts.conf

sudo systemctl daemon-reload
```

### 14.3 `[운영 필수]` 새 버전 systemd 경로 등록

반드시 **새 버전 폴더**에서 실행합니다.

```bash
cd "$NEW_DIR"
sudo bash scripts/secure-deployment.sh
```

이 작업은 다음을 수행합니다.

- `aerial-survey-manager-current` symlink를 새 버전으로 변경
- `aerial-survey.service` 갱신
- GPU watchdog service/timer 갱신
- `.env`를 root 전용 권한 `600`으로 변경
- 일반 운영 명령 설치

고정 경로가 새 버전을 가리키는지 확인합니다.

```bash
readlink -f "$(dirname "$NEW_DIR")/aerial-survey-manager-current"

systemctl cat aerial-survey.service \
    | grep -E 'WorkingDirectory|EnvironmentFile|ExecStart'
```

### 14.4 `[운영 필수]` systemd 상태 확인

```bash
systemctl status aerial-survey --no-pager
systemctl status aerial-gpu-watchdog.timer --no-pager
curl -fsS "http://127.0.0.1:${CURRENT_WEB_PORT}/health"
```

보안 설정 후 `.env`는 일반 사용자가 읽을 수 없습니다. 이후 일반 운영은
다음 명령을 사용합니다.

```bash
aerial-status
aerial-restart
aerial-logs
```

환경 설정을 직접 확인하거나 Compose 명령을 실행해야 하면 `sudo`를
사용합니다.

### 14.5 `[조건부: MinIO]` MinIO 사용 환경의 재시작 주의

`STORAGE_BACKEND=minio`인 환경에서 systemd 재시작 후 MinIO가 보이지
않으면 새 버전 폴더에서 다음 명령으로 MinIO를 다시 올립니다.

```bash
cd "$NEW_DIR"
sudo docker compose --profile minio up -d minio minio-init
sudo docker compose ps
```

재부팅 후에도 `minio` 컨테이너가 실행 중인지 반드시 확인합니다.

---

## 15. `[운영 필수]` 재부팅 검증

업데이트 직후 기능 검증이 모두 통과한 후 유지보수 시간에 재부팅
검증을 수행합니다.

```bash
sudo reboot
```

재부팅 후:

```bash
findmnt /media/innopam/Innopam_4TB
systemctl status docker --no-pager
systemctl status aerial-survey --no-pager
systemctl status aerial-gpu-watchdog.timer --no-pager
aerial-status
curl -fsS http://127.0.0.1:18100/health
```

기존 포트를 유지했다면 `18100` 대신 실제 `AERIAL_WEB_PORT`를 사용합니다.

브라우저에서 다시 확인합니다.

- 로그인
- 프로젝트 목록
- 기존 정사영상
- 오프라인 타일
- GPU 처리 워커

재부팅 후 데이터가 비어 보이면 새 프로젝트를 만들지 말고 즉시
외장 디스크 마운트 상태와 `.env` 경로를 확인합니다.

---

## 16. `[문제 발생 시]` 문제 해결

| 증상 | 가장 가능성 높은 원인 | 확인 및 조치 |
|---|---|---|
| 최초 기동 직후 `/health`가 502 | DB 마이그레이션·초기 데이터 확인 중 | 30~60초 기다린 후 재확인, `docker compose logs api` 확인 |
| 502가 계속됨 | API 마이그레이션 실패 또는 API 재시작 | `docker compose ps -a`, `docker compose logs --tail=250 api` |
| 로그인되지만 프로젝트가 0개 | 새 DB 볼륨을 잘못 사용 | 기존/새 DB 볼륨 이름 비교, `COMPOSE_PROJECT_NAME` 확인 |
| 기존 비밀번호로 로그인 불가 | 다른 DB 사용 또는 기존 계정 DB 미연결 | `install.sh` 재실행 금지, 프로젝트 수와 DB 볼륨부터 확인 |
| DB 마이그레이션에서 duplicate 오류 | 중복 이미지명 또는 중복 활성 작업 | 사전검사 SQL 결과를 개발 담당자에게 전달 |
| 카메라 모델 migration 오류 | 빈 이름, 잘못된 공유 범위, 중복 이름 | 임의 삭제 금지, 오류 레코드 확인 후 데이터 정리 |
| 정사영상이 안 보임 | `EXPORT_ROOT_PATH` 변경 또는 디스크 미마운트 | `.env`, `findmnt`, 컨테이너 `/data/storage/orthomosaic` 확인 |
| 타일 지도가 회색 | `TILES_PATH` 오류, 파일 구조 오류, 브라우저 캐시 | 컨테이너 `/data/tiles` 확인, `Ctrl+Shift+R`, 필요 시 Nginx 재시작 |
| 업로드·파일 생성 Permission denied | UID/GID 또는 디렉터리 소유권 불일치 | `AERIAL_CONTAINER_UID/GID`, 호스트 디렉터리 권한 확인 |
| MinIO 연결 실패 | v1 MinIO 환경이 v2에서 local로 바뀜 | `STORAGE_BACKEND=minio`, `COMPOSE_PROFILES=minio`, 기존 MinIO 비밀값 확인 |
| MinIO 컨테이너가 없음 | MinIO 프로필 미활성 | `docker compose --profile minio up -d minio minio-init` |
| worker-engine 미실행 | NVIDIA runtime 또는 라이선스 문제 | `check-gpu-stack.sh`, worker 로그, watchdog 상태 확인 |
| 컨테이너 GPU 접근 실패 | 드라이버/커널/Container Toolkit 문제 | 호스트 `nvidia-smi`, `nvidia-ctk`, 컨테이너 `nvidia-smi` 순서로 확인 |
| 포트 접속 불가 | `HOST_BIND`, `AERIAL_WEB_PORT`, 방화벽 | `.env`, `ss -ltnp`, `ufw status` 확인 |
| Docker 네트워크 생성 실패 | `10.253.0.0/24` 충돌 | `AERIAL_NETWORK_SUBNET`을 미사용 사설 대역으로 변경 |
| 보안 설정 후 `.env` permission denied | 정상적인 root-only 보호 | `sudo` 사용 또는 `aerial-*` 운영 명령 사용 |
| 재부팅 후 데이터가 사라진 것처럼 보임 | 외장 디스크가 Docker보다 늦게 마운트 | 서비스를 멈추고 `findmnt`, `/etc/fstab`, mount dependency 확인 |

### 문제 발생 시 수집할 정보

```bash
cd "$NEW_DIR"

sudo docker compose ps -a
sudo docker compose logs --tail=300 api
sudo docker compose logs --tail=200 db
sudo docker compose logs --tail=200 worker-engine
sudo ./scripts/check-gpu-stack.sh
sudo ./scripts/collect-logs.sh
```

DB 비밀번호, JWT 키, MinIO 비밀키, 엔진 라이선스 키가 포함된 `.env` 전체
내용은 메신저나 이슈에 붙이지 않습니다.

---

## 17. `[문제 발생 시]` 롤백

다음 경우 롤백을 검토합니다.

- API 마이그레이션 문제를 즉시 해결할 수 없음
- 기존 프로젝트 또는 정사영상 접근이 복구되지 않음
- 핵심 처리 기능이 운영 요구사항을 충족하지 못함

### 17.1 롤백 전 주의

v2 전환 후 새 프로젝트나 새 데이터가 생성되었다면, 업데이트 전 DB
백업으로 복원할 때 그 데이터는 사라집니다. 먼저 현재 v2 DB도 별도
백업하고 운영 책임자와 복원 시점을 결정합니다.

기존 외장 디스크 데이터와 MinIO 데이터는 삭제하지 않습니다.

### 17.2 새 버전 중지

```bash
cd "$NEW_DIR"
sudo systemctl stop aerial-survey 2>/dev/null || true
sudo docker compose down
```

`-v`를 붙이지 않습니다.

### 17.3 업데이트 전 DB 복원

같은 DB 볼륨을 v2 마이그레이션으로 변경했으므로, 기존 버전을 다시
시작하기 전에 업데이트 전 dump를 복원합니다.

```bash
cd "$NEW_DIR"
sudo docker compose up -d db
```

DB가 healthy가 된 후:

```bash
sudo docker compose exec -T db \
    dropdb -U postgres --if-exists aerial_survey

sudo docker compose exec -T db \
    createdb -U postgres aerial_survey

sudo docker compose exec -T db \
    pg_restore -U postgres -d aerial_survey --no-owner \
    < "$BACKUP_DIR/aerial_survey_before_v2.dump"
```

복원 후 프로젝트 수를 확인합니다.

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;"
```

업데이트 전 기록과 같아야 합니다.

DB만 다시 중지합니다.

```bash
sudo docker compose down
```

### 17.4 기존 버전 재시작

```bash
cd "$OLD_DIR"
sudo docker compose --profile engine up -d
```

기존 버전 폴더에 `secure-deployment.sh`가 있다면 systemd 고정 경로도
기존 버전으로 되돌립니다.

```bash
cd "$OLD_DIR"
sudo bash scripts/secure-deployment.sh
```

검증:

```bash
sudo docker compose ps
curl -i http://127.0.0.1:기존포트/health
```

브라우저에서 기존 계정, 프로젝트, 정사영상 및 처리 기능을 확인합니다.

---

## 18. `[검증 후]` 업데이트 완료 후 정리

최소 며칠간 운영 검증이 끝날 때까지 다음 항목을 보관합니다.

- 기존 버전 설치 폴더
- 업데이트 전 `.env`
- DB dump
- 기존 Compose 프로젝트명·볼륨 기록
- 기존 SSL 인증서
- 업데이트 전후 프로젝트 수 기록

바로 삭제하지 않는 것이 좋은 항목:

```text
~/기존-aerial-survey-manager-폴더
~/aerial-upgrade-backup-YYYYMMDD-HHMMSS
기존 Docker 이미지
기존 Docker 볼륨
```

운영 승인 후에도 DB dump와 `.env` 백업은 접근 권한을 제한하여 별도
백업 매체에 보관하는 것을 권장합니다.

---

## 19. `[필수]` 최종 완료 체크리스트

### 데이터 보호

- [ ] 처리 중인 작업 없이 업데이트함
- [ ] DB dump를 생성하고 읽기 검증함
- [ ] 기존 `.env`를 권한 `600`으로 보관함
- [ ] 기존 DB 볼륨 이름을 기록함
- [ ] 새 DB 컨테이너가 동일한 볼륨을 사용하는지 확인함
- [ ] 프로젝트·정사영상·타일·MinIO 경로를 변경하지 않음

### 서비스

- [ ] `/health`가 HTTP 200
- [ ] 버전이 `2.0.1`
- [ ] DB 마이그레이션 성공 로그 확인
- [ ] 모든 핵심 컨테이너 실행
- [ ] GPU와 worker-engine 정상
- [ ] 기존 계정 로그인

### 기능

- [ ] 프로젝트 수가 업데이트 전과 같음
- [ ] 기존 프로젝트 상세 화면 정상
- [ ] 썸네일 정상
- [ ] 정사영상 정상
- [ ] 오프라인 타일 정상
- [ ] 새 프로젝트 생성 가능
- [ ] 테스트 업로드 또는 로컬 경로 등록 가능

### 운영

- [ ] 외장 디스크가 부팅 시 자동 마운트됨
- [ ] Docker mount dependency 적용
- [ ] `aerial-survey-manager-current`가 새 버전을 가리킴
- [ ] `aerial-survey.service` 정상
- [ ] GPU watchdog timer 정상
- [ ] 재부팅 후 서비스와 데이터 재확인
- [ ] 롤백용 기존 폴더와 백업 보관

모든 항목이 확인되면 `v2.0.1` 업데이트가 완료된 것입니다.
