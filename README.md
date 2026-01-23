# Aerial Survey Manager (정사영상 생성 플랫폼)

항공/드론 원본 이미지와 EO(외부표정요소)를 입력받아 정사영상을 생성하고 프로젝트를 관리하는 플랫폼입니다.

## ✨ Features

- **프로젝트 관리**: 항공/드론 촬영 프로젝트 생성, 조회, 수정, 삭제
- **이미지 업로드**: 대용량 이미지 Resumable Upload (tus 프로토콜)
- **EO 데이터 파싱**: 다양한 포맷의 외부표정요소 파일 지원
- **정사영상 생성**: OpenDroneMap + 외부 처리 엔진 API 듀얼 지원
- **결과물 다운로드**: 대용량 정사영상 Resumable Download
- **다중 사용자**: JWT 기반 인증, 조직별 권한 관리
- **고급 관리 기능**: 프로젝트 그룹핑(폴더), 처리 옵션 프리셋, 다중 선택 일괄 작업

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   React + Vite + Tailwind                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
└───┬───────────────┬───────────────┬───────────────┬─────────┘
    │               │               │               │
┌───▼───┐    ┌──────▼──────┐  ┌─────▼─────┐   ┌─────▼─────┐
│FastAPI│    │    tusd     │  │  TiTiler  │   │  MinIO    │
│Backend│    │ (Resumable) │  │(COG Tiles)│   │ (Storage) │
└───┬───┘    └─────────────┘  └───────────┘   └───────────┘
    │
┌───▼───┐    ┌─────────────┐    ┌─────────────┐
│ Redis │───▶│Celery Worker│───▶│ ODM/External│
│(Queue)│    │             │    │   Engine    │
└───────┘    └─────────────┘    └─────────────┘
    │
