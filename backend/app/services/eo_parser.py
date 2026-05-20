"""Service for parsing Exterior Orientation (EO) data files."""
import csv
import io
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class EORow(BaseModel):
    image_name: str
    x: float
    y: float
    z: float
    omega: float
    phi: float
    kappa: float
    crs: Optional[str] = None
    source_file: Optional[str] = None


class EOParserService:
    _crs_pattern = re.compile(r"(?:EPSG[:\s]*)?(\d{4,5})", re.IGNORECASE)
    _known_crs_codes = {"4326", "5179", "5185", "5186", "5187", "5188"}

    @classmethod
    def normalize_crs(cls, value: Optional[str]) -> Optional[str]:
        """Extract and normalize supported EPSG codes from free-form text."""
        if not value:
            return None

        text = str(value).strip()
        for match in cls._crs_pattern.finditer(text):
            code = match.group(1)
            if "epsg" in match.group(0).lower() or code in cls._known_crs_codes:
                return f"EPSG:{code}"
        return None

    @classmethod
    def _extract_row_crs(cls, row: list[str], columns: Dict[str, int]) -> Optional[str]:
        if "crs" in columns:
            try:
                return cls.normalize_crs(row[columns["crs"]])
            except (IndexError, TypeError):
                return None

        used_indices = {idx for idx in columns.values() if isinstance(idx, int)}
        for idx, value in enumerate(row):
            if idx in used_indices:
                continue
            normalized = cls.normalize_crs(value)
            if normalized:
                return normalized
        return None

    @staticmethod
    def parse_eo_file(
        content: str,
        delimiter: str = ",",
        has_header: bool = True,
        columns: Dict[str, int] = None,
        source_file: Optional[str] = None,
    ) -> List[EORow]:
        """
        Parse EO data from a string.
        
        Args:
            content: The file content as a string.
            delimiter: The character separating values.
            has_header: Whether the first row is a header.
            columns: Mapping of field names to column indices.
                     e.g., {"image_name": 0, "x": 1, "y": 2, ...}
        """
        # Default column mapping if none provided
        if not columns:
            columns = {
                "image_name": 0,
                "x": 1,
                "y": 2,
                "z": 3,
                "omega": 4,
                "phi": 5,
                "kappa": 6
            }
        
        results = []
        lines = content.splitlines()
        skip_next_data_line = has_header
        current_crs = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_crs = EOParserService.normalize_crs(line)
            if line.startswith("#") or line.startswith("//"):
                if line_crs:
                    current_crs = line_crs
                continue

            if skip_next_data_line:
                skip_next_data_line = False
                continue
            
            # For space delimiter, use split() without argument to handle multiple spaces
            if delimiter == ' ':
                row = line.split()  # Splits on any whitespace, handles multiple spaces
            else:
                # Use csv reader for other delimiters (comma, tab, etc.)
                reader = csv.reader(io.StringIO(line), delimiter=delimiter)
                row = next(reader, [])
            
            if not row or len(row) < max(columns.values()) + 1:
                continue
                
            try:
                eo_row = EORow(
                    image_name=row[columns["image_name"]].strip(),
                    x=float(row[columns["x"]]),
                    y=float(row[columns["y"]]),
                    z=float(row[columns["z"]]),
                    omega=float(row[columns["omega"]]),
                    phi=float(row[columns["phi"]]),
                    kappa=float(row[columns["kappa"]]),
                    crs=EOParserService._extract_row_crs(row, columns) or current_crs,
                    source_file=source_file,
                )
                results.append(eo_row)
            except (ValueError, IndexError):
                # Skip invalid rows
                continue
                
        return results
