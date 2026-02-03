# Aerial Survey Manager (정사영상 생성 플랫폼)

항공/드론 원본 이미지와 EO(외부표정요소)를 입력받아 정사영상을 생성하고 프로젝트를 관리하는 플랫폼입니다.

## ✨ Features

- **프로젝트 관리**: 항공/드론 촬영 프로젝트 생성, 조회, 수정, 삭제
- **이미지 업로드**: S3 Multipart Upload (대용량 병렬 업로드, 멀티 프로젝트 동시 지원)
- **EO 데이터 파싱**: 다양한 포맷의 외부표정요소 파일 지원
- **정사영상 생성**: 고품질 정사영상 처리 엔진
- **결과물 다운로드**: 대용량 정사영상 Resumable Download
- **다중 사용자**: JWT 기반 인증, 조직별 권한 관리
- **고급 관리 기능**: 프로젝트 그룹핑(폴더), 처리 옵션 프리셋, 다중 선택 일괄 작업
- **대시보드**: 실시간 지도 시각화, 월별/권역별 통계, COG 정사영상 오버레이

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   React + Vite + Tailwind                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
│              (S3 Multipart Proxy: /storage/)                 │
└───┬───────────────────────────┬───────────────┬─────────────┘
    │                           │               │
┌───▼───┐                 ┌─────▼─────┐   ┌─────▼─────┐
│FastAPI│                 │  TiTiler  │   │  MinIO    │
│Backend│                 │(COG Tiles)│   │ (Storage) │
└───┬───┘                 └───────────┘   └───────────┘
    │
┌───▼───┐    ┌─────────────┐    ┌──────────────────┐
│ Redis │───▶│Celery Worker│───▶│   Processing    │
│(Queue)│    │   (GPU)     │    │   (GPU Engine)   │
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
git clone https://github.com/hwiyoung/aerial-survey-manager.git
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
MINIO_PUBLIC_ENDPOINT=192.168.10.203:9002  # 브라우저에서 접근 가능한 주소

# Storage Paths (대용량 드라이브에 설정 권장)
PROCESSING_DATA_PATH=/path/to/large/disk/processing  # 처리 데이터 경로
MINIO_DATA_PATH=/path/to/large/disk/minio            # MinIO 저장소 경로

# External Processing Engine (Optional)
EXTERNAL_ENGINE_URL=https://external-engine.example.com
EXTERNAL_ENGINE_API_KEY=your-api-key

# Offline Map Tiles (Optional)
VITE_MAP_OFFLINE=false               # true로 설정 시 로컬 타일 사용
VITE_TILE_URL=/tiles/{z}/{x}/{y}.png # 오프라인 타일 URL 패턴
TILES_PATH=/data/tiles               # 호스트의 타일 디렉토리 경로
```

> ⚠️ **중요**: `MINIO_DATA_PATH`는 반드시 **충분한 여유 공간이 있는 디스크**에 설정하세요.
> MinIO는 디스크 여유 공간이 임계치(기본 10%) 이하로 떨어지면 **HTTP 507 (Storage Full)** 오류를 반환하며, 이 경우 모든 업로드가 실패합니다.
> 상세 내용은 [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md#minio-저장소-관리)를 참조하세요.

## 📋 Implementation Status

> 📌 상세 변경 이력은 [docs/ROADMAP.md](./docs/ROADMAP.md)를 참조하세요.

| Phase | 상태 | 주요 내용 |
|-------|------|----------|
| Phase 1: Foundation | ✅ 완료 | FastAPI 백엔드, PostgreSQL + PostGIS, JWT 인증 |
| Phase 2: File Transfer | ✅ 완료 | S3 Multipart Upload, Resumable Download |
| Phase 3: Processing | ✅ 완료 | Metashape GPU 엔진, Celery 비동기 워커 |
| Phase 4: Dashboard | ✅ 완료 | 지도 시각화, 프로젝트 관리, COG 오버레이 |
| Phase 5: Advanced | ✅ 완료 | TiTiler 통합, 내보내기, 그루핑, 통계 API |
| Phase 6: Hardening | ✅ 완료 | TB급 업로드, Metashape 라이선스 안정화 |
| Phase 7: UX Polish | ✅ 완료 | 멀티 프로젝트 업로드, UI 개선, 버그 수정 |

### 🔮 향후 개선 예정
- 다중 사용자 권한 관리 (역할별 분리)
- 조직 스토리지 할당량 관리
- 그룹 단위 일괄 작업

## ⚠️ Known Issues (2026-02-03)

### 지도 및 상호작용
- **권역 툴팁 우선순위**: 권역(Region)과 프로젝트(Footprint) 중첩 시 바운딩박스 호버에도 권역 툴팁이 표시되는 경우 있음 (CSS + 이벤트 제어로 개선 중)
- **오프라인 타일맵**: `VITE_MAP_OFFLINE=true` 설정 시 로컬 타일 필요 (없으면 회색 배경)

### 시스템
- **COG Loading**: MinIO presigned URL 외부 접근 시 `MINIO_PUBLIC_ENDPOINT` 설정 필요
- **처리 중단 후 재시작 오류**: 동일 프로젝트에서 처리 중단 후 곧바로 재시작할 때 Metashape 단계에서 오류(예: `Empty DEM`)가 발생할 수 있음. EO 파일명 매칭/metadata.txt 상태를 확인하고, 필요 시 EO 재업로드 또는 프로젝트 재생성을 권장.

### 저장소
- **MinIO 디스크 용량 부족 시 업로드 실패**: MinIO가 설치된 디스크의 여유 공간이 임계치(기본 10%) 이하로 떨어지면 **HTTP 507 (Storage Full)** 오류와 함께 모든 업로드가 중단됩니다.
  - **증상**: TUS 로그에 `XMinioStorageFull: Storage backend has reached its minimum free drive threshold` 에러 발생
  - **해결**: `.env`의 `MINIO_DATA_PATH`를 충분한 용량의 드라이브로 설정 (최소 1TB 이상 권장)
  - **긴급 대응**: 실패한 업로드 파일 정리 (`mc rm --recursive --force local/aerial-survey/uploads/`)
  - 상세 내용은 [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md#minio-저장소-관리) 참조

### 배포 (2026-02-03 추가)
- **컨테이너 자동 시작**: `restart: always` 설정됨. Docker 서비스 자동 시작 확인 필요 (`systemctl enable docker`)
- **Metashape 라이센스**: 정상 종료 시 자동 비활성화 (`stop_signal: SIGTERM`). 강제 종료 시 수동 비활성화 필요

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
