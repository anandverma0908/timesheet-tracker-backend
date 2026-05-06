"""merge_all_heads

Revision ID: 017_merge_all_heads
Revises: 011_add_custom_fields, 012_add_tests, 016_chat_is_private_column
Create Date: 2026-05-06 09:19:29.029543

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017_merge_all_heads'
down_revision: Union[str, Sequence[str], None] = ('011_add_custom_fields', '012_add_tests', '016_chat_is_private_column')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
