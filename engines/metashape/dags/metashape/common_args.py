import sys
import argparse

def parse_arguments():
    """
    공통 명령줄 인자를 처리하는 함수.
    """
    print(f"DEBUG: sys.argv = {sys.argv}")
    parser = argparse.ArgumentParser(description="Process images using Metashape.")
    parser.add_argument(
        "--input_images",
        required=False,
        help="Comma-separated list of input image file paths (e.g., 'image1.jpg,image2.jpg')."
    )
    parser.add_argument(
        "--input_images_file",
        required=False,
        help="Path to a file containing image file paths (one per line). Use this for large number of images to avoid 'Argument list too long' error."
    )
    parser.add_argument(
        "--image_folder",
        required=False,
        help="Path to the folder containing input images. Required if --input_images is not provided."
    )
    parser.add_argument(
        "--output_path", 
        required=True, 
        help="Path to the output folder where results will be saved."
    )

    parser.add_argument(
        "--run_id", 
        required=True, 
    )

    parser.add_argument(
        "--process_mode", 
        default="Normal", 
        choices=["Normal", "Preview", "High"], 
        help="Processing mode: 'Normal', 'Preview', or 'High'. Default is 'Normal'."
    )
    parser.add_argument(
        "--output_tiff_name", 
        required=True, 
    )
    parser.add_argument(
        "--reai_task_id", 
        required=True, 
        help="Path to the output folder where results will be saved."
    )

    parser.add_argument(
        "--input_epsg", 
        required=False, 
        default="4326",
    )
    parser.add_argument(
        "--output_epsg", 
        required=False, 
        default="5186",
    )
    parser.add_argument(
        "--reference_path",
        required=False,
        help="Optional path to EO reference file (.txt/.csv) or a directory containing it."
    )



    args = parser.parse_args()

    # input_images 처리: 파일 또는 쉼표 구분 문자열에서 리스트로 변환
    input_images = []
    if args.input_images_file:
        # 파일에서 이미지 목록 읽기 (대용량 이미지 처리용 - ARG_MAX 제한 우회)
        with open(args.input_images_file, 'r') as f:
            input_images = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(input_images)} images from file: {args.input_images_file}")
    elif args.input_images:
        # 기존 방식: 쉼표로 구분된 문자열 (소량 이미지용)
        input_images = args.input_images.split(",")

    return args, input_images

def print_debug_info(args, input_images):
    """
    디버깅 정보를 출력하는 함수.
    """
    print(f"Input Images: {input_images}")
    print(f"Image Folder: {args.image_folder}")
    print(f"Output Path: {args.output_path}")
    print(f"Process Mode: {args.process_mode}")
    print(f"Found {len(input_images)} images.")
