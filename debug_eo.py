import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.services.eo_parser import EOParserService

test_content = """DJI_20241023102514_0115.JPG        126.631807      37.524525       178.236 0.036325        -0.093169       111.300030
DJI_20241023102516_0116.JPG    126.631600      37.524465       184.070 0.036325        -0.093169       111.300030
DJI_20241023102529_0117.JPG    126.631400      37.524400       184.070 0.036325        -0.093169       111.300030
"""

config = {
    "delimiter": " ",
    "has_header": False,
    "columns": {"image_name": 0, "x": 1, "y": 2, "z": 3, "omega": 4, "phi": 5, "kappa": 6}
}

try:
    results = EOParserService.parse_eo_file(
        content=test_content,
        delimiter=config["delimiter"],
        has_header=config["has_header"],
        columns=config["columns"]
    )

    print(f"Parsed {len(results)} rows.")
    for res in results:
        print(f"Img: {res.image_name}, X: {res.x}, Y: {res.y}")

    if len(results) == 3:
        print("SUCCESS: All rows parsed correctly.")
    else:
        print(f"FAILURE: Expected 3 rows, got {len(results)}")

except Exception as e:
    print(f"ERROR during parsing: {e}")
