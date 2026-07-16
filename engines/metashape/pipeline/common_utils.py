import os
import json
import time
from threading import Lock
import requests
import Metashape

# 파일 접근을 동기화하기 위한 Lock 객체
lock = Lock()

_last_logged_progress = {}

def progress_callback(value, task_name, output_path):
    """
    작업 진행 상태를 status.json 파일에 기록하는 함수.
    로그는 10% 단위로만 출력하여 로그 양을 줄임.

    Note: status.json은 processing_router.py에서 실행할 단계만 포함하여 미리 초기화됨.
          이 함수는 기존 status.json을 읽어서 해당 task_name만 업데이트함.
    """
    status_file = os.path.join(output_path, "status.json")

    with lock:  # 파일 접근을 동기화
        status = {}
        if os.path.exists(status_file):
            for attempt in range(2):
                try:
                    with open(status_file, "r") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        status = loaded
                    break
                except Exception:
                    if attempt == 0:
                        time.sleep(0.05)
        if not status:
            manifest_file = os.path.join(output_path, "processing_manifest.json")
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, "r") as f:
                        manifest = json.load(f)
                    for record in manifest.get("steps", {}).values():
                        name = record.get("task_name")
                        if not name:
                            continue
                        if record.get("status") == "completed":
                            status[name] = 100
                        elif record.get("status") == "failed":
                            status[name] = 1000
                except Exception:
                    status = {}
        status[task_name] = round(value, 2)
        with open(status_file, "w") as f:
            json.dump(status, f)

    # 10% 단위로만 로그 출력 (로그 양 감소)
    current_10pct = int(value // 10) * 10
    last_logged = _last_logged_progress.get(task_name, -1)
    if current_10pct > last_logged and current_10pct <= 100:
        _last_logged_progress[task_name] = current_10pct
        print(f"   {task_name}: {current_10pct}%")

def find_files(folder, types):
    """
    지정된 폴더에서 특정 확장자를 가진 파일들을 검색하는 함수.
    """
    return [entry.path for entry in os.scandir(folder) if (entry.is_file() and os.path.splitext(entry.name)[1].lower() in types)]


def change_task_status_in_ortho( run_id, status ):
    """
    API를 호출하여 작업 상태를 업데이트하는 함수.
    """
    # backend 컨테이너 이름을 사용하여 내부 통신
    api_url = f"http://api:8000/api/v1/processing/broadcast"
    payload = {
        "project_id": run_id,
        "status": status,
        "progress": 0,
        "message": f"작업 상태 변경: {status}"
    }
    try:
        response = requests.post(api_url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ 상태 브로드캐스트 실패: {e}")

def notify_result_in_ortho(task_id,comment):
    """
    작업 결과를 알리는 API를 호출하는 함수.
    """
    api_url = f"http://api:8000/api/v1/processing/broadcast"
    payload = {
        "project_id": task_id,
        "status": "processing",
        "progress": 100,
        "message": comment
    }
    
    try:
        response = requests.post(api_url, json=payload)
        if response.status_code == 200:
            print("✅ 작업 결과 알림 성공")
        else:
            print(f"❌ 작업 결과 알림 실패: {response.status_code}")
    except Exception as e:
        print(f"⚠️ 알림 전송 실패: {e}")

def check_success(output_path):
    """
    작업 성공 여부를 확인하는 함수.

    진행률 값 의미:
    - 0-98: 미완료 (진행 중 또는 미시작)
    - 99-100: 완료 (엔진 진행률이 99.9%로 끝나는 경우 대응)
    - 1000: 실패

    Note: status.json에는 실행할 단계만 포함됨 (processing_router.py에서 초기화)
          선택적 단계(예: Build Point Cloud)는 실행하지 않으면 status.json에 포함되지 않음
    """
    status_file = os.path.join(output_path, "status.json")

    if not os.path.exists(status_file):
        print(f"Status file not found: {status_file}")
        return False

    with open(status_file, "r") as f:
        try:
            state = json.load(f)
        except json.JSONDecodeError:
            print(f"Invalid JSON in {status_file}")
            return False

    # 1000은 실패를 의미
    if any(value == 1000 for value in state.values()):
        failed = [k for k, v in state.items() if v == 1000]
        print(f"❌ 일부 작업이 실패했습니다: {failed}")
        return False

    # 99% 이상이면 완료로 간주 (엔진 진행률이 99.9%로 끝나는 경우 대응)
    # result_gsd는 GSD 값이므로 진행률 체크에서 제외
    progress_keys = [k for k in state.keys() if k != 'result_gsd']
    incomplete = {k: v for k, v in state.items() if k in progress_keys and v < 99}

    if incomplete:
        print(f"⚠️ 일부 작업이 아직 완료되지 않았습니다: {incomplete}")
        return False

    print("✅ 모든 작업이 성공했습니다.")
    return True

def _is_license_valid():
    """
    처리 엔진 라이선스가 이미 활성화되어 있는지 로컬에서 확인.
    서버 호출 없이 로컬 .lic 파일 기반으로 검증합니다.
    """
    # 처리 엔진 License().valid
    try:
        lic = Metashape.License()
        if hasattr(lic, 'valid') and lic.valid:
            return True
    except Exception as e:
        print(f"⚠️ License().valid 확인 중 오류: {e}", flush=True)

    # Fallback: engine app activation flag
    try:
        if hasattr(Metashape.app, 'activated') and Metashape.app.activated:
            return True
    except Exception as e:
        print(f"⚠️ app.activated 확인 중 오류: {e}", flush=True)

    return False


def activate_metashape_license():
    """
    환경 변수의 라이선스 키를 사용하여 처리 엔진을 활성화하는 함수.
    이미 활성화된 상태이면 서버에 활성화 요청을 보내지 않습니다.
    """
    license_key = os.getenv("ENGINE_LICENSE_KEY") or os.getenv("METASHAPE_LICENSE_KEY")
    if not license_key:
        print("ℹ️ 처리 엔진 라이선스 키가 설정되지 않았습니다.", flush=True)
        return

    # 1. 로컬 라이선스 검증 (서버 호출 없음)
    if _is_license_valid():
        print("✅ 처리 엔진 라이선스가 이미 활성화되어 있습니다.", flush=True)
        return

    # 2. 라이선스 미활성화 상태 — 서버에 활성화 요청
    print("🔑 처리 엔진 라이선스 활성화 중...", flush=True)

    try:
        Metashape.License().activate(license_key)

        if _is_license_valid():
            print("✅ 처리 엔진 라이선스 활성화 성공", flush=True)
        else:
            print("❌ 처리 엔진 라이선스 활성화 실패", flush=True)

    except Exception as e:
        if "already" in str(e).lower():
            print("ℹ️ 라이선스가 이미 활성화되어 있습니다.", flush=True)
        elif "not available" in str(e).lower():
            print(f"⚠️ 라이선스 가용 수량 부족: {e}", flush=True)
        else:
            print(f"⚠️ 라이선스 활성화 실패: {e}", flush=True)

def deactivate_metashape_license():
    """
    처리 엔진 라이선스를 비활성화하는 함수.
    """
    print("🔒 처리 엔진 라이선스 비활성화를 시도합니다...")
    try:
        Metashape.License().deactivate()
        print("✅ 처리 엔진 라이선스가 성공적으로 비활성화되었습니다.")
    except Exception as e:
        print(f"⚠️ 라이선스 비활성화 중 오류 발생: {e}")


def save_result_gsd(output_path, gsd_meters):
    """
    처리 결과 GSD를 status.json에 저장하는 함수.

    Args:
        output_path: 출력 디렉토리 경로
        gsd_meters: GSD 값 (미터 단위)
    """
    status_file = os.path.join(output_path, "status.json")
    gsd_cm = round(gsd_meters * 100, 4)  # cm 단위로 변환

    with lock:
        if os.path.exists(status_file):
            with open(status_file, "r") as f:
                try:
                    status = json.load(f)
                except Exception:
                    status = {}
        else:
            status = {}

        # 결과 GSD 저장 (cm 단위)
        status["result_gsd"] = gsd_cm

        with open(status_file, "w") as f:
            json.dump(status, f)

    print(f"📊 결과 GSD 저장: {gsd_cm:.2f} cm/pixel")
