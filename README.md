# Aerial Survey Manager

항공/드론 원본 이미지와 EO(외부표정요소)를 입력받아 정사영상을 생성하고 관리하는 플랫폼입니다.

## Features

- **프로젝트 관리**: 항공/드론 촬영 프로젝트 생성, 조회, 수정, 삭제
- **이미지 업로드**: 대용량 병렬 업로드 (로컬 디스크 또는 MinIO)
- **EO 데이터 파싱**: 다양한 포맷의 외부표정요소 파일 지원
- **정사영상 생성**: Metashape GPU 가속 처리 엔진
- **결과물 다운로드**: 대용량 정사영상 Resumable Download
- **대시보드**: 실시간 지도 시각화, COG 정사영상 오버레이

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
│FastAPI│                 │  TiTiler  │   │  Storage   │
│Backend│                 │(COG Tiles)│   │(Local/MinIO)│
└───┬───┘                 └───────────┘   └────────────┘
    │
┌───▼───┐    ┌───────────────┐    ┌──────────────────┐
│ Redis │───▶│ celery-worker │    │  worker-engine   │
│(Queue)│    │(파일관리/썸네일)│    │ (Metashape GPU)  │
└───────┘    └───────────────┘    └──────────────────┘
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
| Web UI | http://localhost:8081 | 메인 인터페이스 |
| API Docs | http://localhost:8081/api/docs | Swagger UI |
| MinIO Console | http://localhost:9003 | 스토리지 관리 (MinIO 모드) |

## Project Structure

```
aerial-survey-manager/
├── backend/              # FastAPI 백엔드
│   ├── app/              # 애플리케이션 코드
│   ├── alembic/          # DB 마이그레이션
│   └── scripts/          # DB 시드 스크립트
├── src/                  # React 프론트엔드
├── engines/              # 처리 엔진 (Metashape)
├── scripts/              # 운영/배포 스크립트 (inject-cog.sh 등)
├── docs/                 # 문서
└── data/                 # 초기 시드 데이터
```

## Environment Variables

```bash
# Database
POSTGRES_PASSWORD=your-password

# JWT Authentication
JWT_SECRET_KEY=your-secret-key

# Storage Backend: "local" (단일 서버) 또는 "minio" (S3 호환)
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=/path/to/storage        # 로컬 모드
# MINIO_ACCESS_KEY=minioadmin              # MinIO 모드
# MINIO_SECRET_KEY=your-password           # MinIO 모드

# Processing Data (대용량 드라이브 권장)
PROCESSING_DATA_PATH=/path/to/processing
```

> 전체 환경변수는 `.env.example` 참조

## Documentation

| 문서 | 설명 |
|------|------|
| [DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md) | 문서 역할/갱신 규칙(우선순위) |
| [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) | 배포/초기 구성/버전 업그레이드 |
| [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | 운영·운영자용 유지보수 가이드 |
| [ROADMAP.md](docs/ROADMAP.md) | 개발 로드맵 및 변경 이력 |
| [SPRINT_COMPLETION.md](docs/SPRINT_COMPLETION.md) | 1~4차 스프린트 핵심 목적 달성 상태 |
| [engines/README.md](engines/README.md) | 처리 엔진 가이드 |
| [OPERATIONS_MONITORING.md](docs/OPERATIONS_MONITORING.md) | 처리 큐/로그/임계치 모니터링 |

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
