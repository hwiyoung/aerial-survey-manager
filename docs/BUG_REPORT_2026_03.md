# 시스템 전반 버그 및 비효율 분석 리포트

> 작성일: 2026-03-18
> 분석 범위: 백엔드(FastAPI/Celery), 프론트엔드(React), 인프라(Docker)

---

## 요약

| 구분 | 건수 |
|------|------|
| 🔴 크리티컬 버그 | 5 |
| 🟠 미디엄 버그 | 10 |
| 🟡 코드 품질 | 4 |
| 🔵 인프라 | 5 |
| ⚠️ 보안 | 2 |
| **합계** | **26** |

---

## 🔴 크리티컬 버그

### C1. WebSocket 연결 메모리 누수
**파일**: `backend/app/api/v1/processing.py:155-177`

`ConnectionManager.disconnect()`에서 연결이 리스트에 없는 경우 예외처리 없이 실패. 브라우저가 새로고침/종료 시 dead connection이 리스트에 영구 잔류함. 브로드캐스트 시 dead connection에 반복 전송 시도 → 전송 실패를 조용히 무시하면서 연결 수가 계속 증가.

```python
# 현재: 실패해도 리스트에서 제거 안됨
async def broadcast(self, message):
    for connection in self.active_connections:
        await connection.send_json(message)  # 실패 시 연결 잔류
```

**영향**: 장기 운영 시 메모리 점진적 증가, 브로드캐스트 지연

---

### C2. N+1 쿼리 - 프로젝트 목록 조회
**파일**: `backend/app/api/v1/projects.py:296-345`

프로젝트 목록 API에서 프로젝트 1건당 DB 쿼리 3건 실행 (이미지 수, 작업 수 등). 페이지당 20개 프로젝트 = **60+ 쿼리** 발생.

**영향**: 페이지 로드 지연, DB 부하, 사이드바 폴링 시 5초마다 반복

---

### C3. 예외 무시 (bare except)
**파일**: `backend/app/api/v1/download.py:289-291, 317-319, 607-612 외 다수`

```python
try:
    os.remove(temp_file)
except:
    pass  # 임시 파일이 쌓여도 모름
```

실패 시 로깅 없이 무시 → 디스크 공간 낭비, 디버깅 불가.

**영향**: 임시 파일 누적, 운영 중 문제 파악 어려움

---

### C4. 잘못된 서명 검증 (보안)
**파일**: `backend/app/api/v1/upload.py:40`

```python
# 현재 (취약)
signature == hashlib.sha256(body + token).hexdigest()

# 올바른 방법
hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
```

단순 SHA256 연결(concatenation)은 **Length Extension Attack**에 취약한 HMAC이 아님.

**영향**: 웹훅 서명 위조 가능성

---

### C5. 태스크 멱등성 Race Condition
**파일**: `backend/app/workers/tasks.py:266-283`

`job.status == "completed"` 체크와 상태 업데이트 사이에 다른 워커가 개입 가능. DB 트랜잭션으로 원자적 처리 필요.

**영향**: 중복 처리 또는 작업 소실 (드문 경우)

---

## 🟠 미디엄 버그

### M1. Dead WebSocket 연결 잔류
`broadcast()` 실패 시 해당 연결을 active 리스트에서 제거하지 않음. 실패한 연결에 계속 재시도.

```python
# 수정 방법
async def broadcast(self, message):
    dead = []
    for connection in self.active_connections:
        try:
            await connection.send_json(message)
        except:
            dead.append(connection)
    for conn in dead:
        self.active_connections.remove(conn)
```

---

### M2. AbortController 미사용
**파일**: `src/api/client.js:57-90`

페이지 이동 시 진행 중인 API 요청이 취소되지 않음. 특히 대용량 파일 준비(batch export) 시 불필요한 서버 작업 지속.

---

### M3. setInterval 클린업 누락
**파일**: `src/components/Project/ExportDialog.jsx:82`

컴포넌트 언마운트 시 `progressIntervalRef.current`를 클리어하는 `useEffect` cleanup 없음.

```javascript
// 누락된 cleanup
useEffect(() => {
    return () => {
        if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
        }
    };
}, []);
```

---

### M4. WebSocket 예외 처리 불충분
**파일**: `backend/app/api/v1/processing.py:933`

`WebSocketDisconnect`만 캐치, timeout/reset 등 다른 예외 미처리.

---

### M5. 썸네일 생성 실패 무시
**파일**: `backend/app/api/v1/upload.py:238-243`

`generate_thumbnail.delay()` 실패 시 이미지에 에러 상태 표시 없음. 사용자 입장에서 영구적으로 "미리보기 없음" 상태.

