import Metashape
import os
from common_args import parse_arguments, print_debug_info
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho


def align_photos(input_images, image_folder, output_path, run_id, process_mode="Normal", input_epsg="4326"):
    """
    Generate an orthophoto and other outputs with progress tracking and refined seamlines.
    
    Parameters:
      input_images (list): List of image file paths.
      output_path (str): Base path to save the generated outputs.
      process_mode (str): "preview", "normal", or "high"
    """
    def progress_callback_wrapper(value):
        progress_callback(value, task_name, output_path)
    
    # 설정값: 각 모드에 따라 matchPhotos와 buildDepthMaps의 downscale 값을 다르게 지정.
    if process_mode == "Preview":
        mp_downscale = 4      # Align Photos: Low (4: Low, 8: Lowest)
    elif process_mode == "Normal":
        mp_downscale = 2      # Align Photos: Medium
    elif process_mode == "High":
        mp_downscale = 1      # Align Photos: High
    else:
        print(f"Invalid process mode: {process_mode}. Defaulting to normal.")
        mp_downscale = 2
    
    os.makedirs(output_path, exist_ok=True)


    # Step 1: Create a new project and add a chunk
    doc = Metashape.Document()
    doc.save(output_path + '/project.psx')
    chunk = doc.addChunk()

    chunk.crs = Metashape.CoordinateSystem(f"EPSG::{input_epsg}")
    print(f"ℹ️ Coordinate system set to EPSG::{input_epsg}")

    change_task_status_in_ortho(run_id,"Running")

    # Step 2: Add photos
    try:
        chunk.addPhotos(input_images,load_xmp_accuracy = True)
        doc.save()
        print(f"✅ Added {len(input_images)} photos to the chunk.")
    except Exception as e:
        print(f"❌ Failed to add photos: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e

    drone_makes = {"DJI", "Parrot", "Yuneec", "Autel Robotics", "senseFly"}
    # 첫 번째 카메라의 'Make' 정보 확인
    first_camera = chunk.cameras[0]
    make = first_camera.photo.meta["Exif/Make"].strip() if "Exif/Make" in first_camera.photo.meta else ""

    # 드론 제조사에 해당하지 않으면 EulerAnglesOPK 설정
    if not make or make not in drone_makes:
        # chunk.crs = Metashape.CoordinateSystem(f"EPSG::5186")
        chunk.euler_angles = Metashape.EulerAnglesOPK
        chunk.camera_location_accuracy = Metashape.Vector([0.00001, 0.00001, 0.00001])
        chunk.camera_rotation_accuracy = Metashape.Vector([0.00001, 0.00001, 0.00001])
        print("ℹ️ 'Make' 정보가 드론 제조사에 해당하지 않아 EulerAnglesOPK로 설정되었습니다.")


    # Step 2-1 : importReference
    geom_reference = os.path.join(image_folder,"metadata.txt")
    if os.path.isfile(geom_reference):
        chunk.importReference(path=geom_reference,format=Metashape.ReferenceFormatCSV, delimiter=" ",columns="nxyzabc")
        

    
    
    # 카메라 회전 정보 사용 설정
    for camera in chunk.cameras:
        if camera.reference and camera.reference.rotation is not None:
            camera.reference.rotation_enabled = True
        

    # sensor = chunk.sensors[0]
    
    # calib = Metashape.Calibration()
    # calib.width = 11310
    # calib.height = 17310
    # calib.f = 16750                # focal length in pixels
    # calib.cx = 11310 / 2           # 중심점 (픽셀)
    # calib.cy = 17310 / 2
    
    # sensor.user_calib = calib
    # sensor.calibration = calib
    # sensor.fixed = True

    # --- Step 3: Align Photos ---
    try:
        print("🛠 Aligning photos...")
        task_name = "Align Photos"
        chunk.matchPhotos(
            downscale=mp_downscale, 
            keypoint_limit = 40000, 
            tiepoint_limit = 4000, 
            generic_preselection = True, 
            reference_preselection = True, 
            progress=progress_callback_wrapper
        )
        # doc.save()
        chunk.alignCameras(adaptive_fitting=True)
        doc.save(output_path + '/project.psx')
         
        progress_callback_wrapper(99.9)
        print("\n✅ Cameras aligned successfully.")
    except Exception as e:
        change_task_status_in_ortho(run_id,"Fail")
        progress_callback_wrapper(1000)
        if Metashape.app.activated:
            print("✅ Metashape is activated and fully functional.")
        else:
            print("❌ Metashape is running in Demo mode.")
        print(f"❌ Camera alignment failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e


# usage
def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # align_photos 함수 실행
    align_photos(input_images, args.image_folder, args.output_path, args.run_id, args.process_mode, args.input_epsg)

if __name__ == "__main__":
    main()