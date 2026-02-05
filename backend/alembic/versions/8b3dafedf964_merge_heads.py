"""merge_heads

Revision ID: 8b3dafedf964
Revises: 6df507f08f82, d4e5f6a7b8c9
Create Date: 2026-02-05 03:01:10.310903

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '8b3dafedf964'
down_revision: Union[str, None] = ('6df507f08f82', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
