import Metashape
import os
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho


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
    proj = Metashape.OrthoProjection()
    proj.crs = Metashape.CoordinateSystem(f"EPSG::{input_epsg}")
    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    
        # --- Step 6: Build Orthomosaic & Refine Seamlines ---
    try:
        print("🛠 Building orthomosaic...")
        key = "main/enable_refine_roof_edges"
        Metashape.app.settings.setValue(key, True)
        task_name = "Build Orthomosaic"
        chunk = doc.chunk
        chunk.buildOrthomosaic(
            surface_data=Metashape.DataSource.ElevationData,
            refine_seamlines = False,
            refine_roof_edges = True,
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')
        
        compression = Metashape.ImageCompression()
        compression.tiff_big = True
        compression.tiff_overviews = True
        compression.tiff_tiled = True

        

        chunk.exportRaster(path=os.path.join(output_path, "result.tif"),source_data=Metashape.DataSource.OrthomosaicData, projection=proj,image_compression=compression)


        progress_callback_wrapper(99.9)
        print("\n✅ Orthomosaic generated successfully.")
    
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