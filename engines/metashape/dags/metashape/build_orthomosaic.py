import Metashape
import os
from common_args import parse_arguments, print_debug_info
from common_utils import progress_callback, change_task_status_in_ortho, save_result_gsd


def build_orthomosaic(output_path, run_id, input_epsg="4326"):
    """
    정사모자이크를 생성합니다.
    TIFF 내보내기는 export_orthomosaic.py에서, COG 변환은 convert_cog.py에서 수행합니다.
    """
    def progress_callback_wrapper(value):
        progress_callback(value, task_name, output_path)

    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    chunk = doc.chunk

    try:
        print("🛠 Building orthomosaic...")
        task_name = "Build Orthomosaic"
        chunk.buildOrthomosaic(
            surface_data=Metashape.DataSource.ElevationData,
            refine_seamlines=True,
            progress=progress_callback_wrapper
        )
        doc.save(output_path + '/project.psx')

        # Orthomosaic 결과 요약 및 GSD 저장
        if chunk.orthomosaic:
            ortho_res = chunk.orthomosaic.resolution
            print(f"📊 Orthomosaic GSD: {ortho_res*100:.2f}cm")
            save_result_gsd(output_path, ortho_res)

        progress_callback_wrapper(99.9)
        print("✅ Orthomosaic generated successfully.")

    except Exception as e:
        change_task_status_in_ortho(run_id, "Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Orthomosaic generation failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e



def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    build_orthomosaic(args.output_path, args.run_id, args.input_epsg)

if __name__ == "__main__":
    main()