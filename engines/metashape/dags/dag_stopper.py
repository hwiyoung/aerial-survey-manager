from airflow import DAG
from airflow.operators.python import PythonOperator
import subprocess
import requests
import json
import os
import base64
from airflow.utils.state import State
from datetime import datetime



# 기본 REST API URL (Airflow 웹서버)
base_url = os.getenv("BASE_URL", "http://airflow-webserver:8080/api/v1")

def terminate_dag_run(**context):
    """
    DAG 실행 시 conf로 전달된 dag_run_id (및 필요시 dag_id)를 사용하여,
    해당 dag run 내의 태스크 인스턴스를 조회한 후,
      - 상태가 running이면 프로세스를 종료 후 failed 업데이트
      - 상태가 queued이면 바로 failed 업데이트합니다.
    """
    # dag_run.conf에서 nest api가 전달한 파라미터를 추출
    dag_run_conf = context['dag_run'].conf
    dag_id = dag_run_conf.get('stop_dag_id', 'generate_orthophoto-1')
    dag_run_id = dag_run_conf.get('dag_run_id')
    if not dag_run_id:
        raise ValueError("DAG 실행 시 conf에 dag_run_id 값이 전달되지 않았습니다.")
    
    # 인증 정보 (환경에 맞게 수정)
    username = "admin"
    password = "admin"
    auth_string = f"{username}:{password}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

    # 태스크 인스턴스 목록 조회
    list_url = f"{base_url}/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances"
    response = requests.get(list_url, headers=headers)
    if response.status_code != 200:
        print(f"❌ 태스크 인스턴스 목록 조회 실패: {response.text}")
        return

    data = response.json()
    task_instances = data.get("task_instances", [])
    if not task_instances:
        print("ℹ️ 해당 dag run에 태스크 인스턴스가 없습니다.")
        return

 # 각 태스크에 대해 상태에 따른 처리
    for task in task_instances:
        task_id = task.get("task_id")
        state = task.get("state")
        if state in [State.RUNNING, State.QUEUED]:
            print(f"ℹ️ 처리 대상 태스크: {task_id} (상태: {state})")
            if state == State.RUNNING:
                # PID 파일 경로: /tmp/{task_id}.pid
                pid_file = f"/tmp/{task_id}.pid"
                if os.path.exists(pid_file):
                    try:
                        with open(pid_file, 'r') as f:
                            pid_list = f.read().strip().splitlines()
                        for pid_str in pid_list:
                            try:
                                pid = int(pid_str)
                                os.kill(pid, 9)
                                print(f"✅ PID {pid} (태스크: {task_id}) 종료 성공")
                            except Exception as kill_error:
                                print(f"⚠️ PID {pid_str} (태스크: {task_id}) 종료 실패: {kill_error}")
                        os.remove(pid_file)
                    except Exception as e:
                        print(f"⚠️ PID 파일 처리 오류 ({pid_file}): {e}")
                else:
                    print(f"⚠️ PID 파일이 존재하지 않습니다: {pid_file}")
            # 태스크 상태를 failed로 업데이트 (REST API PATCH 호출)
            patch_url = f"{base_url}/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}"
            payload = json.dumps({"state": "failed"})
            patch_response = requests.patch(patch_url, headers=headers, data=payload)
            if patch_response.status_code == 200:
                print(f"🔁 상태 업데이트 성공 (failed): {task_id}")
            else:
                print(f"❌ 상태 업데이트 실패: {task_id} / {patch_response.text}")
        else:
            print(f"ℹ️ 처리 대상 아님: {task_id} (상태: {state})")

def dummy_task():
    print("종료 및 실패 처리 완료")

with DAG(
    dag_id='terminate_dag_run_tasks',
    default_args={'owner': 'airflow'},
    description='외부(NestJS)에서 전달받은 dag_run_id 기반으로 dag run의 running/queued 태스크 종료 및 실패 업데이트',
    schedule_interval=None,
    start_date=datetime.now(),
    catchup=False,
    max_active_runs=1,
    concurrency=1
) as dag:

    terminate_tasks = PythonOperator(
        task_id='terminate_dag_run',
        python_callable=terminate_dag_run,
        provide_context=True  # DAG 실행 시 context를 전달
    )

    final_status = PythonOperator(
        task_id='dummy_task',
        python_callable=dummy_task
    )

    terminate_tasks >> final_status
