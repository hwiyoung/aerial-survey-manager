import Metashape
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho
import os
import requests

def build_point_cloud( output_path, run_id,reai_task_id):
    """
    Generate an orthophoto and other outputs with progress tracking and refined seamlines.
    
    Parameters:
      input_images (list): List of image file paths.
      output_path (str): Base path to save the generated outputs.
      process_mode (str): "preview", "normal", or "high"
    """

    
    def progress_callback_wrapper(value):
        progress_callback(value, task_name, output_path)
    
    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    try:
        print("🛠 Build Point Cloud...")
        task_name = "Build Point Cloud"
        chunk = doc.chunk
        chunk.buildPointCloud(
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')

        chunk.exportPointCloud(path=os.path.join(output_path,"point_cloud.zip"),source_data = Metashape.DataSource.PointCloudData,format=Metashape.PointCloudFormat.PointCloudFormatCesium,crs=Metashape.CoordinateSystem("EPSG::4326"))
        progress_callback_wrapper(100)
        print("\n✅ Point cloud built successfully.")


        # BACKEND_URL 가져오기
        backend_url_ortho = os.getenv("BACKEND_URL_ORTHO","http:/localhost:3033")
        # API 호출 추가
        api_url = f"{backend_url_ortho}/tasks/{reai_task_id}/point_cloud"
        response = requests.get(api_url)

        if response.status_code == 200:
            progress_callback_wrapper(100)        
            print("API call successful")
        else:
            change_task_status_in_ortho(run_id,"Fail")
            progress_callback_wrapper(1000)
            print("API call failed with status code:", response.status_code)
    except Exception as e:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Point cloud generation failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e
    


def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_depth_maps 함수 실행
    build_point_cloud(args.output_path, args.run_id, args.reai_task_id)

if __name__ == "__main__":
    main()