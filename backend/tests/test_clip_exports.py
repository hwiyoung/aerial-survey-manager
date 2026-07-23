import json
from types import SimpleNamespace

import pytest

from app.services import clip_exports


def test_clip_filename_records_operation_without_sheet_ids():
    assert clip_exports.make_clip_filename("서울 2026.tif", "GeoTiff") == "서울_2026_clip.tif"
    assert clip_exports.make_clip_filename("survey_clip.jpg", "JPG") == "survey_clip.jpg"
    assert clip_exports.make_clip_filename("../../unsafe name", "PNG") == "unsafe_name_clip.png"


def test_default_clip_filename_includes_region_before_project_title():
    base = clip_exports.make_default_clip_base_filename(
        "2025_5B",
        "수도권남부 권역",
    )

    assert clip_exports.make_clip_filename(base, "GeoTiff") == (
        "수도권남부_권역_2025_5B_ortho_clip.tif"
    )


def test_legacy_requested_clip_filename_gets_region_prefix_once():
    base = clip_exports.make_region_aware_clip_base_filename(
        "2025_5B",
        "수도권남부 권역",
        "2025_5B_ortho",
    )
    already_prefixed = clip_exports.make_region_aware_clip_base_filename(
        "2025_5B",
        "수도권남부 권역",
        "수도권남부_권역_2025_5B_ortho",
    )

    assert base == "수도권남부_권역_2025_5B_ortho"
    assert already_prefixed == base


def test_clip_output_path_is_flat_and_uses_pc_style_numbering(tmp_path):
    filename = "서울_2026_clip.tif"

    assert clip_exports.select_available_clip_output_path(tmp_path, filename) == (
        tmp_path / filename
    )
    (tmp_path / filename).touch()
    assert clip_exports.select_available_clip_output_path(tmp_path, filename) == (
        tmp_path / "서울_2026_clip (1).tif"
    )
    (tmp_path / "서울_2026_clip (1).tif").touch()
    assert clip_exports.select_available_clip_output_path(tmp_path, filename) == (
        tmp_path / "서울_2026_clip (2).tif"
    )


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
