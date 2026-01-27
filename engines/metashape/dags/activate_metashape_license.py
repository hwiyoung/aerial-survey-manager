from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime.now(),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
    'retry_delay': timedelta(minutes=5),
}

def activate_license():
    # worker 에서만 import 되도록 함수 내부에 import 구문을 넣음
    import Metashape
    Metashape.license.activate(os.getenv("METASHAPE_LICENSE_KEY"))

dag = DAG(
    'activate_metashape_license',
    default_args=default_args,
    description='A DAG to activate Metashape license',
    schedule_interval=None,
    concurrency=1,
    max_active_runs=1,
)

activate_license_task = PythonOperator(
    task_id='activate_license_task',
    python_callable=activate_license,
    dag=dag,
)
