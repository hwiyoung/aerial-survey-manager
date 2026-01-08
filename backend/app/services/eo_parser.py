"""Service for parsing Exterior Orientation (EO) data files."""
import csv
import io
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


class EOParserService:
    @staticmethod
    def parse_eo_file(
        content: str,
        delimiter: str = ",",
        has_header: bool = True,
        columns: Dict[str, int] = None
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
        lines = content.strip().split('\n')
        
        # Handle header
        start_idx = 1 if has_header else 0
        
        for line in lines[start_idx:]:
            line = line.strip()
            if not line:
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
                    kappa=float(row[columns["kappa"]])
                )
                results.append(eo_row)
            except (ValueError, IndexError):
                # Skip invalid rows
                continue
                
        return results
