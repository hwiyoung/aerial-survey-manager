import Metashape
from common_args import parse_arguments, print_debug_info
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho


def build_depth_maps( output_path, run_id, process_mode="Normal"):
    """
    Generate an orthophoto and other outputs with progress tracking and refined seamlines.
    
    Parameters:
      input_images (list): List of image file paths.
      output_path (str): Base path to save the generated outputs.
      process_mode (str): "preview", "normal", or "high"
    """
    # 설정값: 각 모드에 따라 matchPhotos와 buildDepthMaps의 downscale 값을 다르게 지정.
    if process_mode == "Preview":
        dm_downscale = 8      # Build DepthMaps: Low quality
    elif process_mode == "Normal":
        dm_downscale = 4      # Build DepthMaps: Medium quality
    elif process_mode == "High":
        dm_downscale = 1      # Build DepthMaps: UltraHigh
    else:
        print(f"Invalid process mode: {process_mode}. Defaulting to normal.")
        dm_downscale = 4

    
    def progress_callback_wrapper(value):
        progress_callback(value, task_name, output_path)
    
    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    try:
        print("🛠 Building depth maps...")
        task_name = "Build Depth Maps"
        chunk = doc.chunk
        chunk.buildDepthMaps(
            downscale=dm_downscale,
            filter_mode=Metashape.FilterMode.MildFiltering,
            subdivide_task=True,
            workitem_size_cameras=20,
            max_workgroup_size=100,
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')
        progress_callback_wrapper(100)
        print("\n✅ Depth maps built successfully.")
    except Exception as e:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Depth map generation failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e
    


def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_depth_maps 함수 실행
    build_depth_maps( args.output_path, args.run_id, args.process_mode)

if __name__ == "__main__":
    main()