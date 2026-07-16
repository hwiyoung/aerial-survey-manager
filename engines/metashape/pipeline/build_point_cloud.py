import Metashape
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho
import os
import requests


def _normalize_epsg(epsg_value):
    if not epsg_value:
        return None
    value = str(epsg_value).strip()
    if value.upper().startswith("EPSG::"):
        value = value.split("::", 1)[1]
    elif value.upper().startswith("EPSG:"):
        value = value.split(":", 1)[1]
    return value if value else None

def build_point_cloud(output_path, run_id, reai_task_id, output_epsg=None):
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
        print("🛠 Building point cloud...")
        task_name = "Build Point Cloud"
        chunk = doc.chunk
        chunk.buildPointCloud(
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')

        # Point Cloud 결과 요약
        if chunk.point_cloud:
            print("📊 Point cloud generated successfully")

        export_epsg = _normalize_epsg(output_epsg)
        print(f"ℹ️ Point cloud export target EPSG: {export_epsg}")
        export_crs = Metashape.CoordinateSystem(f"EPSG::{export_epsg}") if export_epsg else None
        export_ok = False
        try:
            if export_crs:
                chunk.exportPointCloud(
                    path=os.path.join(output_path, "point_cloud.zip"),
                    source_data=Metashape.DataSource.PointCloudData,
                    format=Metashape.PointCloudFormat.PointCloudFormatCesium,
                    crs=export_crs
                )
                export_ok = True
            else:
                raise RuntimeError("No export CRS provided")
        except Exception:
            print("⚠️ Point cloud export with output CRS failed. Retrying without CRS transformation.")
            try:
                # Export without CRS to avoid datum transformation failures
                chunk.exportPointCloud(
                    path=os.path.join(output_path, "point_cloud.zip"),
                    source_data=Metashape.DataSource.PointCloudData,
                    format=Metashape.PointCloudFormat.PointCloudFormatCesium
                )
                export_ok = True
            except Exception as export_error:
                print(f"⚠️ Point cloud export skipped due to error: {export_error}")
        if not export_ok:
            print("⚠️ Point cloud export skipped.")
        progress_callback_wrapper(100)
        print("✅ Point cloud built successfully.")

        # API 콜백 (실패해도 무시)
        try:
            backend_url_ortho = os.getenv("BACKEND_URL_ORTHO", "http://api:8000/api/v1/processing")
            api_url = f"{backend_url_ortho}/tasks/{reai_task_id}/point_cloud"
            requests.get(api_url, timeout=5)
        except Exception:
            pass  # Non-critical
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
    build_point_cloud(args.output_path, args.run_id, args.reai_task_id, args.output_epsg)

if __name__ == "__main__":
    main()
