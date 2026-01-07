# Aerial Survey Manager (정사영상 생성 플랫폼)

항공/드론 원본 이미지와 EO(외부표정요소)를 입력받아 정사영상을 생성하고 프로젝트를 관리하는 플랫폼입니다.

## ✨ Features

- **프로젝트 관리**: 항공/드론 촬영 프로젝트 생성, 조회, 수정, 삭제
- **이미지 업로드**: 대용량 이미지 Resumable Upload (tus 프로토콜)
- **EO 데이터 파싱**: 다양한 포맷의 외부표정요소 파일 지원
- **정사영상 생성**: OpenDroneMap + 외부 처리 엔진 API 듀얼 지원
- **결과물 다운로드**: 대용량 정사영상 Resumable Download
- **다중 사용자**: JWT 기반 인증, 조직별 권한 관리

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   React + Vite + Tailwind                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
└──────┬───────────────────┬───────────────────┬──────────────┘
       │                   │                   │
┌──────▼──────┐    ┌───────▼───────┐    ┌──────▼──────┐
│  FastAPI    │    │     tusd      │    │   MinIO     │
│  Backend    │    │  (Resumable   │    │  (Storage)  │
│             │    │   Upload)     │    │             │
└──────┬──────┘    └───────────────┘    └─────────────┘
       │
┌──────▼──────┐    ┌───────────────┐    ┌─────────────┐
│   Redis     │───▶│ Celery Worker │───▶│ ODM/External│
│  (Queue)    │    │               │    │   Engine    │
└─────────────┘    └───────────────┘    └─────────────┘
       │
┌──────▼──────┐
│ PostgreSQL  │
│  + PostGIS  │
└─────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Git

### Installation

```bash
# Clone repository
git clone <repository-url>
cd aerial-survey-manager

# Setup environment
cp .env.example .env
# Edit .env file with your configurations

# Start all services
docker-compose up -d

# Check services
docker-compose ps
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | Web UI |
| API | http://localhost:8000 | Backend API |
| API Docs | http://localhost:8000/docs | Swagger UI |
| MinIO Console | http://localhost:9001 | Storage UI |
| Flower | http://localhost:5555 | Celery Monitoring |

## 📁 Project Structure

```
aerial-survey-manager/
├── src/                          # Frontend (React)
│   ├── App.jsx                   # Main application
│   ├── api/
│   │   └── client.js             # API client
│   └── services/
│       ├── upload.js             # Resumable Upload (tus)
│       └── download.js           # Resumable Download
├── backend/                      # Backend (FastAPI)
│   ├── app/
│   │   ├── main.py               # App entry point
│   │   ├── config.py             # Settings
│   │   ├── database.py           # DB connection
│   │   ├── api/v1/               # API endpoints
│   │   │   ├── auth.py           # Authentication
│   │   │   ├── projects.py       # Project CRUD
│   │   │   ├── upload.py         # Upload + Webhook
│   │   │   ├── download.py       # Resumable download
│   │   │   └── processing.py     # Processing jobs
│   │   ├── auth/                 # JWT utilities
│   │   ├── models/               # SQLAlchemy models
│   │   ├── schemas/              # Pydantic schemas
│   │   ├── services/             # Business logic
│   │   │   ├── storage.py        # MinIO service
│   │   │   └── processing_router.py  # Engine router
│   │   └── workers/              # Celery tasks
│   ├── alembic/                  # DB migrations
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml            # All services
├── nginx.conf                    # Reverse proxy
├── init.sql                      # DB initialization
└── .env.example                  # Environment template
```

## 🔧 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/register` | Register new user |
| `POST` | `/api/v1/auth/login` | Login (returns JWT) |
| `POST` | `/api/v1/auth/refresh` | Refresh token |
| `GET` | `/api/v1/auth/me` | Get current user |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/projects` | List projects |
| `POST` | `/api/v1/projects` | Create project |
| `GET` | `/api/v1/projects/{id}` | Get project |
| `PATCH` | `/api/v1/projects/{id}` | Update project |
| `DELETE` | `/api/v1/projects/{id}` | Delete project |

### Upload & Download
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/upload/projects/{id}/images/init` | Init upload |
| `POST` | `/api/v1/upload/hooks` | tus webhook |
| `GET` | `/api/v1/download/projects/{id}/ortho` | Resumable download |
| `HEAD` | `/api/v1/download/projects/{id}/ortho` | Get file info |

### Processing
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/processing/projects/{id}/start` | Start processing |
| `GET` | `/api/v1/processing/projects/{id}/status` | Get status |
| `POST` | `/api/v1/processing/projects/{id}/cancel` | Cancel job |
| `WS` | `/ws/projects/{id}/status` | Real-time updates |

## 🔐 Environment Variables

```bash
# Database
POSTGRES_PASSWORD=your-secure-password

# JWT Authentication  
JWT_SECRET_KEY=your-super-secret-jwt-key

# MinIO Storage
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=your-secure-minio-password

# External Processing Engine (Optional)
EXTERNAL_ENGINE_URL=https://external-engine.example.com
EXTERNAL_ENGINE_API_KEY=your-api-key
```

## 📋 Implementation Roadmap

### ✅ Phase 1: Foundation (Completed)
- [x] Backend project structure (FastAPI)
- [x] Database schema (PostgreSQL + PostGIS)
- [x] JWT authentication system
- [x] User & Organization models
- [x] Project CRUD API
- [x] MinIO storage integration
- [x] Docker Compose configuration

### ✅ Phase 2: Large File Transfer (Completed)
- [x] tusd server integration (Resumable Upload)
- [x] Range-based Resumable Download
- [x] SHA256 checksum verification
- [x] Frontend upload/download services

### ✅ Phase 3: Processing Engine (Completed)
- [x] OpenDroneMap integration
- [x] External Engine API support
- [x] Processing router (dual engine)
- [x] Celery async workers (multi-queue)
- [x] WebSocket real-time updates

### 🔲 Phase 4: Project Management (TODO)
- [ ] EO data parsing and storage
- [ ] Camera model management
- [ ] Quality Control (QC) workflow
- [ ] Frontend-Backend integration

### 🔲 Phase 5: Advanced Features (TODO)
- [ ] Multi-user permission management
- [ ] Organization storage quota
- [ ] Map visualization (Leaflet/MapLibre)
- [ ] Dashboard statistics
- [ ] Batch export functionality

## 🛠️ Development

### Local Development (Backend)

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --reload --port 8000
```

### Local Development (Frontend)

```bash
# Install dependencies
npm install

# Run dev server
npm run dev
```

### Database Migration

```bash
# Create migration
docker-compose exec api alembic revision --autogenerate -m "description"

# Apply migration
docker-compose exec api alembic upgrade head
```

## 📄 License

MIT License

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
