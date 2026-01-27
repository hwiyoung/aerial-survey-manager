from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
from metashape.common_utils import progress_callback, chnage_task_status_in_ortho, notify_result_in_ortho

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


bash_command_template = """
# PID 파일 경로 설정
PID_FILE="/tmp/{{ params.task_id }}.pid"

if [ -f $PID_FILE ]; then
    rm $PID_FILE
fi

echo $$ > $PID_FILE

python3 {{ params.script_path }} \
--input_images '{{ dag_run.conf["input_images"] | join(",") }}' \
--image_folder '{{ dag_run.conf["image_folder"] }}' \
--output_path '{{ dag_run.conf["output_path"] }}' \
--run_id '{{ dag_run.run_id }}' \
--process_mode '{{ dag_run.conf["process_mode"] }}' \
--output_tiff_name '{{ dag_run.conf["output_tiff_name"] }}' \
--reai_task_id '{{ dag_run.conf["reai_task_id"] }}' \
--input_epsg '{{ dag_run.conf["input_epsg"] }}' \
--output_epsg '{{ dag_run.conf["output_epsg"] }}' &

echo $! >> $PID_FILE

wait
"""

def on_bash_fail(context,task_id):
    dag_run = context.get("dag_run")
    if dag_run:
        output_path = dag_run.conf.get("output_path")
        reai_task_id = dag_run.conf.get("reai_task_id") 
        # progress_callback 함수를 호출하여 실패 처리
        progress_callback(1000, task_id, output_path)
        chnage_task_status_in_ortho(dag_run.run_id,"Fail")
        notify_result_in_ortho(reai_task_id,"분석에 실패했습니다.")
        


dag = DAG(
    'generate_orthophoto-1',
    default_args=default_args,
    description='A DAG to generate orthophoto with progress and refined seamlines',
    schedule_interval=None,
    max_active_runs=1,       # 동시에 DAG 인스턴스는 1개만 실행
    concurrency=2            # DAG 안에서 동시에 실행 가능한 task는 2개
)


align_photos_task = BashOperator(
    task_id='align_photos_task',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    on_failure_callback=lambda context: on_bash_fail(context, "Align Photos"),
    dag=dag,
    params={
        'task_id': 'align_photos_task',
        'script_path': './metashape/align_photos.py'
    },
)

build_depth_map_task = BashOperator(
    task_id='build_depth_map_task',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    on_failure_callback=lambda context: on_bash_fail(context, "Build Depth Maps"),
    dag=dag,
    params={
        'task_id': 'build_depth_map_task',
        'script_path': './metashape/build_depth_maps.py'
    },
)

build_point_cloud = BashOperator(
    task_id='build_point_cloud_task',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    on_failure_callback=lambda context: on_bash_fail(context, "Build Point Cloud"),
    dag=dag,
    params={
        'task_id': 'build_point_cloud_task',
        'script_path': './metashape/build_point_cloud.py'
    },
)

build_dem_task = BashOperator(
    task_id='build_dem_task',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    on_failure_callback=lambda context: on_bash_fail(context, "Build DEM"),
    dag=dag,
    params={
        'task_id': 'build_dem_task',
        'script_path': './metashape/build_dem.py'
    },
)

build_orthomosaic_task = BashOperator(
    task_id='build_orthomosaic_task',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    on_failure_callback=lambda context: on_bash_fail(context, "Build Orthomosaic"),
    dag=dag,
    params={
        'task_id': 'build_orthomosaic_task',
        'script_path': './metashape/build_orthomosaic.py'
    },
)

export_align_photos = BashOperator(
    task_id='export_align_photos',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    dag=dag,
    params={
        'task_id': 'export_align_photos',
        'script_path': './metashape/export_align_photos.py'
    },
)

export_build_dem = BashOperator(
    task_id='export_build_dem',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    dag=dag,
    params={
        'task_id': 'export_build_dem',
        'script_path': './metashape/export_dem.py'
    },
)

export_build_orthomosaic = BashOperator(
    task_id='export_build_orthomosaic',
    bash_command=bash_command_template,
    cwd="/opt/airflow/dags",
    dag=dag,
    params={
        'task_id': 'export_build_orthomosaic',
        'script_path': './metashape/export_orthomosaic.py'
    },
)

align_photos_task >> export_align_photos >> build_depth_map_task >> build_point_cloud
build_point_cloud >> build_dem_task >> [build_orthomosaic_task, export_build_dem]
build_orthomosaic_task >> export_build_orthomosaic
