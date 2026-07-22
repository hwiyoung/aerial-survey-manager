# Aerial Survey Manager v2.0.1 간단 업데이트 가이드

> 상태: 작성 중인 초안. `v2.0.1` 릴리즈 후보가 만들어지기 전에는 이
> 절차로 운영 PC를 업데이트하지 마십시오.

기존 배포 PC의 Aerial Survey Manager를 `v2.0.1`로 업데이트하는
간단 실행 절차입니다.

문제가 생기거나 MinIO·SSL·경로 이전·롤백 설명이 필요하면
[상세 업데이트 가이드](UPGRADE_GUIDE.md)를 확인하십시오.

## 절대 금지

```bash
# 실행 금지: DB와 라이선스 볼륨이 삭제될 수 있음
docker compose down -v

# 실행 금지: 기존 비밀번호와 경로가 바뀔 수 있음
./scripts/install.sh
```

업데이트 전 처리 중인 프로젝트, 업로드 및 내보내기가 없어야 합니다.

---

## 1. 기존 설치 정보 확인

기존 버전 설치 폴더로 이동합니다.

```bash
cd /기존/설치경로

OLD_DIR="$(pwd -P)"
BACKUP_DIR="$HOME/aerial-upgrade-backup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

sudo docker compose ps
```

기존 Compose 프로젝트명과 DB 볼륨을 기록합니다.

```bash
DB_CONTAINER="$(sudo docker compose ps -q db)"

OLD_PROJECT="$(sudo docker inspect "$DB_CONTAINER" \
    --format '{{ index .Config.Labels "com.docker.compose.project" }}')"

OLD_DB_VOLUME="$(sudo docker inspect "$DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

printf '기존 프로젝트명: %s\n기존 DB 볼륨: %s\n' \
    "$OLD_PROJECT" "$OLD_DB_VOLUME"

printf '%s\n' "$OLD_PROJECT" > "$BACKUP_DIR/old-compose-project.txt"
printf '%s\n' "$OLD_DB_VOLUME" > "$BACKUP_DIR/old-db-volume.txt"
```

두 값 중 하나라도 비어 있으면 업데이트를 중단합니다.

스토리지 방식을 확인합니다.

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

---

## 2. DB 사전검사

다음 쿼리 결과가 모두 `(0 rows)`여야 합니다.

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey <<'SQL'
\echo '중복 이미지 파일명'
SELECT project_id, filename, COUNT(*)
FROM images
GROUP BY project_id, filename
HAVING COUNT(*) > 1;

\echo '프로젝트별 중복 활성 작업'
SELECT project_id, COUNT(*)
FROM processing_jobs
WHERE status IN ('scheduled', 'queued', 'processing')
GROUP BY project_id
HAVING COUNT(*) > 1;

\echo '잘못된 카메라 모델'
SELECT id, name, is_custom, organization_id
FROM camera_models
WHERE btrim(name) = ''
   OR NOT (
       (is_custom = false AND organization_id IS NULL)
       OR
       (is_custom = true AND organization_id IS NOT NULL)
   );

\echo '중복 카메라 모델명'
SELECT organization_id, lower(btrim(name)), COUNT(*)
FROM camera_models
GROUP BY organization_id, lower(btrim(name))
HAVING COUNT(*) > 1;
SQL
```

레코드가 하나라도 나오면 서비스를 중지하지 말고 업데이트를 중단합니다.

---

## 3. `.env`와 DB 백업

```bash
sudo cp "$OLD_DIR/.env" "$BACKUP_DIR/old.env"
sudo chown "$(id -u):$(id -g)" "$BACKUP_DIR/old.env"
chmod 600 "$BACKUP_DIR/old.env"

sudo docker compose exec -T db \
    pg_dump -U postgres -d aerial_survey -Fc \
    > "$BACKUP_DIR/aerial_survey_before_v2.dump"

test -s "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    && echo "DB 백업: 정상" \
    || echo "중단: DB 백업 파일이 비어 있음"

sudo docker compose exec -T db pg_restore -l \
    < "$BACKUP_DIR/aerial_survey_before_v2.dump" \
    | sed -n '1,10p'
```

업데이트 전 프로젝트 수를 기록합니다.

```bash
sudo docker compose exec -T db \
    psql -U postgres -d aerial_survey -Atc \
    "SELECT count(*) FROM projects;" \
    > "$BACKUP_DIR/project-count-before.txt"

