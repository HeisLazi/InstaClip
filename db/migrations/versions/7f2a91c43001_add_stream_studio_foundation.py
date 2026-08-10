"""add Stream Studio foundation

Revision ID: 7f2a91c43001
Revises: 3953521d8d77
Create Date: 2026-07-01 22:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f2a91c43001"
down_revision: Union[str, Sequence[str], None] = "3953521d8d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Public edition: stream studio tables intentionally omitted because
    stream_studio.py is not included."""
    pass


def downgrade() -> None:
    """No-op placeholder."""
    pass
