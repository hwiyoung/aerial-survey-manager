from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.state import State
from datetime import datetime
import base64
import json
import os
import signal
import subprocess
import time
import requests

BASE_URL = os.getenv("BASE_URL", "http://airflow-webserver:8082/api/v1")
USERNAME = os.getenv("AIRFLOW_API_USERNAME", "admin")
PASSWORD = os.getenv("AIRFLOW_API_PASSWORD", "admin")

def _auth_headers():
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Basic {token}",
    }

def _sanitize_task_id(task_id: str) -> str:
    return task_id.replace(".", "_") if task_id else ""

def _sanitize_run_id(run_id: str) -> str:
    if not run_id:
        return "unknown"
    sanitized = run_id.replace(":", "-").replace(".", "-").replace("_", "-").replace("+", "-")
    return sanitized

def _derive_model_name(task_id: str) -> str:
    if not task_id:
        return "unknown"
    leaf = task_id.split(".")[-1]
    parts = leaf.split("_")
    return parts[-1] if parts else leaf

def _derive_container_name(run_id: str, task_id: str) -> str:
    model = _derive_model_name(task_id)
    return f"cd-{_sanitize_run_id(run_id)}-{model}"

def _stop_container(container_name: str) -> None:
    if not container_name:
        return
    for cmd in (["docker", "stop", container_name], ["docker", "rm", container_name]):
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                print(result.stdout.strip())
            if result.returncode != 0 and result.stderr:
                print(f"[WARN] {' '.join(cmd)}: {result.stderr.strip()}")
        except Exception as exc:
            print(f"[ERROR] Failed to run {' '.join(cmd)}: {exc}")

def _kill_processes(pid_file: str, task_id: str) -> None:
    if not os.path.exists(pid_file):
        print(f"[INFO] PID file missing for {task_id}: {pid_file}")
        return
    try:
        with open(pid_file, "r", encoding="utf-8") as handle:
            pids = [line.strip() for line in handle if line.strip()]
    except Exception as exc:
        print(f"[WARN] Unable to read pid file {pid_file}: {exc}")
        return
    for pid_str in pids:
        try:
            pid = int(pid_str)
        except ValueError:
            print(f"[WARN] Invalid PID entry {pid_str} in {pid_file}")
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                print(f"[INFO] Process {pid} terminated for {task_id}")
            else:
                os.kill(pid, signal.SIGKILL)
                print(f"[INFO] Process {pid} force-killed for {task_id}")
        except Exception as exc:
            print(f"[WARN] Failed to signal PID {pid} for {task_id}: {exc}")
    try:
        os.remove(pid_file)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[WARN] Unable to remove pid file {pid_file}: {exc}")

def terminate_change_detection_run(**context):
    dag_run = context.get("dag_run")
    dag_run_conf = dag_run.conf if dag_run else {}
    dag_id = dag_run_conf.get("stop_dag_id", "change_detection")
    dag_run_id = dag_run_conf.get("dag_run_id")
    if not dag_run_id:
        raise ValueError("dag_run_id must be supplied via DAG run conf")

    list_url = f"{BASE_URL}/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances"
    response = requests.get(list_url, headers=_auth_headers(), timeout=10)
    if response.status_code != 200:
        print(f"[ERROR] Failed to fetch task instances: {response.text}")
        return

    task_instances = response.json().get("task_instances", [])
    if not task_instances:
        print("[INFO] No task instances found for supplied dag_run_id")
        return

    dag_run_url = f"{BASE_URL}/dags/{dag_id}/dagRuns/{dag_run_id}"
    dag_run_resp = requests.get(dag_run_url, headers=_auth_headers(), timeout=10)
    run_payload = dag_run_resp.json() if dag_run_resp.status_code == 200 else {}

    for task in task_instances:
        task_id = task.get("task_id")
        state = task.get("state")
        safe_task_id = _sanitize_task_id(task_id)
        pid_file = f"/tmp/change_detection_{safe_task_id}.pid"
        container_file = f"/tmp/change_detection_{safe_task_id}.container"
        should_interrupt = state in {
            State.RUNNING,
            State.QUEUED,
            State.UP_FOR_RETRY,
            State.UP_FOR_RESCHEDULE,
        }
        if not should_interrupt:
            print(f"[INFO] Skip task {task_id} (state={state})")
            continue

        print(f"[INFO] Terminating task {task_id} (state={state})")
        if state == State.RUNNING:
            _kill_processes(pid_file, task_id)
        container_name = None
        if os.path.exists(container_file):
            try:
                with open(container_file, "r", encoding="utf-8") as handle:
                    container_name = handle.read().strip()
            except Exception as exc:
                print(f"[WARN] Unable to read container file {container_file}: {exc}")
        if not container_name:
            container_name = _derive_container_name(dag_run_id, task_id)
        _stop_container(container_name)
        try:
            os.remove(container_file)
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[WARN] Unable to remove container file {container_file}: {exc}")

        patch_url = f"{BASE_URL}/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}"
        payload = json.dumps({"state": "failed"})
        patch_response = requests.patch(patch_url, headers=_auth_headers(), data=payload, timeout=10)
        if patch_response.status_code == 200:
            print(f"[INFO] Task {task_id} marked as failed")
        else:
            print(f"[ERROR] Failed to update task {task_id}: {patch_response.text}")

    run_state = run_payload.get("state")
    if run_state not in {State.FAILED, State.SUCCESS}:
        run_patch_url = f"{BASE_URL}/dags/{dag_id}/dagRuns/{dag_run_id}"
        run_payload = json.dumps({"state": "failed"})
        run_response = requests.patch(run_patch_url, headers=_auth_headers(), data=run_payload, timeout=10)
        if run_response.status_code == 200:
            print(f"[INFO] DAG run {dag_run_id} marked as failed")
        else:
            print(f"[WARN] Unable to mark dag run {dag_run_id} as failed: {run_response.text}")


def finalize(**_):
    print("change_detection run termination complete")

with DAG(
    dag_id="terminate_change_detection_run",
    default_args={"owner": "airflow"},
    description="Stop running change_detection tasks and fail the dag run",
    schedule_interval=None,
    start_date=datetime.now(),
    catchup=False,
    max_active_runs=1,
    concurrency=1,
) as dag:
    terminate = PythonOperator(
        task_id="terminate_change_detection",
        python_callable=terminate_change_detection_run,
        provide_context=True,
    )

    complete = PythonOperator(
        task_id="finalize",
        python_callable=finalize,
    )

    terminate >> complete
