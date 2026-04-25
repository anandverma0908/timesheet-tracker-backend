"""add parent_id to jira_tickets

Revision ID: 010_add_parent_id
Revises: 816eed898ac5
Create Date: 2026-04-25 14:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '010_add_parent_id'
down_revision: Union[str, Sequence[str], None] = '816eed898ac5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jira_tickets', sa.Column('parent_id', sa.UUID(), sa.ForeignKey('jira_tickets.id'), nullable=True))
    op.create_index('ix_jt_parent', 'jira_tickets', ['parent_id'])


def downgrade() -> None:
    op.drop_index('ix_jt_parent', table_name='jira_tickets')
    op.drop_column('jira_tickets', 'parent_id')
