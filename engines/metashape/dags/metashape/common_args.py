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



    args = parser.parse_args()

    # input_images를 쉼표로 구분된 문자열에서 리스트로 변환
    input_images = args.input_images.split(",") if args.input_images else []

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