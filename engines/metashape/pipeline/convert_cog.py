from common_args import parse_arguments, print_debug_info
from osgeo import gdal
import os
import time
import shutil
import Metashape
from common_utils import progress_callback, check_success, change_task_status_in_ortho, notify_result_in_ortho


def convert_cog(output_path, run_id, output_tiff_name, reai_task_id, input_epsg="4326"):
    """
    result.tif를 Cloud Optimized GeoTIFF (COG)로 변환하고,
    처리 성공 여부 확인 및 프로젝트 파일을 정리합니다.
    """
    def progress_callback_wrapper(value):
        progress_callback(value, "Convert COG", output_path)

    input_raster = os.path.join(output_path, "result.tif")
    output_cog = os.path.join(output_path, "result_cog.tif")

    # COG 변환
    print("🛠 Converting to Cloud Optimized GeoTIFF (COG)...")
    translate_options = gdal.TranslateOptions(
        format="COG",
        creationOptions=[
            "BLOCKSIZE=1024",
            "COMPRESS=LZW",
            "RESAMPLING=LANCZOS",
            "PREDICTOR=2",
            "BIGTIFF=YES"
        ]
    )
    gdal.Translate(output_cog, input_raster, options=translate_options)
    print(f"✅ COG saved to {output_cog}")

    # 진행률 100% 설정 (check_success에서 확인하므로 먼저 설정)
    progress_callback_wrapper(100)

    # 작업 상태 알림
    if check_success(output_path):
        change_task_status_in_ortho(run_id, "Success")
        notify_result_in_ortho(reai_task_id, "정사영상 생성에 성공했습니다.")
    else:
        change_task_status_in_ortho(run_id, "Fail")
        notify_result_in_ortho(reai_task_id, "정사영상 생성에 실패했습니다.")

    # 프로젝트 파일 조건부 삭제
    folder_path = os.path.join(output_path, "project.files")
    if os.path.exists(folder_path):
        doc = Metashape.Document()
        doc.open(output_path + '/project.psx')
        chunk = doc.chunk

        total_cameras = len(chunk.cameras)
        aligned_cameras = len([c for c in chunk.cameras if c.transform])
        alignment_ratio = aligned_cameras / total_cameras if total_cameras > 0 else 0

        should_delete = check_success(output_path) and alignment_ratio >= 0.80

        if should_delete:
            doc.save()
            doc = None
            chunk = None
            time.sleep(1)
            shutil.rmtree(folder_path, ignore_errors=True)
            print(f"✅ 프로젝트 파일 삭제됨: {folder_path}")
        else:
            print(f"⚠️ 프로젝트 파일 보존됨 (디버깅용): {folder_path}")
            print(f"   - Alignment 비율: {aligned_cameras}/{total_cameras} ({alignment_ratio*100:.1f}%)")
    else:
        print(f"ℹ️ 프로젝트 파일 없음: {folder_path}")


def main():
    args, input_images = parse_arguments()
    print_debug_info(args, input_images)
    convert_cog(args.output_path, args.run_id, args.output_tiff_name, args.reai_task_id, args.input_epsg)

if __name__ == "__main__":
    main()