┌───▼───────┐
│PostgreSQL │
│ + PostGIS │
└───────────┘
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
| Frontend | [http://localhost:3000](http://localhost:3000) | Web UI (Dev Server) |
| Nginx (Proxy) | [http://localhost:8081](http://localhost:8081) | Production Proxy |
| API | [http://localhost:8001](http://localhost:8001) | Backend API |
| API Docs | [http://localhost:8001/docs](http://localhost:8001/docs) | Swagger UI |
| MinIO Console | [http://localhost:9003](http://localhost:9003) | Storage UI |
| TiTiler | [http://localhost:8081/titiler/](http://localhost:8081/titiler/) | COG Tile Server |
| Flower | [http://localhost:5555](http://localhost:5555) | Celery Monitoring |
| PostgreSQL | `localhost:5434` | Database |

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

### Project Groups
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/groups` | List groups |
| `POST` | `/api/v1/groups` | Create group |
| `PATCH` | `/api/v1/groups/{id}` | Update group |
| `DELETE` | `/api/v1/groups/{id}` | Delete group |

### Upload & Download
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/upload/projects/{id}/images/init` | Init upload |
| `POST` | `/api/v1/projects/{id}/eo` | Upload EO & Match data |
| `POST` | `/api/v1/upload/hooks` | tus webhook |
| `GET` | `/api/v1/download/projects/{id}/ortho` | Resumable download |
| `HEAD` | `/api/v1/download/projects/{id}/ortho` | Get file info |
| `GET` | `/api/v1/download/projects/{id}/cog-url` | COG streaming URL |

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

> 📌 상세 개발 계획은 [docs/ROADMAP.md](./docs/ROADMAP.md)를 참조하세요.

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

### ✅ Phase 4: Project Management & Dashboard (Completed)
- [x] EO data parsing and storage
- [x] Dashboard with layout toggle (Wide/Narrow/Auto)
- [x] Footprint map with project polygons
- [x] Processing start pulse animation & highlight
- [x] Compact mode hover action icons
- [x] Sidebar resizing performance (RAF based)
- [x] Upload Wizard improvements (Project name, image filter, ESC close)
- [x] Project deletion (single/multi)
- [x] Processing options presets (CRUD)
- [x] Processing sidebar back button
- [x] Click/Double-click behavior separation (Single: detail, Double: inspector)
- [x] Chart labels/legend improvements (pie chart overflow fix)
- [x] Map zoom persistence on project selection
- [x] Orthoimage (COG) overlay for completed projects

### 🔄 Phase 5: Advanced Features (In Progress)
- [x] **내보내기 기능 고도화 (2026-01-23)**:
  - 단일 프로젝트 TIF 직접 다운로드, ZIP 무결성 및 파일명 커스텀 로직 수정
- [x] **Project Grouping (Completed)**:
  - Folder-based project organization, drag-and-drop, create/edit/delete modals
- [x] **Dashboard Statistics API (Completed)**:
  - Monthly/Regional statistics endpoints (`/stats/monthly`, `/stats/regional`)
- [x] **TiTiler 타일 서버 통합 (2026-01-22)**:
  - COG 타일 스트리밍 (메모리 90%+ 절감), Nginx 프록시 설정
- [ ] **지도 시각화 최적화 (진행중)**:
  - 약 17,000개 권역 폴리곤 성능 개선 (Canvas 도입, PostGIS ST_Simplify 적용)
  - 권역 투명도 하향 조정을 통한 시인성 확보
- [ ] Multi-user permission management
- [ ] Organization storage quota

### ⚠️ Known Issues
- **지도 성능**: 권역 폴리곤 과다로 인한 브라우저 렌더링 지연 (Canvas 전환 및 데이터 단순화 진행 예정)
- **가시성**: 권역 레이어가 정사영상 영역을 가리는 문제 (투명도 추가 하향 조정 예정)
- **COG Loading**: MinIO presigned URL translation may require `MINIO_PUBLIC_ENDPOINT` configuration

## 🧪 Testing with Real Data

실제 데이터를 사용하여 플랫폼을 테스트하는 방법은 다음과 같습니다.

### 준비물
1. **드론 촬영 이미지**: `.jpg` 또는 `.tif` 파일 세트
2. **EO(외부표정요소) 파일**: 이미지 파일명과 매칭되는 좌표 정보가 포함된 `.csv` 또는 `.txt` 파일
    - 포맷 예시: `filename, x, y, z, omega, phi, kappa` (쉼표 구분)

### 테스트 단계

1. **사용자 등록 및 로그인**
   - [http://localhost:3000](http://localhost:3000) 또는 [http://localhost:8081](http://localhost:8081)에 접속하여 계정을 생성하고 로그인합니다.

2. **프로젝트 생성**
   - '새 프로젝트' 버튼을 클릭하여 이름, 지역, 회사 정보를 입력합니다.

3. **이미지 업로드 (Upload Wizard)**
   - 프로젝트 내 '업로드' 버튼을 클릭합니다.
   - 드론 촬영 이미지를 선택하거나 드래그하여 업로드합니다. (대용량인 경우 tus 프로토콜이 적용되어 중단 시 재개 가능합니다)

4. **EO 데이터 파일 업로드**
   - 이미지 업로드 후, 구성 파일(EO) 업로드 섹션에 `.csv` 파일을 선택합니다.
   - 컬럼 매핑 정보가 기본값과 다른 경우 설정 창에서 수정할 수 있습니다.

5. **정사영상 생성 시작**
   - '처리 시작' 버튼을 클릭합니다.
   - 엔진 선택 (ODM 또는 External API), 최종 결과물 해상도(GSD), 좌표계(CRS)를 설정합니다.

6. **모니터링 및 결과 확인**
   - 우측 사이드바 또는 프로젝트 리스트에서 실시간 진행 상태(%)를 확인합니다.
   - 처리가 완료되면 정사영상을 미리보기 하거나 다운로드합니다.

### 💡 팁
- 대량의 이미지(100장 이상) 테스트 시에는 ODM 엔진 사용을 권장하며, Docker 리소스를 충분히 할당해 주세요.
- 외부 API 엔진을 테스트하려면 `EXTERNAL_ENGINE_URL` 및 API Key가 필요합니다.

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
