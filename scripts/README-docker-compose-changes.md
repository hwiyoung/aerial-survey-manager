# docker-compose.prod.yml 변경 사항

## Metashape 라이센스 비활성화를 위한 설정 추가

`worker-metashape` 서비스에 다음 설정을 추가해야 합니다:

```yaml
worker-metashape:
    build:
      context: .
      dockerfile: engines/metashape/Dockerfile.prod
    working_dir: /app
    # 기존 command 유지
    command: celery -A app.workers.tasks worker -Q metashape --loglevel=info -n worker-metashape@%h
    restart: always

    # === 추가해야 할 설정 ===
    # 종료 신호 설정 (라이센스 비활성화를 위한 graceful shutdown)
    stop_signal: SIGTERM
    stop_grace_period: 60s  # 라이센스 비활성화 시간 확보

    # GPU 설정 (기존 유지)
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    # ... 나머지 설정 유지 ...
```

## 변경 이유

1. **stop_signal: SIGTERM** - Docker가 컨테이너 종료 시 SIGTERM 신호를 보내도록 명시
2. **stop_grace_period: 60s** - 라이센스 비활성화에 충분한 시간(60초) 제공
3. **entrypoint.sh** - SIGTERM 수신 시 `deactivate.py`를 실행하여 라이센스 반환

## 작동 방식

1. `docker compose stop worker-metashape` 또는 `docker compose down` 실행
2. Docker가 SIGTERM 신호를 컨테이너에 전송
3. `entrypoint.sh`의 trap 핸들러가 신호를 수신
4. `deactivate.py` 실행하여 Metashape 라이센스 비활성화
5. 컨테이너 정상 종료

## 수동 종료 스크립트

`scripts/shutdown-metashape.sh` 스크립트를 사용하여 안전하게 종료할 수 있습니다:

```bash
./scripts/shutdown-metashape.sh [docker-compose 파일 경로]
```
