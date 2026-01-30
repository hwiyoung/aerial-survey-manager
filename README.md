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
- **처리 진행 상태 복구**: 처리 화면 재진입 시 마지막 단계 메시지/진행률 즉시 동기화

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
┌───▼───┐    ┌─────────────┐    ┌──────────────────┐
│ Redis │───▶│Celery Worker│───▶│ ODM / Metashape / │
│(Queue)│    │ (Multi-Q)   │    │ External Engine  │
└───────┘    └─────────────┘    └──────────────────┘
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

### Data directory (processing cache)

기본 데이터 저장 경로는 **호스트의 `./data/processing` → 컨테이너의 `/data/processing`** 입니다.  
다른 위치로 변경하려면 아래처럼 환경변수를 지정한 뒤 `docker-compose`를 실행하세요.

```bash
export PROCESSING_DATA_PATH=/your/fast/disk/aerial-data/processing
docker-compose up -d
```

> ODM 엔진은 `HOST_DATA_PATH`를 사용해 호스트 경로를 참조합니다.  
> `docker-compose.yml`에서 `PROCESSING_DATA_PATH`를 설정하면 자동으로 반영됩니다.

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
│   │   ├── api/v1/               # API endpoints
│   │   ├── services/
│   │   │   └── processing_router.py  # Engine router
│   │   └── workers/              # Celery tasks
│   └── Dockerfile
├── engines/                      # Processing Engines (Monorepo)
│   ├── odm/                      # ODM settings & scripts
│   └── external-engine/          # External API engine source
├── docker-compose.yml            # All services
├── nginx.conf                    # Reverse proxy (TB-scale optimized)
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

### ✅ Phase 5: Advanced Features (Completed)
- [x] **내보내기 기능 고도화**: 단일 TIF 직접 다운로드 및 ZIP 무결성 보완
- [x] **Project Grouping**: 폴더 기반 관리, 드래그 앤 드롭 지원
- [x] **Dashboard Statistics API**: 월별/지역별 통계 연동
- [x] **TiTiler 타일 서버 통합**: COG 타일 스트리밍 (메모리 90%+ 절감)
- [x] **지도 시각화 최적화**: 1.7만개 권역 데이터 Canvas 렌더링 및 PostGIS 단순화 (ST_Simplify) 적용
- [x] **UI/UX 개선**: 하드웨어 가속(will-change) 및 60fps 부드러운 애니메이션 적용

### ✅ Phase 6: System Hardening & Integration (Completed)
- [x] **TB급 업로드 안정화**: 20MB Chunk 및 동시성 제어 적용 (upload.js)
- [x] **인프라 튜닝**: Nginx `proxy_request_buffering off`를 통한 스트리밍 안정화
- [x] **Monorepo 구조 전환**: `/engines` 디렉토리를 통한 처리 엔진 통합 관리
- [x] **Metashape 엔진 통합**: 고성능 GPU 워커 구축 및 파이프라인 연동 완료 (2.2.0 호환성 패치 적용)
- [x] **라이선스 안정화**: Always Active + 볼륨 영속화(/var/tmp/agisoft/licensing) 전략으로 중단 없는 처리 보장
- [x] **EO 데이터 파싱 최적화**: 500 에러 해결 및 대용량 매칭 로직 안정화
- [x] **External API 드라이버**: 상세 명세 기반 드라이버 고도화 및 Webhook 연동 완료

### ✅ Phase 7: UX Refinement & Stabilization (Completed)
- [x] **대시보드 메타데이터 & 통계**: 단일 클릭 상세 표시 및 데이터 소스 정규화 (2026-01-29)
- [x] **썸네일 시스템**: 업로드 즉시 생성 및 백필 자동화 (2026-01-29)
- [x] **지도 상호작용 개선**: 중첩 프로젝트 선택 팝업 및 레이어 우선순위 조정 (2026-01-29)
- [x] **메타데이터 표시 확장**: Sidebar compact 모드에 이미지 수 표시 추가 (2026-01-29)
- [x] **대시보드 복귀 UX**: 로고 클릭 시 페이지 리로드 없이 상태 기반 네비게이션 (2026-01-29)
- [x] **썸네일 가시성**: 처리 옵션 팝업 내 이미지 로드 실패 시 폴백 처리 (2026-01-29)
- [x] **처리 완료 상태 동기화**: '나중에 확인(Stay)' 동작 시 UI 상태 즉시 갱신 (2026-01-29)
- [x] **이미지 중복 방지**: 같은 파일명 업로드 시 Image 레코드 중복 생성 방지 (2026-01-29)
- [x] **브라우저 히스토리**: popstate 이벤트 리스너로 뒤로가기 버튼 지원 (2026-01-29)

## ⚠️ Known Issues (2026-01-30)

### 지도 및 상호작용
- **권역 툴팁 우선순위**: 권역(Region)과 프로젝트(Footprint) 중첩 시 바운딩박스 호버에도 권역 툴팁이 표시되는 경우 있음 (CSS + 이벤트 제어로 개선 중)

### 시스템
- **COG Loading**: MinIO presigned URL 외부 접근 시 `MINIO_PUBLIC_ENDPOINT` 설정 필요
- **처리 중단 후 재시작 오류**: 동일 프로젝트에서 처리 중단 후 곧바로 재시작할 때 Metashape 단계에서 오류(예: `Empty DEM`)가 발생할 수 있음. EO 파일명 매칭/metadata.txt 상태를 확인하고, 필요 시 EO 재업로드 또는 프로젝트 재생성을 권장.

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
   - **이미지 파일명과 EO 파일명은 반드시 일치해야 합니다.** (매칭 0건인 경우 업로드가 실패하도록 방지됨)

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
