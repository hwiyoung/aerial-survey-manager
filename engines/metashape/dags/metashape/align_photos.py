import Metashape
import os
import re
from common_args import parse_arguments, print_debug_info
from common_utils import activate_metashape_license, progress_callback, change_task_status_in_ortho


def align_photos(
    input_images,
    image_folder,
    output_path,
    run_id,
    process_mode="Normal",
    input_epsg="4326",
    reference_path=None,
    eo_only_align=True,
):
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


    print(
        "ℹ️ Align mode: "
        + ("EO-only (non-EO incremental disabled)" if eo_only_align else "EO core + non-EO incremental")
    )

    # Step 1: EO reference를 먼저 해석해서 기준 블록에 넣을 이미지를 결정합니다.
    # 기본값은 EO 매칭 이미지만 정합하며, legacy 옵션에서만 non-EO 이미지를 no-reset으로 추가합니다.
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

    def _resolve_reference_image_name(parts, name_map, stem_map):
        token = os.path.basename(parts[0].strip())
        lower = token.lower()
        actual = name_map.get(lower)
        if not actual:
            stem = os.path.splitext(lower)[0]
            actual = stem_map.get(stem)
        return actual

    def _is_valid_reference_row(parts):
        if len(parts) < 7:
            return False
        if _looks_like_header(parts):
            return False
        try:
            for value in parts[1:7]:
                float(value)
        except Exception:
            return False
        return True

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
                    if _is_valid_reference_row(parts):
                        actual = _resolve_reference_image_name(parts, name_map, stem_map)
                        if actual:
                            score += 1
                    lines_checked += 1
                    if lines_checked >= 500:
                        break
        except Exception:
            return 0, None
        return score, delimiter

    def _select_reference_file(folders, name_map, stem_map, explicit_path=None):
        candidates = []
        seen = set()

        def _add_candidate(path):
            normalized = os.path.abspath(path)
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(path)

        if explicit_path:
            if os.path.isdir(explicit_path):
                for entry in os.scandir(explicit_path):
                    if not entry.is_file():
                        continue
                    lower = entry.name.lower()
                    if lower.endswith(".txt") or lower.endswith(".csv"):
                        _add_candidate(entry.path)
            elif os.path.isfile(explicit_path):
                _add_candidate(explicit_path)

        for folder in folders:
            if not folder or not os.path.isdir(folder):
                continue
            meta = os.path.join(folder, "metadata.txt")
            if os.path.isfile(meta):
                _add_candidate(meta)
            for entry in os.scandir(folder):
                if not entry.is_file():
                    continue
                if entry.path == meta:
                    continue
                lower = entry.name.lower()
                if lower.endswith(".txt") or lower.endswith(".csv"):
                    _add_candidate(entry.path)

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
        matched_names = set()
        with open(src_path, "r", encoding="utf-8", errors="ignore") as f, open(out_path, "w", encoding="utf-8") as out:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#"):
                    continue
                parts = raw.split(",") if delimiter == "," else raw.split()
                if not _is_valid_reference_row(parts):
                    skipped += 1
                    continue
                actual = _resolve_reference_image_name(parts, name_map, stem_map)
                if not actual:
                    skipped += 1
                    continue
                out.write(f"{actual} {parts[1]} {parts[2]} {parts[3]} {parts[4]} {parts[5]} {parts[6]}\n")
                matched += 1
                matched_names.add(actual.lower())
        if matched == 0:
            return None, matched, skipped, matched_names
        return out_path, matched, skipped, matched_names

    def _split_images_by_reference(images, matched_names):
        matched = []
        unmatched = []
        matched_set = {name.lower() for name in matched_names}
        for path in images:
            name = os.path.basename(path).lower()
            if name in matched_set:
                matched.append(path)
            else:
                unmatched.append(path)
        return matched, unmatched

    def _enable_reference_for_cameras(cameras):
        for camera in cameras:
            if not camera.reference:
                continue
            try:
                camera.reference.location_enabled = True
            except Exception:
                pass
            if camera.reference.rotation is not None:
                try:
                    camera.reference.rotation_enabled = True
                except Exception:
                    pass

    def _get_camera_keys(cameras):
        keys = set()
        for camera in cameras:
            key = getattr(camera, "key", None)
            if key is not None:
                keys.add(key)
        return keys

    def _get_new_cameras_by_key(cameras, existing_keys):
        new_cameras = []
        for camera in cameras:
            key = getattr(camera, "key", None)
            if key is not None and key not in existing_keys:
                new_cameras.append(camera)
        return new_cameras

    def _disable_reference_for_cameras(cameras):
        for camera in cameras:
            if not camera.reference:
                continue
            try:
                camera.reference.location_enabled = False
            except Exception:
                pass
            try:
                camera.reference.rotation_enabled = False
            except Exception:
                pass

    def _print_alignment_summary(cameras, label):
        total = len(cameras)
        aligned = len([c for c in cameras if c.transform])
        unaligned = total - aligned
        ratio = aligned / total * 100 if total > 0 else 0
        print(f"\n📊 {label}: {aligned}/{total} 카메라 정렬됨 ({ratio:.1f}%)")
        if unaligned > 0:
            labels = [c.label for c in cameras if not c.transform]
            print(f"⚠️ {label} 미정합 카메라 ({unaligned}개):")
            for camera_label in labels[:20]:
                print(f"   - {camera_label}")
            if unaligned > 20:
                print(f"   ... 외 {unaligned - 20}개")
        return aligned, unaligned

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
    normalized_path = None
    matched_count = 0
    matched_names = set()
    initial_input_images = list(input_images)
    delayed_input_images = []
    if geom_reference and geom_score > 0:
        reference_epsg = _extract_epsg_from_reference(geom_reference)
        print(f"📄 EO reference 파일 선택: {geom_reference}")
        normalized_path, matched_count, _, matched_names = _normalize_reference_file(
            geom_reference, geom_delim, name_map, stem_map, output_path
        )
        if normalized_path:
            initial_input_images, delayed_input_images = _split_images_by_reference(
                input_images,
                matched_names,
            )
            print(
                f"📋 EO reference 매칭: {matched_count}개 "
                f"(EPSG:{reference_epsg or input_epsg})"
            )
            print(
                f"📷 1차 처리 대상(EO 있음): {len(initial_input_images)}개 | "
                f"2차 증분 대상(EO 없음): {len(delayed_input_images)}개"
            )
        else:
            raise RuntimeError("EO reference 파일은 찾았지만 입력 이미지와 매칭된 항목이 없습니다.")
    else:
        if eo_only_align:
            raise RuntimeError("EO-only align 모드인데 입력 이미지와 매칭되는 EO reference 파일이 없습니다.")
        print("ℹ️ EO reference 파일 없음 - 전체 이미지를 기존 방식으로 처리합니다.")

    if not initial_input_images:
        raise RuntimeError("1차 정합에 사용할 EO 매칭 이미지가 없습니다.")

    # Step 2: Create a new project and add only EO-matched photos first
    doc = Metashape.Document()
    doc.save(output_path + '/project.psx')
    chunk = doc.addChunk()

    chunk.crs = Metashape.CoordinateSystem(f"EPSG::{reference_epsg or input_epsg}")
    print(f"ℹ️ Coordinate system set to EPSG::{reference_epsg or input_epsg}")

    change_task_status_in_ortho(run_id,"Running")

    try:
        chunk.addPhotos(initial_input_images, load_xmp_accuracy=True)
        doc.save()
        print(f"✅ Added {len(initial_input_images)} EO-matched photos to the core chunk.")
    except Exception as e:
        print(f"❌ Failed to add EO-matched photos: {e}")
        raise RuntimeError(f"Task failed due to: {e}") from e

    drone_makes = {"DJI", "Parrot", "Yuneec", "Autel Robotics", "senseFly"}
    first_camera = chunk.cameras[0]
    make = first_camera.photo.meta["Exif/Make"].strip() if "Exif/Make" in first_camera.photo.meta else ""

    if not make or make not in drone_makes:
        chunk.euler_angles = Metashape.EulerAnglesOPK
        chunk.camera_location_accuracy = Metashape.Vector([0.00001, 0.00001, 0.00001])
        chunk.camera_rotation_accuracy = Metashape.Vector([0.00001, 0.00001, 0.00001])
        print("ℹ️ 'Make' 정보가 드론 제조사에 해당하지 않아 EulerAnglesOPK로 설정되었습니다.")

    if normalized_path:
        chunk.importReference(
            path=normalized_path,
            format=Metashape.ReferenceFormatCSV,
            delimiter=" ",
            columns="nxyzabc"
        )
        print("✅ EO reference imported into the core chunk.")
        

    
    
    # 카메라 회전 정보 사용 설정
    _enable_reference_for_cameras(chunk.cameras)
    doc.save(output_path + '/project.psx')

    def _save_project():
        doc.save(output_path + '/project.psx')

    def _print_limited_items(items, label_getter):
        for item in items[:20]:
            print(f"   - {label_getter(item)}")
        if len(items) > 20:
            print(f"   ... 외 {len(items) - 20}개")

    def _match_photos(reference_preselection, reset_matches=None):
        match_kwargs = dict(
            downscale=mp_downscale,
            keypoint_limit=40000,
            tiepoint_limit=4000,
            generic_preselection=True,
            reference_preselection=reference_preselection,
            keep_keypoints=True,
            progress=progress_callback_wrapper
        )
        if reset_matches is not None:
            match_kwargs["reset_matches"] = reset_matches
        chunk.matchPhotos(**match_kwargs)

    def _align_camera_set(cameras=None, reset_alignment=False):
        if cameras is None:
            chunk.alignCameras(adaptive_fitting=True)
        else:
            chunk.alignCameras(
                cameras=cameras,
                min_image=2,
                adaptive_fitting=True,
                reset_alignment=reset_alignment,
            )
        _save_project()

    def _align_core_photos():
        print("🛠 Aligning EO-matched core photos...")
        _match_photos(reference_preselection=True)
        _align_camera_set()
        core_cameras = list(chunk.cameras)
        core_aligned, core_unaligned = _print_alignment_summary(
            core_cameras,
            "EO core alignment"
        )
        return core_cameras, core_aligned, core_unaligned

    def _retry_unaligned_eo_cameras(core_cameras):
        retry_core_cameras = [camera for camera in core_cameras if not camera.transform]
        if not retry_core_cameras:
            return _print_alignment_summary(core_cameras, "EO core retry result")

        print(
            f"\n🔁 EO-only retry: 정합 실패 EO 카메라 "
            f"{len(retry_core_cameras)}장 재정합 시도..."
        )
        _match_photos(reference_preselection=False, reset_matches=False)
        _align_camera_set(cameras=retry_core_cameras, reset_alignment=False)

        retry_aligned = len([camera for camera in retry_core_cameras if camera.transform])
        print(
            f"✅ EO-only retry 완료: {retry_aligned}/"
            f"{len(retry_core_cameras)}장 추가 정렬됨"
        )
        return _print_alignment_summary(core_cameras, "EO core retry result")

    def _log_skipped_non_eo_images(images):
        if not images:
            return
        print(
            f"ℹ️ EO-only align: EO reference와 매칭되지 않은 이미지 "
            f"{len(images)}장을 chunk에 추가하지 않습니다."
        )
        _print_limited_items(images, lambda image_path: os.path.basename(image_path))

    def _remove_unaligned_eo_cameras(core_cameras):
        unaligned_core_cameras = [camera for camera in core_cameras if not camera.transform]
        if not unaligned_core_cameras:
            return
        print(f"⚠️ EO-only align: 정합 실패 EO 카메라 {len(unaligned_core_cameras)}장을 제거합니다.")
        _print_limited_items(unaligned_core_cameras, lambda camera: camera.label)
        chunk.remove(unaligned_core_cameras)

    def _finalize_eo_only_alignment(core_cameras):
        _log_skipped_non_eo_images(delayed_input_images)
        _remove_unaligned_eo_cameras(core_cameras)

        if len(chunk.cameras) < 2:
            raise RuntimeError(
                f"EO-only align 결과 정합 카메라가 {len(chunk.cameras)}장입니다. "
                "Depth map 생성을 위해 최소 2장이 필요합니다."
            )

        _save_project()
        _print_alignment_summary(chunk.cameras, "Final EO-only alignment")

    def _run_non_eo_incremental_alignment():
        if not delayed_input_images:
            print("ℹ️ EO 없는 추가 이미지가 없어 증분 정합을 건너뜁니다.")
            return

        print(f"\n🧩 EO 없는 이미지 {len(delayed_input_images)}장 no-reset 증분 정합 시작...")
        existing_camera_keys = _get_camera_keys(chunk.cameras)
        chunk.addPhotos(delayed_input_images, load_xmp_accuracy=True)
        incremental_cameras = _get_new_cameras_by_key(chunk.cameras, existing_camera_keys)
        if len(incremental_cameras) != len(delayed_input_images):
            print(
                f"⚠️ 증분 카메라 식별 수가 입력 수와 다릅니다: "
                f"입력 {len(delayed_input_images)}장 / 식별 {len(incremental_cameras)}장"
            )

        # EO 미매칭 이미지는 reference를 최적화 제약으로 쓰지 않습니다.
        _disable_reference_for_cameras(incremental_cameras)
        _save_project()
        print(f"✅ Added {len(incremental_cameras)} non-EO photos for incremental alignment.")

        incremental_camera_keys = _get_camera_keys(incremental_cameras)
        retry_cameras = [camera for camera in chunk.cameras if not camera.transform]
        retry_incremental = len([
            camera for camera in retry_cameras
            if getattr(camera, "key", None) in incremental_camera_keys
        ])
        retry_core = len(retry_cameras) - retry_incremental
        print(
            f"🔁 재정합 대상: 총 {len(retry_cameras)}장 "
            f"(EO core 미정합 {retry_core}장 + non-EO {retry_incremental}장)"
        )

        if retry_cameras:
            _match_photos(reference_preselection=False, reset_matches=False)
            _align_camera_set(cameras=retry_cameras, reset_alignment=False)

        still_unaligned = [c for c in incremental_cameras if not c.transform]
        if still_unaligned:
            print(f"⚠️ EO 없는 이미지 중 {len(still_unaligned)}장은 기존 블록에 안정적으로 붙지 않아 제거합니다.")
            _print_limited_items(still_unaligned, lambda camera: camera.label)
            chunk.remove(still_unaligned)

        _save_project()
        _print_alignment_summary(chunk.cameras, "Final alignment")

    # --- Step 3: Align Photos ---
    try:
        task_name = "Align Photos"
        core_cameras, core_aligned, core_unaligned = _align_core_photos()
        if eo_only_align and core_unaligned > 0:
            core_aligned, core_unaligned = _retry_unaligned_eo_cameras(core_cameras)

        if core_aligned == 0:
            raise RuntimeError("EO 매칭 이미지 정합에 모두 실패했습니다.")

        if eo_only_align:
            _finalize_eo_only_alignment(core_cameras)
        else:
            _run_non_eo_incremental_alignment()

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
        args.reference_path,
        args.eo_only_align
    )

if __name__ == "__main__":
    main()
