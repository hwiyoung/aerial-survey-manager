from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime.now(),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 0,
    'retry_delay': timedelta(minutes=5),
}

def deactivate_license():
    # worker 에서만 import 되도록 함수 내부에 import 구문을 넣음
    import Metashape
    Metashape.license.deactivate()

dag = DAG(
    'deactivate_metashape_license',
    default_args=default_args,
    description='A DAG to deactivate Metashape license',
    schedule_interval=None,
    concurrency=1,
    max_active_runs=1,
)

deactivate_license_task = PythonOperator(
    task_id='deactivate_license_task',
    python_callable=deactivate_license,
    dag=dag,
)
