import json
from types import SimpleNamespace

import pytest

from app.services import clip_exports


def test_clip_filename_records_operation_without_sheet_ids():
    assert clip_exports.make_clip_filename("서울 2026.tif", "GeoTiff") == "서울_2026_clip.tif"
    assert clip_exports.make_clip_filename("survey_clip.jpg", "JPG") == "survey_clip.jpg"
    assert clip_exports.make_clip_filename("../../unsafe name", "PNG") == "unsafe_name_clip.png"


def test_selected_sheet_bounds_become_one_multipolygon():
    feature_collection = clip_exports.build_cutline_geojson([
        [37.0, 127.0, 37.1, 127.1],
        [37.0, 127.1, 37.1, 127.2],
    ])

    geometry = feature_collection["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2
    assert geometry["coordinates"][0][0][0] == [127.0, 37.0]
    assert geometry["coordinates"][0][0][-1] == [127.0, 37.0]


def test_cog_validation_requires_layout_and_georeferencing(monkeypatch):
    valid = {
        "driverShortName": "GTiff",
        "metadata": {"IMAGE_STRUCTURE": {"LAYOUT": "COG"}},
        "bands": [{"band": 1}],
        "coordinateSystem": {"wkt": "EPSG:5186"},
    }
    monkeypatch.setattr(
        clip_exports.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(valid)),
    )
    assert clip_exports.validate_cog_source("source.tif")["driverShortName"] == "GTiff"

    invalid = {**valid, "metadata": {"IMAGE_STRUCTURE": {}}}
    monkeypatch.setattr(
        clip_exports.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(invalid)),
    )
    with pytest.raises(clip_exports.InvalidCogSource):
        clip_exports.validate_cog_source("source.tif")


def test_unknown_export_format_is_rejected():
    with pytest.raises(ValueError):
        clip_exports.normalize_export_format("raw")
