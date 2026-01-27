import os
import json
from threading import Lock
import requests
import Metashape

# 파일 접근을 동기화하기 위한 Lock 객체
lock = Lock()

def progress_callback(value, task_name, output_path):
    """
    작업 진행 상태를 status.json 파일에 기록하는 함수.
    """
    status_file = os.path.join(output_path, "status.json")
    
    with lock:  # 파일 접근을 동기화
        if os.path.exists(status_file):
            with open(status_file, "r") as f:
                try:
                    status = json.load(f)
                except:
                    status = {}
        else:
            status = {
                "Align Photos": 0,
                "Build Depth Maps": 0,
                "Build Point Cloud": 0,
                "Build DEM": 0,
                "Build Orthomosaic": 0
            }
        status[task_name] = round(value, 2)  # 소수점 두 번째 자리로 제한
        with open(status_file, "w") as f:
            json.dump(status, f)

    print(f"\r{task_name} Progress: {value:.2f}% completed", end="")

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

    values = list(state.values())

    if all(value == 100 for value in values):
        print("✅ 모든 작업이 성공했습니다.")
        return True
    elif any(value == 1000 for value in values):
        print("❌ 일부 작업이 실패했습니다.")
        return False
    else:
        print("⚠️ 일부 작업이 아직 완료되지 않았습니다.")
        return False

def activate_metashape_license():
    """
    환경 변수의 라이선스 키를 사용하여 Metashape를 활성화하는 함수.
    """
    license_key = os.getenv("METASHAPE_LICENSE_KEY")
    if not license_key:
        print("ℹ️ METASHAPE_LICENSE_KEY 환경 변수가 설정되지 않았습니다.")
        return

    # 이미 활성화되어 있는지 여러 방법으로 체크
    is_activated = False
    try:
        if Metashape.License().activated:
            is_activated = True
    except:
        pass
    
    try:
        if not is_activated and Metashape.app.activated:
            is_activated = True
    except:
        pass

    if is_activated:
        print("✅ Metashape가 이미 활성화되어 있습니다.")
        return

    print(f"🔑 Metashape 라이선스 활성화를 시도합니다... (Key: {license_key[:5]}***)")
    print(f"📣 Machine ID Check: {Metashape.License().machine_id if hasattr(Metashape.License(), 'machine_id') else 'N/A'}")
    try:
        # 기존에 엉킨 세션이 있을 수 있으므로 비활성화를 먼저 시도시도 (실패해도 무방)
        try:
            Metashape.License().deactivate()
            print("ℹ️ 이전 라이선스 세션 비활성화를 시도했습니다.")
        except Exception as de_e:
            print(f"ℹ️ 세션 비활성화 건너뜀 (이미 비어있을 수 있음): {de_e}")
            
        print("📣 Metashape.License().activate() 호출 중...")
        Metashape.License().activate(license_key)
        
        # 활성화 확인
        if Metashape.License().activated:
            print("✅ Metashape.License().activated: True")
        if Metashape.app.activated:
            print("✅ Metashape.app.activated: True")
            
        if Metashape.License().activated or Metashape.app.activated:
            print("✅ Metashape 라이선스 활성화 최종 성공")
        else:
            print("❌ Metashape 라이선스 활성화 실패 (에러는 없으나 상태가 False)")
    except Exception as e:
        if "already" in str(e).lower():
            print(f"ℹ️ 라이선스가 이미 활성화되어 있습니다 (Exception): {e}")
        elif "not available" in str(e).lower():
            print(f"⚠️ 라이선스 가용 수량 부족! (중요: 다른 곳에서 비활성화가 필요할 수 있습니다): {e}")
            # 이 에러가 나면 비활성화를 한 번 더 명시적으로 시도해볼 수 있음
            try: Metashape.License().deactivate() 
            except: pass
        else:
            print(f"⚠️ 라이선스 활성화 중 예외 발생: {e}")
            import traceback
            traceback.print_exc()

def deactivate_metashape_license():
    """
    Metashape 라이선스를 비활성화하는 함수.
    """
    print("🔒 Metashape 라이선스 비활성화를 시도합니다...")
    try:
        Metashape.License().deactivate()
        print("✅ Metashape 라이선스가 성공적으로 비활성화되었습니다.")
    except Exception as e:
        print(f"⚠️ 라이선스 비활성화 중 오류 발생: {e}")