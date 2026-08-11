"""add post_metrics analytics

Revision ID: 461aaed89755
Revises: 7f2a91c43001
Create Date: 2026-07-07 01:22:58.256407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '461aaed89755'
down_revision: Union[str, Sequence[str], None] = '7f2a91c43001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Public edition: post_metrics analytics table intentionally omitted
    because the analytics module is not included."""
    pass


def downgrade() -> None:
    """No-op placeholder."""
    pass