printf '업데이트 전 프로젝트 수: '
cat "$BACKUP_DIR/project-count-before.txt"
```

DB dump가 비어 있거나 `pg_restore`에서 오류가 나오면 중단합니다.

---

## 4. 새 패키지 준비

패키지 두 파일을 홈 디렉터리에 복사한 경우입니다.

```text
~/aerial-survey-manager-v2.0.1.tar.gz
~/aerial-survey-manager-v2.0.1.sha256
```

같은 이름의 새 버전 폴더가 없는지 먼저 확인합니다.

```bash
cd "$HOME"

NEW_DIR="$HOME/aerial-survey-manager-v2.0.1"

if [ -e "$NEW_DIR" ]; then
    echo "중단: 이미 폴더가 존재함: $NEW_DIR"
else
    echo "압축 해제 가능"
fi
```

`압축 해제 가능`이 나올 때만 실행합니다.

```bash
sha256sum -c aerial-survey-manager-v2.0.1.sha256
tar -xzf aerial-survey-manager-v2.0.1.tar.gz

cd "$NEW_DIR"

cat VERSION
cat BUILD_INFO.txt
./load-images.sh
```

체크섬은 `OK`, 버전은 `2.0.1`이어야 합니다.

---

## 5. 기존 `.env`를 새 버전에 적용

```bash
sudo cp "$BACKUP_DIR/old.env" "$NEW_DIR/.env"
sudo chown "$(id -u):$(id -g)" "$NEW_DIR/.env"
chmod 600 "$NEW_DIR/.env"

cd "$NEW_DIR"
cp .env .env.before-v2-merge
```

환경변수 갱신 함수를 입력합니다.

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

기존 프로젝트명과 스토리지 방식을 적용합니다.

```bash
OLD_PROJECT="$(cat "$BACKUP_DIR/old-compose-project.txt")"
OLD_STORAGE="$(cat "$BACKUP_DIR/old-storage-backend.txt")"

upsert_env COMPOSE_PROJECT_NAME "$OLD_PROJECT"
upsert_env STORAGE_BACKEND "$OLD_STORAGE"

if [ "$OLD_STORAGE" = "minio" ]; then
    upsert_env COMPOSE_PROFILES "minio"
else
    upsert_env COMPOSE_PROFILES ""
fi
```

기존 포트를 유지합니다.

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
upsert_env ALLOW_WEAK_JWT_SECRET "false"
upsert_env AERIAL_CONTAINER_UID "$(id -u)"
upsert_env AERIAL_CONTAINER_GID "$(id -g)"
upsert_env AUTO_EXPORT_ENABLED "false"
upsert_env AUTO_EXPORT_TARGET_CRS "EPSG:5186"
upsert_env ENABLE_GPU_ENGINE "true"
upsert_env TZ "Asia/Seoul"
```

저장소 경로를 확인합니다.

```bash
grep -E '^(COMPOSE_PROJECT_NAME|STORAGE_BACKEND|COMPOSE_PROFILES|AERIAL_DATA_ROOT|LOCAL_STORAGE_PATH|PROCESSING_DATA_PATH|EXPORT_ROOT_PATH|MINIO_DATA_PATH|TILES_PATH|HOST_BIND|AERIAL_WEB_PORT)=' .env
```

다른 스택과 정사영상·타일을 공유하는 현재 구성 예시:

```dotenv
AERIAL_DATA_ROOT=/media/innopam/Innopam_4TB
PROCESSING_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/projects
LOCAL_STORAGE_PATH=/media/innopam/Innopam_4TB/aerial-survey
EXPORT_ROOT_PATH=/media/innopam/Innopam_4TB/orthomosaic
MINIO_DATA_PATH=/media/innopam/Innopam_4TB/aerial-survey/minio
TILES_PATH=/media/innopam/Innopam_4TB/tiles
```

실제 기존 경로가 다르면 위 예시를 복사하지 말고 기존 값을 유지합니다.

Compose 설정을 검사합니다.

```bash
sudo docker compose config >/dev/null \
    && echo "Compose 설정: 정상" \
    || echo "중단: Compose 설정 오류"
```

오류가 나오면 기존 서비스를 중지하지 않습니다.

---

## 6. 기존 서비스 중지

```bash
sudo systemctl stop aerial-survey 2>/dev/null || true

cd "$OLD_DIR"
sudo docker compose --profile engine down --remove-orphans
```

`-v`는 붙이지 않습니다.

기존 DB 볼륨이 남아 있는지 확인합니다.

```bash
OLD_DB_VOLUME="$(cat "$BACKUP_DIR/old-db-volume.txt")"

sudo docker volume inspect "$OLD_DB_VOLUME" >/dev/null \
    && echo "기존 DB 볼륨 보존: 정상" \
    || echo "중단: 기존 DB 볼륨을 찾을 수 없음"
```