---

### M6. 비동기 핸들러 내 동기 파일 I/O
**파일**: `backend/app/api/v1/download.py:380-402`

`os.path.exists()`, `os.path.getsize()`가 async 핸들러 내에서 직접 호출 → 이벤트 루프 블로킹.

```python
# 수정 방법
import asyncio
exists = await asyncio.to_thread(os.path.exists, path)
```

---

### M7. DB 인덱스 누락 (성능)

자주 조회하는 복합 쿼리에 인덱스 없음:
- `images.project_id + upload_status`
- `processing_jobs.project_id + status`

프로젝트당 수백~수천 이미지 시 sequential scan 발생.

---

### M8. 다운로드 스트리밍 청크 고정
**파일**: `backend/app/api/v1/download.py:282-287`

청크 크기가 8MB 고정. 저속 네트워크에서 버퍼 문제 가능.

---

### M9. 사이드바 전체 목록 폴링
**파일**: `src/components/Dashboard/Sidebar.jsx:38`

5초마다 전체 프로젝트 목록을 가져오는 폴링. N+1 쿼리(C2)와 결합 시 DB 부하 심화. WebSocket 이벤트로 충분한 경우가 대부분.

---

### M10. GSD 입력 검증 미비
**파일**: `src/components/Project/ExportDialog.jsx`

```javascript
gsd: gsd  // NaN, Infinity, 음수 그대로 전달 가능
```

서버에서도 별도 검증 없으면 잘못된 GSD로 내보내기 시도.

---

## 🟡 코드 품질

### Q1. 에러 바운더리 없음
`src/App.jsx`에 React Error Boundary 미적용. 하위 컴포넌트 에러 시 전체 앱 흰 화면.

### Q2. 로깅 불일치
`upload.py` 내 일부는 `print()`, 일부는 `logger.warning()` 혼용. 운영 환경에서 `print()` 는 로그 수집 시스템에 잡히지 않을 수 있음.

### Q3. 웹훅 재시도 없음
`broadcast_to_project()` 실패 시 5초 타임아웃 후 종료. 재시도 로직 없어 프론트엔드가 처리 완료를 놓칠 수 있음.

### Q4. 대용량 파일 처리 후 임시파일 정리 불확실
내보내기(export) 과정에서 생성된 임시 zip/tif 파일의 cleanup이 예외 발생 시 보장되지 않음.

---

## 🔵 인프라

### I1. 컨테이너 리소스 제한 없음
**파일**: `docker-compose.yml`

`api`, `celery-worker`, `celery-worker-thumbnail` 서비스에 `mem_limit`, `cpus` 미설정. 단일 작업이 호스트 전체 메모리 소비 가능.

### I2. 워커 헬스체크 없음
`worker-engine`, `celery-worker`, `celery-worker-thumbnail` 에 `healthcheck` 없음. 좀비 프로세스 상태로 작업 큐에서 받아만 하고 처리 안 하는 경우 감지 불가.

### I3. DB 커넥션 풀 설정 미확인
동시 요청 증가 시 `pool_size` 초과로 연결 대기 가능. `pool_size=20, max_overflow=40` 수준으로 명시 설정 권장.

### I4. 컨테이너 종료 대기 시간 부족
GPU 처리 중 컨테이너 재시작 시 30초 내 정상 종료 불가. `stop_grace_period: 120s` 설정 필요 (특히 `worker-engine`).

### I5. CORS 설정 과도하게 허용
`CORS_ORIGINS=*` 설정 시 모든 출처에서 인증 토큰 포함 요청 가능. 프론트엔드 도메인만 허용하도록 제한 필요.

---

## 우선순위 권장 수정 순서

| 순위 | 항목 | 이유 |
|------|------|------|
| 1 | **C2 N+1 쿼리 + M9 폴링** | 운영 중 가장 빈번히 발생하는 DB 부하 |
| 2 | **C1/M1 WebSocket 메모리 누수** | 장기 운영 시 서버 안정성 직결 |
| 3 | **C3 bare except 정리** | 운영 디버깅 가능성 확보 |
| 4 | **M3 setInterval 클린업** | 내보내기 사용 빈번, 메모리 누수 실용적 문제 |
| 5 | **C4 HMAC 서명 검증** | 보안 (내부망 운영이면 낮출 수 있음) |
| 6 | **I4 stop_grace_period** | GPU 처리 중 재시작 시 데이터 손실 방지 |
| 7 | **I2 워커 헬스체크** | 장애 자동 감지 |

---

*분석 기준: 2026-03-18 기준 main 브랜치 코드*
