import numpy as np
from common_args import parse_arguments, print_debug_info
import os, csv
import math
import Metashape
import requests
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho

def export_align_photos(output_path, run_id):

    def progress_callback_wrapper(value):
        progress_callback(value, "Align Photos", output_path)

    def export_reference_as_epsg4326(chunk, output_path):

        # 원본 좌표계 (현재 chunk.crs)
        src_crs = chunk.crs
        # 타겟 좌표계: WGS84 (EPSG:4326)
        dst_crs = Metashape.CoordinateSystem("EPSG::4326")

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f, delimiter='\t')  # 탭 구분자 사용
            # writer.writerow(["n", "x", "y", "z", "a", "b", "c"])  # nxyzabc 포맷

            for camera in chunk.cameras:
                if not camera.reference.location:
                    continue

                # 좌표 변환
                location = camera.reference.location
                transformed = Metashape.CoordinateSystem.transform(location, src_crs, dst_crs)

                label = camera.label

                # orientation (a, b, c) → yaw/pitch/roll (선택 사항, 없으면 0으로 처리)
                yaw = camera.reference.rotation[0] if camera.reference.rotation else 0
                pitch = camera.reference.rotation[1] if camera.reference.rotation else -90
                roll = camera.reference.rotation[2] if camera.reference.rotation else 0

                if chunk.euler_angles == Metashape.EulerAnglesOPK:                  
                    if camera.reference.rotation:
                        opk = camera.reference.rotation  # OPK: Omega, Phi, Kappa
                        # OPK를 회전 행렬로 변환
                        R = Metashape.utils.opk2mat(opk)
                        # 회전 행렬을 Yaw, Pitch, Roll로 변환
                        ypr = Metashape.utils.mat2ypr(R)
                        yaw, pitch, roll = ypr
                    else:
                            print(f"{camera.label}: 회전 정보 없음")
                else:
                    print("현재 chunk의 euler_angles 설정이 OPK가 아닙니다.")
                print(f"{camera.label}: Yaw={yaw:.3f}°, Pitch={pitch:.3f}°, Roll={roll:.3f}°")

                writer.writerow([label, f"{transformed.x:.7f}", f"{transformed.y:.7f}", f"{transformed.z:.7f}", f"{yaw:.4f}", f"{pitch:.4f}", f"{roll:.4f}"])

        print(f"✅ reference.txt saved with EPSG:4326 at {output_path}")

    doc = Metashape.Document()
    doc.open(output_path + '/project.psx')
    chunk = doc.chunk
    chunk.exportReference(path=os.path.join(output_path, "reference2.txt"),format=Metashape.ReferenceFormatCSV, columns="nxyzabc")
    export_reference_as_epsg4326(chunk, os.path.join(output_path, "reference.txt"))
    
    

    # BACKEND_URL 가져오기
    backend_url_ortho = os.getenv("BACKEND_URL_ORTHO","http://localhost:3033")
    # API 호출 추가
    api_url = f"{backend_url_ortho}/tasks/czml"
    payload = {
        "output_path": output_path
    }
    response = requests.post(api_url, json=payload)

    if response.status_code == 201:
        progress_callback_wrapper(100)        
        print("API call successful")
    else:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        print("API call failed with status code:", response.status_code)

def main():
    activate_metashape_license()
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_dem 함수 실행
    export_align_photos(args.output_path, args.run_id)

if __name__ == "__main__":
    main()