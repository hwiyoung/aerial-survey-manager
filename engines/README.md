# Engines Directory (Monorepo)

이 디렉토리는 Aerial Survey Manager 플랫폼에 통합된 모든 처리 엔진을 관리합니다.

## 디렉토리 구조

- `/engines/odm`: OpenDroneMap 관련 설정 및 커스텀 스크립트가 위치합니다. (현재는 Docker 기반으로 동작하며, 관련 설정 보관용으로 사용됩니다.)
- `/engines/external-engine`: 사용자가 가져온 외부 처리 엔진 코드(FastAPI, Flask 등)가 위치하는 곳입니다.

## 통합 및 배포 가이드

1. **코드 배치**: 외부 엔진의 소스 코드를 `/engines/external-engine` 디렉토리에 복사하십시오.
2. **Docker 통합**: `docker-compose.yml`에서 해당 디렉토리를 빌드 컨텍스트로 사용하거나 볼륨으로 마운트하여 하나의 환경으로 배포할 수 있습니다.
3. **통신**: 플랫폼 백엔드와 외부 엔진은 Docker 내부 네트워크를 통해 통신하는 것이 가장 효율적입니다. (예: `http://external-engine:5000`)

---
*Created on 2026-01-27*
