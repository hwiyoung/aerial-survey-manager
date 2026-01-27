from airflow import DAG
from datetime import datetime
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.operators.dummy import DummyOperator
from airflow.utils.task_group import TaskGroup
from airflow.exceptions import AirflowFailException
import subprocess
import os
import shutil
import requests


def update_detection_status(status: str, change_task_id: str, backend_url: str) -> None:
    """PATCH detection task status back to backend service."""
    if not change_task_id:
        print("[WARN] change_detaction_task_id missing; skip status update")
        return

    if not backend_url:
        print("[WARN] BACKEND_URL_CD missing; skip status update")
        return

    url = f"{backend_url.rstrip('/')}/detection-tasks/{change_task_id}/status"
    payload = {"status": status}

    try:
        response = requests.patch(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[INFO] Detection task {change_task_id} status updated to {status}")
    except Exception as exc:
        print(f"[ERROR] Failed to update detection task status: {exc}")


def notify_failure(context):
    """Airflow failure callback to notify backend when a task fails."""
    dag_run = context.get("dag_run")
    conf = dag_run.conf if dag_run else {}
    change_task_id = conf.get("change_detaction_task_id")
    backend_url_cd = os.getenv("BACKEND_URL_CD", "http://localhost:3034")
    update_detection_status("failed", change_task_id, backend_url_cd)

def notify_run(context):
    """Airflow callback to notify backend when a dag run starts."""
    dag_run = context.get("dag_run")
    conf = dag_run.conf if dag_run else {}
    change_task_id = conf.get("change_detaction_task_id")
    backend_url_cd = os.getenv("BACKEND_URL_CD", "http://localhost:3034")
    update_detection_status("running", change_task_id, backend_url_cd)

def notify_finish(context):
    """Airflow callback to notify backend when a dag run finishes successfully."""
    dag_run = context.get("dag_run")
    conf = dag_run.conf if dag_run else {}
    change_task_id = conf.get("change_detaction_task_id")
    backend_url_cd = os.getenv("BACKEND_URL_CD", "http://localhost:3034")
    update_detection_status("finished", change_task_id, backend_url_cd)

def preprocess_input(**kwargs):

    # conf에서 파라미터 추출
    conf = kwargs["dag_run"].conf
    input_t1_path = conf.get("input_t1_path").replace(os.getenv("DEFAULT_PATH","./../../"),"/app")
    input_t2_path = conf.get("input_t2_path").replace(os.getenv("DEFAULT_PATH","./../../"),"/app")
    compare_type = conf.get("compare_type", "image-image")  # 기본값 설정

    notify_run(context=kwargs)
    
    workspace = "/app"
    dataset_dir = os.path.join(workspace, ".inputs/change-detection/workspace")



    t1_dir = os.path.join(dataset_dir, "T1")
    t2_dir = os.path.join(dataset_dir, "T2")


    print(f"Dataset Directory: {dataset_dir}")
    for dir_path in [t1_dir, t2_dir]:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
        os.makedirs(dir_path)

        
    if compare_type == "image-image":
        cmd = [
            "python3", "/opt/airflow/dags/utils/match_orthophotos.py",
            "--inputs", input_t1_path, input_t2_path,
            "--outdir", dataset_dir
        ]
        subprocess.run(cmd, check=True)
    
    elif compare_type == "image-digital":
        # ✅ SHP 관련 파일들 복사
        def copy_shapefile_set(src_path, dst_dir):
            base, _ = os.path.splitext(src_path)
            extensions = [".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd",".geojson"]
            for ext in extensions:
                candidate = base + ext
                if os.path.exists(candidate):
                    shutil.copy(candidate, os.path.join(dst_dir, os.path.basename(candidate)))
                    print(f"📁 copied: {candidate} → {dst_dir}")

        shutil.copy(input_t2_path, os.path.join(dataset_dir, "T2", "change_detection.tif"))
        copy_shapefile_set(input_t1_path, t1_dir)
    else:
        raise ValueError(f"❌ Unknown compare_type: {compare_type}")
    
    return dataset_dir

# [todo]  road 모델에 대한 처리 추가
def get_request_payload(compare_type, model, task_id):
    if compare_type == "image-image":
        if "building" in model:
            return {
                "model": "building",
                "resultPath": f"{task_id}/results/change_detection",
                "resultFileName": "change_detection.json"
            }
        elif "road" in model:
            return {
                "model": "road",
                "resultPath": f"{task_id}",
                "resultFileName": "change_detection.json"
            }
    elif compare_type == "image-digital":
        if "building" in model:
            return {
                "model": "building",
                "resultPath": f"{task_id}",
                "resultFileName": "result.json"
            }
        elif "road" in model:
            return {
                "model": "building",
                "resultPath": f"{task_id}",
                "resultFileName": "result.json"
            }

def get_docker_config(compare_type, model):
    if compare_type == "image-image":
        if "building" in model:
            return {
                "image": "repo.innopam.kr/ai/building_cd:1.0.1",
                "script": "python /app/.inputs/change-detection/workspace/building_II.py"
            }
        elif "road" in model:
            return {
                "image": "repo.innopam.kr/ai/road_cd:1.0.0",
                "script": "python /app/.inputs/change-detection/workspace/road_II.py"
            }
    elif compare_type == "image-digital":
        if "building" in model:
            return {
                "image": "repo.innopam.kr/ai/building_v_shp:1.0.0",
                "script": "python3 /app/.inputs/change-detection/workspace/building_ID.py"
            }
        elif "road" in model:
            return {
                "image": "repo.innopam.kr/ai/building_v_shp:1.0.0",
                "script": "python3 /app/.inputs/change-detection/workspace/building_ID.py"
            }
    return {
        "image": None,
        "script": None
    }


def parse_models(**kwargs):
    """모델 문자열을 파싱하여 리스트로 반환"""
    conf = kwargs["dag_run"].conf
    models_str = conf.get("model", "building")
    models = [model.strip() for model in models_str.split(",")]
    return models

def should_run_model(model_name, **kwargs):
    """특정 모델이 실행되어야 하는지 확인"""
    models = parse_models(**kwargs)
    return model_name in models

def conditional_resolve_config(model_name):
    def _resolve_config(**kwargs):
        print(f"[DEBUG] conditional_resolve_config called for model: {model_name}")
        if not should_run_model(model_name, **kwargs):
            print(f"[DEBUG] should_run_model({model_name}) == False, returning None dict")
            return {
                "image": "None",
                "script": "None"
            }
        conf = kwargs["dag_run"].conf
        compare_type = conf.get("compare_type", "image-image")
        config = get_docker_config(compare_type, model_name)
        print(f"[DEBUG] Returning config for {model_name}: {config}")
        return config
    return _resolve_config

def conditional_api_request(model_name):
    def _api_request(**kwargs):
        if not should_run_model(model_name, **kwargs):
            print(f"Skipping API request for {model_name}")
            return
        
        backend_url_cd = os.getenv("BACKEND_URL_CD","http://localhost:3034")
        conf = kwargs["dag_run"].conf
        change_detaction_task_id = conf.get('change_detaction_task_id')
        compare_type = conf.get('compare_type')

        api_url = f"{backend_url_cd}/detection-objects/{change_detaction_task_id}/bulk"
        payload = get_request_payload(compare_type, model_name, f"{change_detaction_task_id}/{model_name}")
        

        expected_path = os.path.join(
            "/app/.outputs/change-detection",
            payload["resultPath"],
            payload["resultFileName"],
        )

        if not os.path.exists(expected_path):
            print(f"[ERROR] Expected result file missing for {model_name}: {expected_path}")
            notify_failure(kwargs)
            raise AirflowFailException(f"Missing result file for {model_name}")

        if model_name == "building" and compare_type == "image-image":
            cmd = ["python3", "/opt/airflow/dags/utils/ombb.py", "-o", expected_path, expected_path]

            subprocess.run(cmd, check=True)


        response = requests.post(api_url, json=payload)

        if response.status_code == 201:
            print(f"API call successful for {model_name}")
        else:
            print(f"API call failed for {model_name} with status code:", response.status_code)
    return _api_request

def create_conditional_gpu_task(model_name):

    return BashOperator(
        task_id=f"run_gpu_container_{model_name}",
        bash_command="""
        {% set config = task_instance.xcom_pull(task_ids=params.resolve_config_task_id) %}
        {% if config['image'] == 'None' %}
        echo "Skipping GPU task for {{ params.model_name }} as it is not configured to run."
        exit 0
        {% endif %}

        set -euo pipefail

        PID_FILE="/tmp/change_detection_{{ ti.task_id|replace('.', '_') }}.pid"
        CONTAINER_FILE="/tmp/change_detection_{{ ti.task_id|replace('.', '_') }}.container"
        CONTAINER_NAME="cd-{{ dag_run.run_id|replace(':', '-')|replace('.', '-')|replace('_', '-')|replace('+', '-') }}-{{ params.model_name }}"

        cleanup() {
            docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
            docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
            rm -f "$PID_FILE" "$CONTAINER_FILE"
        }
        trap cleanup EXIT

        rm -f "$PID_FILE" "$CONTAINER_FILE"
        echo $$ > "$PID_FILE"
        echo "$CONTAINER_NAME" > "$CONTAINER_FILE"

        IMAGE="{{ config['image'] }}"
        SCRIPT="{{ config['script'] }}"

        docker run --rm --name "$CONTAINER_NAME" --gpus device=0 \
        --device /dev/nvidia-uvm:/dev/nvidia-uvm \
        --device /dev/nvidia-uvm-tools:/dev/nvidia-uvm-tools \
        --device /dev/nvidia-modeset:/dev/nvidia-modeset \
        --device /dev/nvidiactl:/dev/nvidiactl \
        --device /dev/nvidia0:/dev/nvidia0 \
        -v {{ params.default_path }}/.outputs:/app/.outputs \
        -v {{ params.default_path }}/.inputs:/app/.inputs \
        -e PYTHONUNBUFFERED=1 -e FORCE_COLOR=1 --shm-size=50g \
        "$IMAGE" \
        $SCRIPT \
        --dataset_path /app/.inputs/change-detection/workspace \
        --output_path /app/.outputs/change-detection/{{ dag_run.conf.get('change_detaction_task_id', 'default') }}/{{ params.model_name }} \
        --model_path /app/.inputs/change-detection/workspace/model/{{ dag_run.conf.get('compare_type', 'default') }}/{{ params.model_name }} &

        DOCKER_PID=$!
        echo "$DOCKER_PID" >> "$PID_FILE"
        wait "$DOCKER_PID"
    """,
        env={"CUDA_VISIBLE_DEVICES": "0"},
        params={
            "model_name": model_name,
            "resolve_config_task_id": f"{model_name}_tasks.resolve_config_{model_name}",
            "default_path": os.getenv("DEFAULT_PATH", "./../../")
        }
    )

with DAG(
    dag_id="change_detection",
    default_args={
        'owner': 'airflow',
        'on_failure_callback': notify_failure,
    },
    start_date=datetime.now(),
    schedule_interval=None,
    max_active_runs=1,     
    concurrency=2  
) as dag:
    
    preprocess = PythonOperator(
        task_id="preprocess_input_data",
        python_callable=preprocess_input,
    )

    start_task = DummyOperator(task_id="start")
    end_task = DummyOperator(task_id="end", on_success_callback=notify_finish)

    # 각 모델별로 태스크 그룹 생성
    with TaskGroup("building_tasks") as building_group:
        resolve_config_building = PythonOperator(
            task_id="resolve_config_building",
            python_callable=conditional_resolve_config("building"),
        )
        
        run_gpu_building = create_conditional_gpu_task("building")
        
        api_request_building = PythonOperator(
            task_id="api_request_building",
            python_callable=conditional_api_request("building"),
        )
        
        resolve_config_building >> run_gpu_building >> api_request_building

    with TaskGroup("road_tasks") as road_group:
        resolve_config_road = PythonOperator(
            task_id="resolve_config_road",
            python_callable=conditional_resolve_config("road"),
        )
        
        run_gpu_road = create_conditional_gpu_task("road")
        
        api_request_road = PythonOperator(
            task_id="api_request_road",
            python_callable=conditional_api_request("road"),
        )
        
        resolve_config_road >> run_gpu_road >> api_request_road

    start_task >> preprocess >> building_group >> road_group >> end_task