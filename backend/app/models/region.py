"""Region boundary model."""
import uuid
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Region(Base):
    """Regional boundary model for spatial filtering and visualization."""
    
    __tablename__ = "regions"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=True)
    layer: Mapped[str | None] = mapped_column(String(100), nullable=True) # "강원 권역", etc.
    
    # Spatial data (PostGIS) - Stored in EPSG:5179 as per source
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=5179), nullable=False)
