
import Metashape
import os
from common_args import parse_arguments, print_debug_info
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho



def build_dem(output_path, run_id, input_epsg="4326"):
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
    proj = Metashape.OrthoProjection()
    proj.crs = Metashape.CoordinateSystem(f"EPSG::{input_epsg}")
    
    # --- Step 5: Build DEM ---
    try:
        print("🛠 Building DEM...")
        task_name = "Build DEM"
        chunk = doc.chunk
        chunk.buildDem(
            source_data=Metashape.DataSource.DepthMapsData,
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')

        # DEM export (주석 처리 - 저장공간 절약을 위해 비활성화)
        # compression = Metashape.ImageCompression()
        # compression.tiff_big = True
        # compression.tiff_overviews = True
        # compression.tiff_tiled = True
        # chunk.exportRaster(
        #     path=os.path.join(output_path, "dem.tif"),
        #     source_data=Metashape.DataSource.ElevationData,
        #     projection=proj,
        #     image_compression=compression
        # )

        # DEM 결과 요약
        if chunk.elevation:
            dem_res = chunk.elevation.resolution
            print(f"📊 DEM resolution: {dem_res:.4f}m")

        progress_callback_wrapper(99.9)
        print("✅ DEM built successfully.")
    except Exception as e:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        print(f"❌ DEM generation failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e
    

## 실행 함수
def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_dem 함수 실행
    build_dem( args.output_path, args.run_id, args.input_epsg)

if __name__ == "__main__":
    main()