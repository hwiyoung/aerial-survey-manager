import Metashape
import os
import re
from common_args import parse_arguments, print_debug_info
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho


def align_photos(input_images, image_folder, output_path, run_id, process_mode="Normal", input_epsg="4326", reference_path=None):
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
    def _build_image_maps(images):
        file_names = [os.path.basename(p) for p in images]
        name_map = {}
        stem_map = {}
        for name in file_names:
            lower = name.lower()
            if lower not in name_map:
                name_map[lower] = name
            stem = os.path.splitext(lower)[0]
            if stem not in stem_map:
                stem_map[stem] = name
        return name_map, stem_map

    def _detect_delimiter(sample_line, path):
        if path.lower().endswith(".csv"):
            return ","
        if "," in sample_line and sample_line.count(",") >= sample_line.count(" "):
            return ","
        return None  # whitespace

    def _score_reference_file(path, name_map, stem_map):
        score = 0
        delimiter = None
        lines_checked = 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    raw = line.strip()
                    if not raw or raw.startswith("#"):
                        continue
                    if delimiter is None:
                        delimiter = _detect_delimiter(raw, path)
                    parts = raw.split(",") if delimiter == "," else raw.split()
                    if len(parts) < 7:
                        continue
                    token = os.path.basename(parts[0].strip())
                    lower = token.lower()
                    if lower in name_map:
                        score += 1
                    else:
                        stem = os.path.splitext(lower)[0]
                        if stem in stem_map:
                            score += 1
                    lines_checked += 1
                    if lines_checked >= 200:
                        break
        except Exception:
            return 0, None
        return score, delimiter

    def _select_reference_file(folders, name_map, stem_map, explicit_path=None):
        candidates = []
        if explicit_path:
            if os.path.isdir(explicit_path):
                for entry in os.scandir(explicit_path):
                    if not entry.is_file():
                        continue
                    lower = entry.name.lower()
                    if lower.endswith(".txt") or lower.endswith(".csv"):
                        candidates.append(entry.path)
            elif os.path.isfile(explicit_path):
                candidates.append(explicit_path)

        for folder in folders:
            if not folder or not os.path.isdir(folder):
                continue
            meta = os.path.join(folder, "metadata.txt")
            if os.path.isfile(meta):
                candidates.append(meta)
            for entry in os.scandir(folder):
                if not entry.is_file():
                    continue
                if entry.path == meta:
                    continue
                lower = entry.name.lower()
                if lower.endswith(".txt") or lower.endswith(".csv"):
                    candidates.append(entry.path)

        best_path = None
        best_score = 0
        best_delim = None
        for path in candidates:
            score, delim = _score_reference_file(path, name_map, stem_map)
            if score > best_score:
                best_score = score
                best_path = path
                best_delim = delim
        return best_path, best_delim, best_score

    def _looks_like_header(parts):
        if not parts:
            return True
        token = parts[0].strip().lower()
        if token in {"image", "image_name", "filename", "file", "photo", "id"}:
            return True
        try:
            float(parts[1])
            float(parts[2])
            float(parts[3])
        except Exception:
            return True
        return False

    def _normalize_reference_file(src_path, delimiter, name_map, stem_map, out_dir):
        out_path = os.path.join(out_dir, "reference_normalized.txt")
        matched = 0
        skipped = 0
        with open(src_path, "r", encoding="utf-8", errors="ignore") as f, open(out_path, "w", encoding="utf-8") as out:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                parts = raw.split(",") if delimiter == "," else raw.split()
                if len(parts) < 7:
                    skipped += 1
                    continue
                if _looks_like_header(parts):
                    continue
                token = os.path.basename(parts[0].strip())
                lower = token.lower()
                actual = name_map.get(lower)
                if not actual:
                    stem = os.path.splitext(lower)[0]
                    actual = stem_map.get(stem)
                if not actual:
                    skipped += 1
                    continue
                try:
                    float(parts[1])
                    float(parts[2])
                    float(parts[3])
                except Exception:
                    skipped += 1
                    continue
                out.write(f"{actual} {parts[1]} {parts[2]} {parts[3]} {parts[4]} {parts[5]} {parts[6]}\n")
                matched += 1
        if matched == 0:
            return None, matched, skipped
        return out_path, matched, skipped

    def _extract_epsg_from_reference(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(20):
                    line = f.readline()
                    if not line:
                        break
                    text = line.strip()
                    if not text:
                        continue
                    match = re.search(r"EPSG[:\s]*([0-9]+)", text.upper())
                    if match:
                        return match.group(1)
        except Exception:
            return None
        return None

    # EO Reference 파일 탐색 및 적용
    name_map, stem_map = _build_image_maps(input_images)
    env_reference = os.getenv("EO_REFERENCE_PATH") or os.getenv("METASHAPE_REFERENCE_PATH")
    search_dirs = [image_folder]
    try:
        image_parent = os.path.dirname(image_folder)
        if image_parent and image_parent != image_folder:
            search_dirs.append(image_parent)
    except Exception:
        pass
    if output_path:
        search_dirs.append(output_path)

    geom_reference, geom_delim, geom_score = _select_reference_file(
        search_dirs, name_map, stem_map, explicit_path=(reference_path or env_reference)
    )
    reference_epsg = None
    if geom_reference and geom_score > 0:
        reference_epsg = _extract_epsg_from_reference(geom_reference)
        if reference_epsg and reference_epsg != str(input_epsg):
            chunk.crs = Metashape.CoordinateSystem(f"EPSG::{reference_epsg}")
        normalized_path, matched_count, _ = _normalize_reference_file(
            geom_reference, geom_delim, name_map, stem_map, output_path
        )
        if normalized_path:
            print(f"📋 EO reference 적용: {matched_count}개 매칭 (EPSG:{reference_epsg or input_epsg})")
            chunk.importReference(
                path=normalized_path,
                format=Metashape.ReferenceFormatCSV,
                delimiter=" ",
                columns="nxyzabc"
            )
        else:
            print("⚠️ EO reference 매칭 실패")
    else:
        print("ℹ️ EO reference 파일 없음 (EXIF GPS 사용)")
        

    
    
    # 카메라 회전 정보 사용 설정
    for camera in chunk.cameras:
        if camera.reference and camera.reference.rotation is not None:
            camera.reference.rotation_enabled = True

    # EO 적용 결과를 즉시 디스크에 반영 (정렬 전에 .psx에서 검증 가능)
    doc.save()

    # --- Step 3: Align Photos ---
    try:
        print("🛠 Aligning photos...")
        task_name = "Align Photos"
        chunk.matchPhotos(
            downscale=mp_downscale,
            keypoint_limit=40000,
            tiepoint_limit=4000,
            generic_preselection=True,
            reference_preselection=True,
            progress=progress_callback_wrapper
        )
        chunk.alignCameras(adaptive_fitting=True)
        doc.save(output_path + '/project.psx')

        # Alignment 결과 로그 출력
        total_cameras = len(chunk.cameras)
        aligned_cameras = len([c for c in chunk.cameras if c.transform])
        unaligned_cameras = total_cameras - aligned_cameras
        alignment_ratio = aligned_cameras / total_cameras * 100 if total_cameras > 0 else 0

        print(f"\n📊 Alignment 결과: {aligned_cameras}/{total_cameras} 카메라 정렬됨 ({alignment_ratio:.1f}%)")

        if unaligned_cameras > 0:
            unaligned_labels = [c.label for c in chunk.cameras if not c.transform]
            print(f"⚠️ 정렬 실패 카메라 ({unaligned_cameras}개):")
            for label in unaligned_labels[:20]:
                print(f"   - {label}")
            if unaligned_cameras > 20:
                print(f"   ... 외 {unaligned_cameras - 20}개")

            # --- Step 3-1: 미정합 카메라 재정합 (1회 시도) ---
            print(f"\n🔄 미정합 카메라 {unaligned_cameras}장 재정합 시도...")
            unaligned_cams = [c for c in chunk.cameras if c.transform is None]

            chunk.matchPhotos(
                downscale=mp_downscale,
                keypoint_limit=40000,
                tiepoint_limit=4000,
                generic_preselection=True,
                reference_preselection=True,
                reset_matches=False,
            )
            chunk.alignCameras(
                cameras=unaligned_cams,
                min_image=2,
                adaptive_fitting=True,
                reset_alignment=False,
            )
            doc.save(output_path + '/project.psx')

            still_unaligned = len([c for c in chunk.cameras if c.transform is None])
            newly_aligned = unaligned_cameras - still_unaligned
            print(f"   → 새로 정합: {newly_aligned}장 | 여전히 실패: {still_unaligned}장")

            if still_unaligned > 0:
                still_labels = [c.label for c in chunk.cameras if c.transform is None]
                print(f"⚠️ 최종 미정합 카메라 ({still_unaligned}개):")
                for label in still_labels[:20]:
                    print(f"   - {label}")
                if still_unaligned > 20:
                    print(f"   ... 외 {still_unaligned - 20}개")
                print("   → 오버랩/텍스처 부족 등 근본적 문제일 수 있습니다.")

            # 최종 정합률 갱신
            aligned_cameras = total_cameras - still_unaligned
            alignment_ratio = aligned_cameras / total_cameras * 100 if total_cameras > 0 else 0
            print(f"📊 최종 Alignment: {aligned_cameras}/{total_cameras} ({alignment_ratio:.1f}%)")

        progress_callback_wrapper(99.9)
        print("✅ Cameras aligned successfully.")
    except Exception as e:
        change_task_status_in_ortho(run_id, "Fail")
        progress_callback_wrapper(1000)
        print(f"❌ Camera alignment failed: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e


# usage
def main():
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # align_photos 함수 실행
    align_photos(
        input_images,
        args.image_folder,
        args.output_path,
        args.run_id,
        args.process_mode,
        args.input_epsg,
        args.reference_path
    )

if __name__ == "__main__":
    main()
