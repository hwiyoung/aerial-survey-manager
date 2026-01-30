# Admin Guide (비공개 관리자용)

이 문서는 민감한 시스템 설정 및 라이선스 관리 정보를 포함하므로 외부에 공개되지 않도록 관리자만 접근해야 합니다.

## 🔑 Metashape Licensing Management

`worker-metashape` 컨테이너의 라이선스 관리 전략에 대한 상세 기술 문서입니다.

### 1. Persistence Strategy (불사조 전략)
Docker 환경 특성상 컨테이너가 빈번하게 생성/삭제되므로, 라이선스 유실 방지를 위해 다음 두 가지 방어 기제를 적용했습니다.

#### A. MAC 주소 고정 (Static ID)
Agisoft의 Node-Locked 라이선스는 기기의 MAC 주소를 "Machine ID"로 사용합니다. 컨테이너가 변경되어도 동일 기기로 인식되도록 강제합니다.
- **설정 파일**: `docker-compose.yml`
- **적용 값**: `mac_address: "02:42:AC:17:00:64"`
- **주의**: 이 값을 변경하면 Agisoft 서버는 이를 "새로운 컴퓨터"로 인식하여 라이선스 재인증을 요구합니다. 절대 임의 변경하지 마세요.

#### B. 라이선스 파일 이중 저장 (Volume Mount)
Metashape 엔진이 로컬에 저장하는 라이선스 파일(`.lic`)을 영구 보존하기 위해 네임드 볼륨에 마운트합니다.
- **볼륨명**: `metashape-license`
- **컨테이너 내부 경로**: `/var/tmp/agisoft/licensing` (Metashape 2.2.0 기준)

### 2. Troubleshooting: "Key Already In Use"
만약 라이선스 오류(`Activation key is already in use`)가 발생한다면, 이는 **현재 컨테이너의 상태와 Agisoft 서버의 기록이 불일치**하기 때문입니다.

#### 해결 절차
1. **Agisoft Support Contact**: 기술지원팀에 해당 라이선스 키의 "Deactivation(초기화)"를 요청합니다.
   - 사유: "Docker 컨테이너 교체 중 기존 인스턴스 소실로 인한 재설정"
2. **Force Recreate**: 리셋 승인 후, 컨테이너를 강제로 재생성하여 정해진 MAC 주소로 다시 시작합니다.
   ```bash
   docker-compose up -d --force-recreate worker-metashape
   ```
3. **수동 활성화**: 컨테이너 시작 후 `activate.py`를 실행하여 라이선스를 활성화합니다.
   ```bash
   docker exec worker-metashape python3 /app/engines/metashape/dags/metashape/activate.py
   ```
   성공 시 `.lic` 파일이 `/var/tmp/agisoft/licensing/licenses/` 폴더에 생성되며, 이후에는 영구적으로 유지됩니다.

### 3. 수동 복구 (Manual Recovery)
컨테이너가 실수로 삭제되었으나 라이선스를 다른 물리 서버로 옮기고 싶은 경우:
1. `docker-compose.yml`에 정의된 것과 동일한 MAC 주소로 임시 컨테이너를 실행합니다.
2. `deactivate.py`를 실행하여 명시적으로 라이선스를 반납합니다.
   ```bash
   docker exec worker-metashape python3 /app/engines/metashape/dags/metashape/deactivate.py
   ```

---

## 처리 진행 상태 캐시 (운영/디버깅)

처리 화면 재진입 시 마지막 단계 메시지와 진행률을 즉시 복구하기 위해,
워커가 처리 상태를 파일로 캐시합니다.

- 경로: `/data/processing/{project_id}/processing_status.json`
- 예시 내용:
  ```json
  {"status":"processing","progress":42,"message":"이미지 정렬 (Align Photos)","updated_at":"..."}
  ```

## Known Issue: 취소 후 재시작 오류

- 동일 프로젝트에서 **처리 중단 직후 재시작**할 경우 Metashape 파이프라인에서 `Empty DEM` 등의 오류가 발생할 수 있습니다.
- 이 경우 EO 파일명 매칭 실패/metadata.txt 불일치 가능성이 높으므로, 아래를 우선 확인하세요:
  - `/data/processing/{project_id}/images/metadata.txt`의 이미지 파일명과 실제 이미지 파일명이 일치하는지
  - `worker-metashape` 로그에서 `reference_normalized.txt exists=True` 여부
  - 필요 시 EO 재업로드 또는 프로젝트 재생성
