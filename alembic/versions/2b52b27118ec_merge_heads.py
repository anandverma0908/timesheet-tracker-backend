"""merge_heads

Revision ID: 2b52b27118ec
Revises: 009_add_goal_insight_hash, 816eed898ac5
Create Date: 2026-04-22 22:44:08.206323

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b52b27118ec'
down_revision: Union[str, Sequence[str], None] = ('009_add_goal_insight_hash', '816eed898ac5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
