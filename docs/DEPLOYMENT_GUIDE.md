# 배포 가이드

배포 패키지 설치 및 업그레이드 절차입니다.

---

## 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| CPU | 8코어 | 16코어 |
| RAM | 32GB | 64GB |
| GPU | NVIDIA CUDA | RTX 3080+ |
| 저장소 | 1TB SSD | 4TB+ NVMe |
| OS | Ubuntu 20.04/22.04 LTS | |
| Docker | 24.0+ | |
| NVIDIA Driver | 525+ | |
| NVIDIA Container Toolkit | 최신 | |

> Docker 설치: https://docs.docker.com/engine/install/ubuntu/
> NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

---

## 신규 설치

### 1. 패키지 설치
```bash
tar -xzf aerial-survey-manager.tar.gz
cd aerial-survey-manager
./scripts/install.sh
```

### 2. 필수 환경변수 (.env)

| 변수 | 설명 | 예시 |
|------|------|------|
| `POSTGRES_PASSWORD` | DB 비밀번호 | `openssl rand -hex 16` |
| `JWT_SECRET_KEY` | JWT 서명 키 (32자+) | `openssl rand -hex 32` |
| `STORAGE_BACKEND` | `local` 또는 `minio` | `local` |
| `LOCAL_STORAGE_PATH` | 파일 저장 경로 (로컬 모드) | `/data/aerial-survey/storage` |
| `PROCESSING_DATA_PATH` | 처리 데이터 경로 | `/data/aerial-survey/processing` |
| `METASHAPE_LICENSE_KEY` | Metashape 라이선스 키 | |

**오프라인 타일맵 (선택):**

| 변수 | 설명 |
|------|------|
| `VITE_MAP_OFFLINE` | `true` |
| `VITE_TILE_URL` | `/tiles/{z}/{x}/{y}` |
| `TILES_PATH` | 호스트 타일 디렉토리 경로 |

> 전체 변수 목록: `.env.example` 참조

### 3. 서비스 시작 및 확인
```bash
docker compose up -d
docker compose ps              # 모든 서비스 Up 확인
curl http://localhost:8081/health   # API 응답 확인
```

### 4. 접속
- 웹 UI: `http://서버IP:8081`
- 기본 계정: `admin` / `siqms`

---

## 버전 업그레이드

### 간편 업그레이드 (.env에 `COMPOSE_PROJECT_NAME=aerial-survey-manager`가 있는 경우)

```bash
# 1. 백업
cp .env ~/env_backup

# 2. 서비스 중지 (볼륨 유지 — -v 금지!)
docker compose down

# 3. 새 패키지 설치
cd ~
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0
cp ~/env_backup .env
./load-images.sh

# 4. 시작 (DB 마이그레이션 자동 실행)
docker compose up -d

# 5. 확인
docker compose ps
docker compose exec db psql -U postgres -d aerial_survey -c "SELECT count(*) FROM projects"
```

> `install.sh`를 실행하지 마세요. 비밀번호가 재생성되어 기존 데이터에 접근할 수 없게 됩니다.

### 표준 업그레이드 (`COMPOSE_PROJECT_NAME`이 없는 최초 업그레이드)

```bash
# 1. 기존 환경에서 백업
docker compose exec db pg_dump -U postgres aerial_survey > ~/backup.sql
cp .env ~/env_backup

# 2. 기존 중지 + 볼륨 삭제
docker compose down -v

# 3. 새 패키지 설치
cd ~
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0
cp ~/env_backup .env
echo 'COMPOSE_PROJECT_NAME=aerial-survey-manager' >> .env

# 4. DB 복원
docker compose up -d db
sleep 5
docker compose exec db dropdb -U postgres aerial_survey
docker compose exec db createdb -U postgres aerial_survey
docker compose exec -T db psql -U postgres aerial_survey < ~/backup.sql

# 5. 전체 시작
docker compose up -d
```

### 업그레이드 확인 체크리스트

- [ ] `docker compose ps` — 모든 서비스 Up
- [ ] 기존 프로젝트 목록이 보이는가
- [ ] 기존 정사영상이 지도에 표시되는가
- [ ] 새 프로젝트 생성이 가능한가

---

## 보안 설정 (선택)

### CORS 제한
```nginx
# nginx.conf — 프로덕션에서는 특정 도메인만 허용
add_header 'Access-Control-Allow-Origin' 'https://app.example.com' always;
```

### 관리 포트 localhost 제한
```yaml
# docker-compose.yml
ports:
  - "127.0.0.1:5555:5555"  # Flower
```

### SSL/HTTPS
```bash
# Let's Encrypt
sudo certbot certonly --standalone -d app.example.com
cp /etc/letsencrypt/live/app.example.com/fullchain.pem ./ssl/cert.pem
cp /etc/letsencrypt/live/app.example.com/privkey.pem ./ssl/key.pem
```

### 방화벽
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5434/tcp    # DB
sudo ufw deny 6380/tcp    # Redis
sudo ufw enable
```

---

## 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| GPU 미인식 | NVIDIA 드라이버/Container Toolkit | `nvidia-smi` 확인, toolkit 재설치 |
| 처리 실패 | 라이선스/이미지 문제 | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) 참조 |
| MinIO 507 | 디스크 부족 | `df -h`, 임시 파일 정리 |
| 타일맵 안 보임 | bind mount 끊김 | `docker compose restart nginx` |
| DB 연결 실패 | 컨테이너 미시작 | `docker compose logs db` |

> 상세 운영 문제는 [ADMIN_GUIDE.md](ADMIN_GUIDE.md) 참조

---

## 백업

```bash
# DB 백업
docker compose exec db pg_dump -U postgres aerial_survey > backup_$(date +%Y%m%d).sql

# DB 복원
docker compose exec -T db psql -U postgres aerial_survey < backup.sql
```
