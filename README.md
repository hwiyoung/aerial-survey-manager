# Aerial Survey Manager

항공/드론 원본 이미지와 EO(외부표정요소)를 입력받아 정사영상을 생성하고 관리하는 플랫폼입니다.

현재 정식 릴리스: **v2.0.0**

## Features

- **프로젝트 관리**: 항공/드론 촬영 프로젝트 생성, 조회, 수정, 삭제
- **이미지 업로드**: 대용량 병렬 업로드 (로컬 디스크 또는 MinIO)
- **EO 데이터 파싱**: 다양한 포맷의 외부표정요소 파일 지원
- **정사영상 생성**: GPU 가속 처리 엔진
- **결과물 다운로드**: 대용량 정사영상 Resumable Download
- **대시보드**: 실시간 지도 시각화, COG 정사영상 오버레이
- **조직 공유 운영**: 하나의 조직 공동 계정으로 프로젝트·그룹·카메라 모델 공유

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   React + Vite + Tailwind                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
└───┬───────────────────────────┬───────────────┬─────────────┘
    │                           │               │
┌───▼───┐                 ┌─────▼─────┐   ┌─────▼──────┐
│FastAPI│──signed tile───▶│  TiTiler  │   │  Storage   │
│Backend│                 │(internal) │   │(Local/MinIO)│
└───┬───┘                 └───────────┘   └────────────┘
    │
┌───▼───┐    ┌───────────────┐ ┌───────────────┐ ┌──────────────────┐
│ Redis │───▶│ general worker│ │thumbnail worker│ │  worker-engine   │
│(Queue)│    │(파일/삭제)     │ │(미리보기)      │ │   (GPU, 1 job)  │
└───────┘    └───────────────┘ └───────────────┘ └──────────────────┘
    │
┌───▼───────┐
│PostgreSQL │
│ + PostGIS │
└───────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- NVIDIA GPU + Driver (처리 엔진용)

### Installation

```bash
# Clone & Setup
git clone https://github.com/hwiyoung/aerial-survey-manager.git
cd aerial-survey-manager
cp .env.example .env

# Start services
docker compose up -d

# Check status
docker compose ps
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Web UI | http://localhost:18110 | 메인 인터페이스 |
| API Docs | http://localhost:18101/docs | Swagger UI |
| MinIO Console | http://localhost:18103 | 스토리지 관리 (MinIO 모드) |

## Project Structure

```
aerial-survey-manager/
├── backend/              # FastAPI 백엔드
│   ├── app/              # 애플리케이션 코드
│   ├── alembic/          # DB 마이그레이션
│   └── scripts/          # DB 시드 스크립트
├── src/                  # React 프론트엔드
├── engines/              # 처리 엔진
├── scripts/              # 운영/배포 스크립트 (inject-cog.sh 등)
├── docs/                 # 문서
└── data/                 # 초기 시드 데이터
```

## Environment Variables

```bash
# Database
POSTGRES_PASSWORD=your-password

# JWT Authentication
# Generate with: openssl rand -hex 32
JWT_SECRET_KEY=replace-with-at-least-32-random-characters
ALLOW_WEAK_JWT_SECRET=false

# Initial shared operator account (ADMIN_* names are kept for compatibility)
ADMIN_EMAIL=admin
ADMIN_PASSWORD=choose-a-strong-password

# Storage Backend: "local" (단일 서버) 또는 "minio" (S3 호환)
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=./data                  # 배포 폴더 기준 기본값
# MINIO_ACCESS_KEY=minioadmin              # MinIO 모드
# MINIO_SECRET_KEY=your-password           # MinIO 모드

# Processing Data
PROCESSING_DATA_PATH=./data/projects
```

> 전체 환경변수는 `.env.example` 참조

## Development checks

```bash
./scripts/check-version.sh
npm run lint
npm run build

python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
pytest -q backend/tests
ruff check --no-cache backend/app backend/tests backend/scripts
```

버전 증가 기준과 릴리즈 절차는 [docs/VERSIONING.md](docs/VERSIONING.md)를
참조하세요.

## Documentation

| 문서 | 대상 | 설명 |
|------|------|------|
| [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) | 배포 담당자 | 설치, 환경 설정, 업그레이드 |
| [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | 운영자 | 상황별 대응 레시피 |
| [USER_MANUAL.md](docs/USER_MANUAL.md) | 사용자 | 화면별 사용법 |
| [TECHNICAL_MANUAL.md](docs/TECHNICAL_MANUAL.md) | 개발자 | 아키텍처, API, 내부 동작 |
| [CHANGELOG.md](docs/CHANGELOG.md) | PM/개발자 | 스프린트별 변경 기록 |
| [changes/README.md](docs/changes/README.md) | 개발자/PM | PR별 패치노트 조각 작성과 릴리즈 반영 규칙 |
| [PATCH_NOTES_TEMPLATE.md](docs/PATCH_NOTES_TEMPLATE.md) | 사용자/운영자 | 게임 업데이트 공지 형태의 릴리즈 노트 템플릿 |
| [ROADMAP.md](docs/ROADMAP.md) | PM | 현재 상태, 향후 계획, Known Issues |
| [engines/README.md](engines/README.md) | 개발자 | 처리 엔진 가이드 |

## Development

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
npm install
npm run dev
```

### Database Migration

```bash
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head
```

## License

MIT License
