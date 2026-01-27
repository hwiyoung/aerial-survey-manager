from osgeo import ogr, osr, gdal
import os
import argparse
import uuid


def _guess_epsg_from_wkt(wkt: str) -> str | None:
    """
    WKT 문자열을 보고 EPSG 코드를 '추론'하는 커스텀 매핑.
    특히 Korea 2000(KGD2002) 계열 좌표계를 JS 로직 기반으로 처리.
    """
    if not wkt:
        return None

    prj_data = wkt.lower()

    # 2. Korea 2000 기반 (GRS80)
    if ('korea 2000' in prj_data) or ('korea_2000' in prj_data) or ('kgd2002' in prj_data):

        # 통합 좌표계
        if (
            'unified_coordinate_system' in prj_data
            or 'unified coordinate system' in prj_data
            or 'unified cs' in prj_data
        ):
            return 'EPSG:5179'

        # TM 원점별
        if ('central belt' in prj_data) or ('central_belt' in prj_data):
            return 'EPSG:5186'
        if (
            'east sea belt' in prj_data
            or 'east_sea_belt' in prj_data
            or 'tm zone 52' in prj_data
        ):
            return 'EPSG:5188'
        if ('west belt' in prj_data) or ('west_belt' in prj_data):
            return 'EPSG:5185'
        if ('east belt' in prj_data) or ('east_belt' in prj_data):
            return 'EPSG:5187'

        # TM을 찾았으나 특정 원점을 명시하지 않은 경우 (일반적으로 중부원점 5186 가정)
        if ('transverse_mercator' in prj_data) or ('transverse mercator' in prj_data):
            return 'EPSG:5186'

        # Korea 2000 기반이지만 위 TM/통합에 해당되지 않는 경우 (지리 좌표계일 가능성) → 4737
        return 'EPSG:4737'

    # 여기 아래로는 필요하면 다른 커스텀 규칙 추가
    # 예: 다른 로컬 좌표계, 단체 내부 정의 등

    return None



def read_crs(vector_path: str) -> str:
    """1. SHP 파일 좌표계 읽기 + EPSG 코드 식별 (AutoIdentify + 커스텀 매핑)"""

    # 파일이 있는지 확인
    if not os.path.exists(vector_path):
        raise FileNotFoundError(f"파일이 존재하지 않습니다: {vector_path}")

    ds = ogr.Open(vector_path)
    if ds is None:
        raise RuntimeError(f"벡터 파일을 열 수 없습니다: {vector_path}")

    layer = ds.GetLayer()
    spatial_ref = layer.GetSpatialRef()

    if spatial_ref is None:
        raise ValueError("레이어에 좌표계 정보가 없습니다.")

    # WKT 출력 (디버깅용)
    wkt = spatial_ref.ExportToWkt()

    # 1) GDAL에게 먼저 EPSG 식별 요청
    spatial_ref.AutoIdentifyEPSG()

    # PROJCS 우선, 없으면 GEOGCS 쪽 Authority 시도
    authority_name = spatial_ref.GetAuthorityName('PROJCS')
    authority_code = spatial_ref.GetAuthorityCode('PROJCS')

    if authority_name is None or authority_code is None:
        authority_name = spatial_ref.GetAuthorityName('GEOGCS')
        authority_code = spatial_ref.GetAuthorityCode('GEOGCS')

    if authority_name == 'EPSG' and authority_code is not None:
        return f"EPSG:{authority_code}"

    # 2) AutoIdentifyEPSG 실패 시 → 커스텀 WKT 기반 매핑
    guessed = _guess_epsg_from_wkt(wkt)
    if guessed is not None:
        return guessed

    # 3) 그래도 못 찾으면 에러
    raise ValueError("EPSG 코드를 식별할 수 없습니다.")


def reproject_vector(in_path, out_path, target_epsg):
    
    """2. 주어진 EPSG로 좌표계 변환"""
    source_ds = ogr.Open(in_path)
    source_layer = source_ds.GetLayer()
    
    source_srs = source_layer.GetSpatialRef()
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(target_epsg)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)


    driver = ogr.GetDriverByName("ESRI Shapefile")
    if os.path.exists(out_path):
        driver.DeleteDataSource(out_path)

    target_ds = driver.CreateDataSource(out_path)
    target_layer = target_ds.CreateLayer("layer", srs=target_srs, geom_type=ogr.wkbPolygon)

    for feature in source_layer:
        geom = feature.GetGeometryRef()
        geom.TransformTo(target_srs)
        out_feat = ogr.Feature(target_layer.GetLayerDefn())
        out_feat.SetGeometry(geom)
        target_layer.CreateFeature(out_feat)
        out_feat = None

    source_ds = None
    target_ds = None


def vector_to_raster(shp_path, tif_path, width_px=3840, height_px=2160, burn_value=1):

    """4. SHP → Raster (지정 해상도 기반)"""
    source_ds = ogr.Open(shp_path)
    layer = source_ds.GetLayer()
    print("1레이어 도형 타입:", layer.GetGeomType())
    extent = layer.GetExtent()  # xmin, xmax, ymin, ymax
    print(f"레이어 범위: {extent}")

    # Bounding box
    xmin, xmax, ymin, ymax = extent

    # 1픽셀당 거리 계산 (pixel size)
    pixel_size_x = (xmax - xmin) / width_px
    pixel_size_y = (ymax - ymin) / height_px  # 주의: y 방향은 보통 위에서 아래로 → 음수

    # gdal.Create에 넣을 x, y 해상도
    x_res = width_px
    y_res = height_px

    target_ds = gdal.GetDriverByName('GTiff').Create(
        tif_path, x_res, y_res, 1, gdal.GDT_Byte
    )

    # GeoTransform 설정: (x_origin, pixel_width, 0, y_origin, 0, -pixel_height)
    geotransform = (xmin, pixel_size_x, 0, ymax, 0, -pixel_size_y)
    target_ds.SetGeoTransform(geotransform)

    srs = layer.GetSpatialRef()
    target_ds.SetProjection(srs.ExportToWkt())

    # 배경을 NoData로 설정 (투명 효과)
    target_ds.GetRasterBand(1).SetNoDataValue(0)


    print("2레이어 도형 타입:", layer.GetGeomType())
    gdal.RasterizeLayer(target_ds, [1], layer, burn_values=[burn_value])
    target_ds.FlushCache()
    target_ds = None


