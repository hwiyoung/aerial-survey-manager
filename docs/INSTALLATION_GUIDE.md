# Aerial Survey Manager 설치 방법

이 문서는 배포 패키지를 새 PC에 설치하거나 새 버전으로 업그레이드할 때의 표준 절차입니다.

## 1. 압축 해제

```bash
tar -xzf aerial-survey-manager-<version>.tar.gz
cd aerial-survey-manager-<version>
```

## 2. Docker 이미지 로드

```bash
./load-images.sh
```

## 3. 설치 전 점검

```bash
docker compose config
./scripts/check-gpu-stack.sh
```

`check-gpu-stack.sh`에서 다음을 확인합니다.

- 현재 커널: `uname -r`
- 호스트 GPU: `nvidia-smi`
- Docker NVIDIA runtime: `docker info | grep -i nvidia`
- 컨테이너 GPU 전달: `docker run --rm --gpus all ... nvidia-smi`
- 현재 커널과 일치하는 `linux-modules-nvidia-*` 패키지
- Secure Boot 상태
- `aerial-survey.service`, `aerial-gpu-watchdog.timer` 상태

커널은 올라갔지만 `linux-modules-nvidia-*$(uname -r)` 패키지가 없으면 `nvidia-smi`와 `worker-engine`이 실패할 수 있습니다.
설치 스크립트가 NVIDIA runtime 재등록을 제안하는 경우 Docker가 재시작되어
실행 중인 다른 컨테이너도 잠시 중단된다는 안내를 확인한 뒤 승인합니다.

## 4. 설치 실행

```bash
./scripts/install.sh
```

설치 스크립트는 `.env`를 생성하고 서비스를 시작합니다. 신규 설치에서는 아래 구조를 권장합니다.

신규 DB에서는 설치 중 최초 관리자 아이디와 비밀번호를 입력합니다.
비밀번호 입력 없이 Enter를 누르면 강한 임의 비밀번호를 자동 생성해 한 번
출력합니다. 기존 사용자가 있는 업그레이드 설치에서는 기존 로그인 정보를
변경하지 않습니다.

```text
AERIAL_DATA_ROOT=/data/aerial-survey
LOCAL_STORAGE_PATH=/data/aerial-survey
PROCESSING_DATA_PATH=/data/aerial-survey/projects
EXPORT_ROOT_PATH=/data/aerial-survey/orthomosaic
```

컨테이너에는 다음처럼 마운트됩니다.

```text
LOCAL_STORAGE_PATH/projects  -> /data/storage/projects
EXPORT_ROOT_PATH             -> /data/storage/orthomosaic
EXPORT_ROOT_PATH             -> /data/exports
```

`LOCAL_STORAGE_PATH/orthomosaic` 더미 디렉토리는 만들 필요가 없습니다.

## 5. systemd 보안 설정

설치가 끝나면 반드시 실행합니다.

```bash
sudo bash scripts/secure-deployment.sh
```

이 스크립트는 현재 버전 폴더를 고정 symlink로 연결합니다.

```text
/home/dell/aerial-survey-manager-current -> /home/dell/aerial-survey-manager-<version>
```

`aerial-survey.service`와 `aerial-gpu-watchdog.service`는 버전 폴더가 아니라 이 고정 symlink를 봅니다. 새 버전으로 업그레이드한 뒤에도 새 폴더에서 `sudo bash scripts/secure-deployment.sh`를 다시 실행해야 symlink와 systemd 유닛이 최신 버전을 가리킵니다.

확인:

```bash
systemctl cat aerial-survey.service | grep -E 'WorkingDirectory|EnvironmentFile|ExecStart'
```

코드 정비용 체크아웃처럼 `.env`를 현재 사용자 권한으로 유지해야 할 때는 자동 시작 및 GPU watchdog만 등록할 수 있습니다.

```bash
sudo bash scripts/secure-deployment.sh --systemd-only
```

## 6. 시작 모델

`aerial-survey.service`는 핵심 서비스를 먼저 시작합니다.

```text
db, redis, api, frontend, nginx, celery-beat, celery-worker,
celery-worker-thumbnail, flower, titiler
```

`worker-engine`은 GPU 런타임이 늦게 올라와도 전체 서비스가 failed가 되지 않도록 best-effort로 시작합니다. 이 경우 `aerial-survey.service`는 success 상태일 수 있고, `aerial-gpu-watchdog.timer`가 나중에 `worker-engine` 복구를 재시도합니다.

## 7. 운영 명령

보안 설정 후 `.env`는 root-only 권한(`600`)이 됩니다. 일반 사용자가 직접 `docker compose`를 실행하면 permission denied가 날 수 있습니다. 일반 운영자는 아래 명령을 사용하세요.

```bash
aerial-status
aerial-restart
aerial-logs
```

## 8. 설치 후 확인

```bash
systemctl status aerial-survey --no-pager
systemctl status aerial-gpu-watchdog.timer --no-pager
docker compose ps
nvidia-smi
docker compose exec worker-engine nvidia-smi
curl http://127.0.0.1:18100/health
```

프로덕션 Docker 네트워크는 기본적으로 `10.253.0.0/24`를 사용해 개발
스택의 `172.23.0.0/16`과 충돌하지 않습니다. 설치 환경에서 이미 사용 중인
대역이면 `.env`의 `AERIAL_NETWORK_SUBNET`을 다른 사설 대역으로 변경합니다.

카메라 IO 목록은 패키지의 상대경로 `./data/io.csv`에서 API 시작 시 DB로
동기화됩니다. 설치 대상 PC에서 별도 절대경로를 지정할 필요가 없습니다.

```bash
scripts/build-release.sh vYYYYMMDD
```

릴리스를 만드는 저장소에도 원본 IO 파일을 `./data/io.csv`로 준비합니다.
빌드 스크립트가 이를 배포패키지의 같은 상대경로에 포함합니다.

`io.csv`의 pixel size는 µm 단위로 유지되며, 처리 엔진 실행 직전에 mm로 변환됩니다.

기존 정사영상 경로 보정이 필요하면 먼저 dry-run을 확인한 뒤 적용합니다.

```bash
./scripts/sync-ortho-result-paths.sh
./scripts/sync-ortho-result-paths.sh --apply
```

## 9. GPU stack hold 선택 기능

커널 업데이트와 NVIDIA 커널 모듈 패키지 mismatch를 피해야 하는 운영 환경에서는 운영자가 명시적으로 hold를 선택할 수 있습니다.

```bash
./scripts/pin-gpu-stack.sh --list
sudo ./scripts/pin-gpu-stack.sh --hold
```

해제:

```bash
sudo ./scripts/pin-gpu-stack.sh --unhold
```

주의: hold는 커널과 드라이버 보안 업데이트 적용을 지연시킬 수 있습니다. 기본 설치는 자동 hold를 수행하지 않습니다. 유지보수 창을 정해 unhold, 업데이트, 재부팅, 재진단을 수행하세요.
