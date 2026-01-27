import numpy as np
from common_args import parse_arguments, print_debug_info
from osgeo import gdal
import os
from common_utils import activate_metashape_license, progress_callback

def export_dem(output_path):

    def progress_callback_wrapper(value):
        progress_callback(value, "Build DEM", output_path)

    # Turbo 컬러맵 데이터 파일 읽기
    color_data = []

    input_raster_dem = os.path.join(output_path, "dem.tif")
    output_colored_map = os.path.join(output_path, "dem_colored.tif")
    output_cog = os.path.join(output_path, "dem_coloerd_cog.tif")

    dataset = gdal.Open(input_raster_dem)
    if dataset is None:
        raise FileNotFoundError(f"Unable to open file: {input_raster_dem}")
    
        # 첫 번째 밴드 읽기
    band = dataset.GetRasterBand(1)

    # NoData 값 확인 (결측값 처리)
    nodata_value = band.GetNoDataValue()

    # 데이터를 NumPy 배열로 읽기
    data = band.ReadAsArray()

    # 결측값을 제외한 최소/최대 고도 계산
    if nodata_value is not None:
        data = np.ma.masked_equal(data, nodata_value)  # NoData 값을 마스킹
    min_elevation = data.min()
    max_elevation = data.max()
    
    # Turbo 컬러맵 데이터 파일 읽기
    with open("./metashape/turbo_colormap.txt", "r") as f:
        for line in f:
            parts = line.strip().split()
            normalized_value = float(parts[0])
            rgb = list(map(int, parts[1:]))
            color_data.append((normalized_value, rgb))

    def get_color(elevation):
        normalized_value = (elevation - min_elevation) / (max_elevation - min_elevation)
        closest_color = min(color_data, key=lambda x: abs(x[0] - normalized_value))
        return closest_color[1]

    # 예시: 고도 값에 따른 색상 출력
    elevation_levels = np.linspace(min_elevation, max_elevation, num=255)

    color_ramp_file = os.path.join(output_path, "dem_colormap.txt")
    with open(color_ramp_file, "w") as f:
        f.write("nv 0 0 0 0\n")
        for elevation in elevation_levels:
            color = get_color(elevation)
            f.write(f"{elevation:.2f} {color[0]} {color[1]} {color[2]}\n")
            print(f"Elevation: {elevation:.2f}, Color: {color}")


    print("Running gdaldem color-relief...")

    gdal.DEMProcessing(
    destName=output_colored_map,
    srcDS=input_raster_dem,
    processing="color-relief",
    options=gdal.DEMProcessingOptions(
        colorFilename=color_ramp_file,
        format="GTiff",
        creationOptions=["COMPRESS=LZW", "TILED=YES","BIGTIFF=YES","BLOCKSIZE=256"],
        addAlpha=True
    )
)
    print(f"Color relief map saved to dem_colored.tif")


    print("Running gdal_translate...")
    translate_options = gdal.TranslateOptions(
        format="COG",
        creationOptions=[
            "BLOCKSIZE=256",
            "COMPRESS=LZW",
            "PREDICTOR=2",
            "BIGTIFF=YES"
        ]
    )
    gdal.Translate(output_cog, output_colored_map, options=translate_options)
    progress_callback_wrapper(100)
    print(f"Cloud Optimized GeoTIFF saved to {output_cog}")


def main():
    activate_metashape_license()
    # 공통 명령줄 인자 처리
    args, input_images = parse_arguments()

    # 디버깅 정보 출력
    print_debug_info(args, input_images)

    # build_dem 함수 실행
    export_dem( args.output_path )

if __name__ == "__main__":
    main()