def convert_to_cog( input_path, output_path):
    """5. 일반 TIFF → COG"""
    gdal.Translate(
        output_path,
        input_path,
        format='COG',
        creationOptions=[
            'COMPRESS=LZW',
            'OVERVIEWS=IGNORE_EXISTING'
        ]
    )

def create_thumbnail( input_path, width_px=256, height_px=256):

    thumbnail_path = input_path.replace('.tif', '_thumbnail.png')

    """6. COG에서 썸네일 생성"""
    ds = gdal.Open(input_path)
    if ds is None:
        raise FileNotFoundError(f"파일을 열 수 없습니다: {input_path}")

    # 썸네일 크기 설정
    # thumbnail_size = (256, 256)

    # 썸네일 생성
    gdal.Translate(
        thumbnail_path,
        ds,
        format='PNG',
        width=width_px,
        height=height_px
    )

    ds = None


def change_data_format(file_name, old_format, new_format):
    """7. 데이터 형식 변환"""
    old_path = os.path.join(default_path, file_name)
    new_name = os.path.splitext(os.path.basename(old_path))[0]
    new_path = os.path.join(default_path, 'outputs', f"{new_name}.{new_format}")

    dirverName = None
    if new_format == 'shp':
        dirverName = 'ESRI Shapefile'
    elif new_format == 'GPKG':
        dirverName = 'GPKG'
    elif new_format == 'geojson':
        dirverName = 'GeoJSON'
    else:
        raise ValueError(f"지원하지 않는 형식: {new_format}")

    # 드라이버가 None이 아닌지 확인
    if dirverName != None:
        driver = ogr.GetDriverByName(dirverName)
        
        # 기존 파일이 있다면 삭제
        if os.path.exists(new_path):
            driver.DeleteDataSource(new_path)

        # GeoJSON 파일을 읽어들여서 새로운 형식으로 저장
        source_ds = ogr.Open(old_path)
        source_layer = source_ds.GetLayer()
        source_srs = source_layer.GetSpatialRef()

        ds = driver.CreateDataSource(new_path)
        layer = ds.CreateLayer(new_name, source_srs, geom_type=ogr.wkbMultiPolygon)

        # 레이어의 속성 정의 복사
        source_defn = source_layer.GetLayerDefn()
        for i in range(source_defn.GetFieldCount()):
            field_defn = source_defn.GetFieldDefn(i)
            if field_defn.GetName().strip():
                # 필드 이름이 비어있지 않은 경우에만 추가
                layer.CreateField(field_defn)

        # 레이어의 속성 정의 복사
        for feature in source_layer:
            geom = feature.GetGeometryRef()
            # geometry가 MultiPolygon이 아닌 경우 MultiPolygon으로 강제 변환
            if geom is not None and geom.GetGeometryType() != ogr.wkbMultiPolygon:
                geom = ogr.ForceToMultiPolygon(geom)

            new_feature = ogr.Feature(layer.GetLayerDefn())
            new_feature.SetGeometry(geom)

            # 속성값 복사
            for i in range(source_defn.GetFieldCount()):
                field_name = source_defn.GetFieldDefn(i).GetName()
                if field_name.strip():
                    new_feature.SetField(field_name, feature.GetField(i))

            layer.CreateFeature(new_feature)
            new_feature = None

        ds = None
        source_ds = None

def main(args):
    input_file = args.input_file
    random_str = uuid.uuid4().hex[:8]  # 8자리 랜덤 문자열
    reprojected_file = random_str + "_reprojected.shp"
    tif_output = args.tif_output
    temp_tif_output = args.tif_output.replace('.tif', '_temp.tif')
    default_path = args.default_path

    print("디지털 지도 변환 프로세스 시작...")
    print("1. 원본 좌표계:")
    print(read_crs(input_file))

    print("2. 좌표계 4326으로 변환 중...")
    reproject_vector( input_file, reprojected_file, 4326)

    print("3. SHP → Raster 변환 중...")
    tr_w = 8
    tr_h = 8
    vector_to_raster( reprojected_file, temp_tif_output, 3840*tr_w, 2160*tr_h)

    # reprojected_file 파일 삭제
    reprojected_path = os.path.join(default_path, random_str + "_reprojected.shp")
    if os.path.exists(reprojected_path):
        os.remove(reprojected_path)
    
    print("4. Raster → COG 변환 중...")
    convert_to_cog( temp_tif_output, tif_output)

    if os.path.exists(temp_tif_output):
        os.remove(temp_tif_output)

    print("5. 썸네일 생성 중...")
    create_thumbnail(tif_output, 512, 512)

    print("완료되었습니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="디지털 지도 변환 프로세스")

    parser.add_argument("--input_file", type=str, required=True, help="입력 GeoJSON 파일 경로")
    parser.add_argument("--tif_output", type=str, required=True, help="출력 tif 파일 경로")
    parser.add_argument("--default_path", type=str, required=True, help="기본 경로")

    args = parser.parse_args()
    main(args)