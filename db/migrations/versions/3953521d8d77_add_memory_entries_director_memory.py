"""add memory_entries (director memory)

Revision ID: 3953521d8d77
Revises: c8972e212b4e
Create Date: 2026-06-30 01:41:32.094282

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3953521d8d77'
down_revision: Union[str, Sequence[str], None] = 'c8972e212b4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Public edition: memory_entries table intentionally omitted because the
    Director module is not included."""
    pass


def downgrade() -> None:
    """No-op placeholder."""
    pass
