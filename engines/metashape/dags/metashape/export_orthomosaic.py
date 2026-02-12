import Metashape
import os
import shutil
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho


def export_orthomosaic(output_path, run_id, output_tiff_name, reai_task_id, input_epsg="4326"):
    """
    정사모자이크를 TIFF 파일로 내보냅니다.
    COG 변환은 convert_cog.py에서 수행합니다.
    """
    def progress_callback_wrapper(value):
        progress_callback(value, "Export Raster", output_path)

    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    chunk = doc.chunk

    try:
        # 출력 좌표계
        proj = Metashape.OrthoProjection()
        proj.crs = chunk.crs
        print(f"ℹ️ 출력 좌표계: {chunk.crs}")

        # 압축 설정
        compression = Metashape.ImageCompression()
        compression.tiff_big = True
        compression.tiff_overviews = True
        compression.tiff_tiled = True

        # TIFF 내보내기
        result_path = os.path.join(output_path, "result.tif")
        print("🛠 Exporting orthomosaic to TIFF...")
        chunk.exportRaster(
            path=result_path,
            source_data=Metashape.DataSource.OrthomosaicData,
            projection=proj,
            image_compression=compression
        )
        print(f"✅ Orthomosaic exported to {result_path}")

        # GSD 기반 파일 복사 (옵션)
        if os.getenv("EXPORT_GSD_COPY", "false").lower() in {"1", "true", "yes"}:
            gsd_m = chunk.orthomosaic.resolution
            gsd_cm = round(gsd_m * 100, 2)
            gsd_cm_str = f"{gsd_cm:.2f}".replace('.', '_')
            link_name = f"{output_tiff_name}_{gsd_cm_str}cm.tif"

            src = result_path
            uploads_base = output_path.replace('.outputs/true-ortho', '.uploads/data')
            uploads_base = os.path.dirname(uploads_base)
            dst = os.path.join(uploads_base, link_name)
            shutil.copy2(src, dst)
            print(f"✅ 파일 복사됨: {dst} ← {src}")

        progress_callback_wrapper(100)

    except Exception as e:
        change_task_status_in_ortho(run_id, "Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Orthomosaic export failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e


def main():
    args, input_images = parse_arguments()
    print_debug_info(args, input_images)
    export_orthomosaic(args.output_path, args.run_id, args.output_tiff_name, args.reai_task_id, args.input_epsg)

if __name__ == "__main__":
    main()
