# Metashape Processing Engine

항공측량 매니저 플랫폼의 고성능 정사영상 처리 엔진입니다. Agisoft Metashape Professional Python SDK를 기반으로 동작합니다.

## 🚀 Key Features
- **GPU Acceleration**: NVIDIA CUDA 가속을 통한 고속 매칭 및 포인트 클라우드 생성
- **Celery Integration**: 분산 처리 큐를 통한 비동기 작업 관리
- **License Persistence**: Docker 볼륨 및 고정 MAC 주소를 활용한 안정적인 라이선스 유지

## 🛠 Setup & Licensing

### 1. Environment Setup
`.env` 파일에 라이선스 키 및 하드웨어 설정을 입력합니다.

```env
METASHAPE_LICENSE_KEY=XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
```

### 2. License Activation
컨테이너 실행 후 최초 1회 활성화가 필요합니다.

```bash
# 개발 환경 (.py)
docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/activate.py
# 배포 환경 (.pyc)
docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/activate.pyc
```

### 3. Verification
활성화 상태를 확인하려면 다음 명령어를 실행합니다.
```bash
docker exec aerial-worker-engine python3 -c "import Metashape; print(Metashape.License().valid)"
```

## 📁 Structure
- `dags/`: Airflow 호환용 DAG 파일 (Celery Worker에서도 공유됨)
- `dags/metashape/`: 실제 Metashape 처리 로직 및 공통 유틸리티
- `Dockerfile`: 개발용 이미지 (CUDA 12.0 기반)
- `Dockerfile.prod`: 배포용 이미지 (.pyc 컴파일, 소스 코드 제거)

## 🔒 코드 보호 (배포 환경)

배포 패키지에서는 Python 소스코드가 바이트코드(.pyc)로 컴파일되어 보호됩니다:

```bash
# 배포 이미지 확인 (.py 파일 없어야 함)
docker run --rm aerial-prod-worker-engine:latest \
  find /app/engines -name "*.py" -type f
# 결과가 비어있어야 정상
```

> 배포 패키지 빌드: `./scripts/build-release.sh v1.0.x`

## ⚠️ Notes
- Metashape 2.2.0 버전을 사용하며, 라이선스 체크 시 `.valid` 속성을 사용합니다.
- 라이선스 파일은 `/var/tmp/agisoft/licensing` 경로에 저장되도록 설정되어 있습니다.
- 배포 환경에서는 `.pyc` 확장자로 스크립트를 실행해야 합니다.