---

## 7. 새 버전 시작

DB만 먼저 시작합니다.

```bash
cd "$NEW_DIR"
sudo docker compose up -d db
sudo docker compose ps db
```

새 컨테이너가 기존 DB 볼륨을 사용하는지 확인합니다.

```bash
NEW_DB_CONTAINER="$(sudo docker compose ps -q db)"

NEW_DB_VOLUME="$(sudo docker inspect "$NEW_DB_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')"

printf '기존 DB 볼륨: %s\n새 DB 볼륨: %s\n' \
    "$OLD_DB_VOLUME" "$NEW_DB_VOLUME"
```

두 값이 완전히 같아야 합니다. 다르면 전체 서비스를 시작하지 말고:

```bash
sudo docker compose down
```

볼륨이 같을 때만 전체 서비스를 시작합니다.

```bash
sudo docker compose up -d
sleep 60

sudo docker compose ps
sudo docker compose logs --tail=250 api
curl -i "http://127.0.0.1:${CURRENT_WEB_PORT}/health"
```

정상 기준:

```text
HTTP/1.1 200 OK
version: 2.0.1
Migrations applied successfully.
Application startup complete.
```

처음 10초 정도 502가 나오는 것은 DB 마이그레이션 중일 수 있습니다.
60초 후에도 계속 502면 상세 가이드의 문제 해결 절을 확인합니다.

`v2.0.0`에서 생성된 `EXPORT_ROOT_PATH/{project_uuid}/...tif` 결과가
있다면 DB와 `EXPORT_ROOT_PATH`를 백업한 뒤 전용 도구를 먼저 dry-run으로
확인합니다. 현재 정사영상 처리 작업이 모두 끝난 상태에서 실행해야 합니다.

```bash
sudo ./scripts/migrate-orthomosaic-layout.sh
sudo ./scripts/migrate-orthomosaic-layout.sh --apply  # dry-run 매핑이 맞을 때만
```

파일만 수동으로 옮기면 DB 경로가 어긋납니다. 이 도구는 로컬 스토리지
배포 전용이며, MinIO 배포는 상세 가이드에 따라 별도 계획을 세웁니다.

---

## 8. 업데이트 결과 확인

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

브라우저에서 확인:

- 기존 계정 로그인
- 기존 프로젝트 목록
- 기존 프로젝트에서 EO 포인트 클릭 후 실제 비율 썸네일과 EO 값 표시
- 새 프로젝트 EO 가져오기 화면에서 EO 행 내용과 지도 위치 미리보기
- 테스트 처리 중 좌표계(원점) 변경 예약 및 EO 위치 갱신
- 썸네일과 정사영상
- 오프라인 지도 타일
- 새 테스트 프로젝트 생성

좌표계 변경은 처리 대기·진행 중이며 최종 결과 저장 전일 때만 가능합니다.
예약한 좌표계는 최종 COG 생성과 목표 좌표계 재투영 전에 적용됩니다.

---

## 9. 운영 자동 시작 설정

기능 검증이 끝난 후 새 버전 폴더에서 실행합니다.

```bash
cd "$NEW_DIR"
sudo bash scripts/secure-deployment.sh

readlink -f "$(dirname "$NEW_DIR")/aerial-survey-manager-current"

systemctl status aerial-survey --no-pager
systemctl status aerial-gpu-watchdog.timer --no-pager
```

symlink가 `aerial-survey-manager-v2.0.1`을 가리켜야 합니다.

외장 디스크를 사용하면 상세 가이드의 **14.1~14.2 외장 디스크 마운트
설정**도 적용합니다.

---

## 10. 최종 체크

- [ ] DB 사전검사 결과가 모두 0건
- [ ] `.env` 백업 완료
- [ ] DB dump 생성 및 읽기 확인
- [ ] 체크섬 `OK`
- [ ] 기존/새 DB 볼륨 이름 동일
- [ ] `/health` HTTP 200
- [ ] 버전 `2.0.1`
- [ ] 업데이트 전후 프로젝트 수 동일
- [ ] 기존 계정 로그인
- [ ] 정사영상과 타일 정상
- [ ] GPU 정상
- [ ] systemd와 watchdog 정상

하나라도 통과하지 못하면 기존 폴더와 볼륨을 삭제하지 말고
[상세 업데이트 가이드](UPGRADE_GUIDE.md)의 문제 해결 또는
롤백 절차를 확인합니다.
