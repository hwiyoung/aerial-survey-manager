import Metashape
import os
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho, save_result_gsd


def build_orthomosaic( output_path, run_id, input_epsg="4326", ):
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
    chunk = doc.chunk

    # 출력 좌표계를 프로젝트에 설정된 입력 좌표계와 동일하게 사용
    proj = Metashape.OrthoProjection()
    proj.crs = chunk.crs
    print(f"ℹ️ 출력 좌표계: {chunk.crs} (입력 좌표계와 동일)")
    
    # --- Step 6: Build Orthomosaic & Refine Seamlines ---
    try:
        print("🛠 Building orthomosaic...")
        # key = "main/enable_refine_roof_edges"
        # Metashape.app.settings.setValue(key, True)
        task_name = "Build Orthomosaic"
        chunk.buildOrthomosaic(
            surface_data=Metashape.DataSource.ElevationData,
            refine_seamlines=True,
            # refine_roof_edges=True,
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')
        
        compression = Metashape.ImageCompression()
        compression.tiff_big = True
        compression.tiff_overviews = True
        compression.tiff_tiled = True

        

        chunk.exportRaster(
            path=os.path.join(output_path, "result.tif"),
            source_data=Metashape.DataSource.OrthomosaicData,
            projection=proj,
            image_compression=compression
        )

        # Orthomosaic 결과 요약 및 GSD 저장
        if chunk.orthomosaic:
            ortho_res = chunk.orthomosaic.resolution
            print(f"📊 Orthomosaic GSD: {ortho_res*100:.2f}cm")
            # 결과 GSD를 status.json에 저장 (내보내기 시 기본값으로 사용)
            save_result_gsd(output_path, ortho_res)

        progress_callback_wrapper(99.9)
        print("✅ Orthomosaic generated successfully.")
    
    except Exception as e:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Orthomosaic generation or seamline refinement failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e



def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_orthomosaic 함수 실행
    build_orthomosaic( args.output_path, args.run_id , args.input_epsg,)

if __name__ == "__main__":
    main()