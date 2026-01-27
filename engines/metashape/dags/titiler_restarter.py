from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import logging
import psutil
import subprocess
import os

def restart_titiler_if_high_memory(
    titiler_container_name=os.getenv("TITILER_CONTAINER_NAME","titiler-titiler-1"),
    memory_threshold_ratio=0.5,  # 50%
):
    """
    titiler 컨테이너 메모리 사용률이 호스트의 50%를 넘으면 자동 재시작 (docker 패키지 없이)
    """
    # 1. 호스트 전체 메모리 구하기
    total_mem = psutil.virtual_memory().total

    # 2. docker stats로 메모리 사용량 확인
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", titiler_container_name],
            capture_output=True, text=True, timeout=10
        )
        mem_usage_str = result.stdout.strip().split('/')[0].strip()  # 예: "123.5MiB"
        if "MiB" in mem_usage_str:
            container_mem = float(mem_usage_str.replace("MiB", ""))
            container_mem_bytes = container_mem * 1024 * 1024
        elif "GiB" in mem_usage_str:
            container_mem = float(mem_usage_str.replace("GiB", ""))
            container_mem_bytes = container_mem * 1024 * 1024 * 1024
        else:
            logging.error(f"Unknown memory unit in '{mem_usage_str}'")
            return
    except Exception as e:
        logging.error(f"Failed to get docker memory stats: {e}")
        return

    ratio = container_mem_bytes / total_mem
    logging.info(f"titiler memory: {container_mem_bytes / (1024**2):.2f}MB / total: {total_mem / (1024**2):.2f}MB ({ratio*100:.1f}%)")

    if ratio > memory_threshold_ratio:
        try:
            logging.warning(f"titiler container memory {ratio*100:.1f}% exceeds threshold, restarting container.")
            subprocess.run(["docker", "restart", titiler_container_name], check=True)
            logging.info("titiler container restarted.")
        except Exception as e:
            logging.error(f"Failed to restart container: {e}")
    else:
        logging.info("Memory usage is within acceptable range. No action taken.")

with DAG(
    dag_id="restart_titiler_if_high_memory",
    start_date=datetime(2025, 6, 27),
    schedule_interval="*/10 * * * *",  # 10분마다
    catchup=False,
    tags=["maintenance"]
) as dag:

    restart_task = PythonOperator(
        task_id="check_and_restart_titiler",
        python_callable=restart_titiler_if_high_memory,
        op_kwargs={
            "titiler_container_name": os.getenv("TITILER_CONTAINER_NAME", "titiler-titiler-1"),
            "memory_threshold_ratio": 0.5
        }
    )