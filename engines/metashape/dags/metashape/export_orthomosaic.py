from common_args import parse_arguments, print_debug_info
from osgeo import gdal
import os
import Metashape
from common_utils import progress_callback, check_success, change_task_status_in_ortho, notify_result_in_ortho
import requests
import shutil

def export_orthomosaic(output_path, run_id,output_tiff_name,reai_task_id, input_epsg="4326"):

    def progress_callback_wrapper(value):
        progress_callback(value, "Build Orthomosaic", output_path)


    input_raster_dem = os.path.join(output_path, "result.tif")
    output_cog = os.path.join(output_path, "result_cog.tif")

    try:
        thumbnail_name = "result.tif".replace('.tif', '_thumbnail.png')
        thumbnail_path = os.path.join(output_path, 'outputs', thumbnail_name)
        ds = gdal.Open(input_raster_dem)
        if ds is None:
            raise FileNotFoundError(f"파일을 열 수 없습니다: {input_raster_dem}")

        # 썸네일 크기 설정
        # thumbnail_size = (256, 256)

        # 썸네일 생성
        gdal.Translate(
            thumbnail_path,
            ds,
            format='PNG',
            width=256,
            height=256
        )

        ds = None
    except Exception as e:
        print(f"썸네일 생성 중 오류 발생: {e}")
        thumbnail_path = None


    print("Running gdal_translate...")
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


    # 3. 심볼릭 링크 생성
    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    chunk = doc.chunk
     
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

    # try:
    #     if os.path.islink(dst) or os.path.exists(dst):
    #         os.remove(dst)
    #     os.link(src, dst)
    #     print(f"✅ 심볼릭 링크 생성됨: {dst} → {src}")
    # except OSError as e:
    #     print(f"❌ 심볼릭 링크 생성 실패: {e}")


    # 3-1. 작업 상태 알림
    if check_success(output_path):
        change_task_status_in_ortho(run_id,"Success")
        notify_result_in_ortho(reai_task_id,"정사영상 생성에 성공했습니다.")
    else:
        change_task_status_in_ortho(run_id,"Fail")
        notify_result_in_ortho(reai_task_id,"정상영상 생성에 실패했습니다.")

    # 4. Resource DB에 저장
    # backend_url_cd = os.getenv("BACKEND_URL_CD","http://localhost:3034")
    # API 호출 추가
    # api_url = f"{backend_url_cd}/resources"

    # drone_makes = {"DJI", "Parrot", "Yuneec", "Autel Robotics", "senseFly"}
    # # 첫 번째 카메라의 'Make' 정보 확인
    # first_camera = chunk.cameras[0]
    # make = first_camera.photo.meta["Exif/Make"].strip() if "Exif/Make" in first_camera.photo.meta else ""

    # 드론 제조사에 해당하지 않으면 EulerAnglesOPK 설정
    # if not make or make not in drone_makes:
    #     platform = "항공"
    # else:
    #     platform = "드론"

    # payload 준비
    # payload = {
    #     # todo 드론인지 항공인지 구분 필요
    #     "file_name": "orthophoto.tif",
    #     "path": f".outputs/true-ortho/{reai_task_id}",
    #     "type": "image",
    #     "belongs_to": "true-ortho",
    #     "display_name": link_name,
    #     "crs": f"{input_epsg}",
    #     "platform": platform,
    #     "full_path": f".outputs/true-ortho/{reai_task_id}",
    # }
    # response = requests.post(api_url, json=payload)



    # if response.status_code == 201:
    #     progress_callback_wrapper(100)        
    #     print("API call successful")
    # else:
    #     print(f"API call failed with status code {response.status_code}")
    #     print(f"Response: {response.text}")



    progress_callback_wrapper(100)  
    # 5. 프로젝트 파일 삭제
    folder_path = os.path.join(output_path,"project.files")
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path) 
        print(f"폴더 '{folder_path}' 및 내부 모든 파일/폴더가 삭제되었습니다.")
    else:
        print(f"폴더 '{folder_path}'가 존재하지 않습니다.")
    

def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_dem 함수 실행
    export_orthomosaic( args.output_path, args.run_id, args.output_tiff_name, args.reai_task_id,args.input_epsg)

if __name__ == "__main__":
    main()