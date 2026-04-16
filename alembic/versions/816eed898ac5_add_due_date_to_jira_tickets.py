"""add due_date to jira_tickets

Revision ID: 816eed898ac5
Revises: 006_week6
Create Date: 2026-04-15 18:38:31.218155

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '816eed898ac5'
down_revision: Union[str, Sequence[str], None] = '006_week6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jira_tickets', sa.Column('due_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('jira_tickets', 'due_date')
