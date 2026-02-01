from common_args import parse_arguments, print_debug_info
from osgeo import gdal
import os
import Metashape
from common_utils import progress_callback, check_success, change_task_status_in_ortho, notify_result_in_ortho
import shutil

def export_orthomosaic(output_path, run_id, output_tiff_name, reai_task_id, input_epsg="4326"):

    def progress_callback_wrapper(value):
        progress_callback(value, "Build Orthomosaic", output_path)

    input_raster_dem = os.path.join(output_path, "result.tif")
    output_cog = os.path.join(output_path, "result_cog.tif")

    print("🛠 Converting to Cloud Optimized GeoTIFF (COG)...")
    translate_options = gdal.TranslateOptions(
        format="COG",
        creationOptions=[
            "BLOCKSIZE=256",
            "COMPRESS=LZW",
            "RESAMPLING=LANCZOS",
            "PREDICTOR=2",
            "BIGTIFF=YES"
        ]
    )
    gdal.Translate(output_cog, input_raster_dem, options=translate_options)
    
    progress_callback_wrapper(100)
    print(f"Cloud Optimized GeoTIFF saved to {output_cog}")


    # 3. 심볼릭 링크 생성 (필요 시에만)
    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    chunk = doc.chunk
     
    if os.getenv("EXPORT_GSD_COPY", "false").lower() in {"1", "true", "yes"}:
        gsd_m = chunk.orthomosaic.resolution
        gsd_cm = round(gsd_m * 100, 2)
        gsd_cm_str = f"{gsd_cm:.2f}".replace('.', '_')
        link_name = f"{output_tiff_name}_{gsd_cm_str}cm.tif"

        src = input_raster_dem
        uploads_base = output_path.replace('.outputs/true-ortho', '.uploads/data')
        uploads_base = os.path.dirname(uploads_base)  # 아이디값 폴더 제거
        dst = os.path.join(uploads_base, link_name)
        shutil.copy2(src, dst)
        print(f"✅ 파일 복사됨: {dst} ← {src}")

    # 작업 상태 알림
    if check_success(output_path):
        change_task_status_in_ortho(run_id, "Success")
        notify_result_in_ortho(reai_task_id, "정사영상 생성에 성공했습니다.")
    else:
        change_task_status_in_ortho(run_id, "Fail")
        notify_result_in_ortho(reai_task_id, "정사영상 생성에 실패했습니다.")

    progress_callback_wrapper(100)

    # 5. 프로젝트 파일 조건부 삭제 (문제 발생 시 디버깅을 위해 보존)
    folder_path = os.path.join(output_path, "project.files")
    if os.path.exists(folder_path):
        # Alignment 비율 확인
        total_cameras = len(chunk.cameras)
        aligned_cameras = len([c for c in chunk.cameras if c.transform])
        alignment_ratio = aligned_cameras / total_cameras if total_cameras > 0 else 0

        # 95% 이상 정렬되고 처리 성공 시에만 삭제
        should_delete = check_success(output_path) and alignment_ratio >= 0.95

        if should_delete:
            shutil.rmtree(folder_path)
            print(f"✅ 프로젝트 파일 삭제됨: {folder_path}")
        else:
            print(f"⚠️ 프로젝트 파일 보존됨 (디버깅용): {folder_path}")
            print(f"   - Alignment 비율: {aligned_cameras}/{total_cameras} ({alignment_ratio*100:.1f}%)")
    else:
        print(f"ℹ️ 프로젝트 파일 없음: {folder_path}")
    

def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_dem 함수 실행
    export_orthomosaic( args.output_path, args.run_id, args.output_tiff_name, args.reai_task_id,args.input_epsg)

if __name__ == "__main__":
    main()
