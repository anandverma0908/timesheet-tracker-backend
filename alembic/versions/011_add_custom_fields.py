"""011_add_custom_fields

Revision ID: 011_add_custom_fields
Revises: 010_add_parent_id_to_jira_tickets
Create Date: 2026-04-25 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_add_custom_fields'
down_revision = '010_add_parent_id_to_jira_tickets'
branch_labels = None
depends_on = None


def upgrade():
    # Add custom_fields JSONB to jira_tickets
    op.add_column('jira_tickets', sa.Column('custom_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_jt_custom_fields', 'jira_tickets', ['custom_fields'], postgresql_using='gin')

    # Create custom_fields_definitions table
    op.create_table(
        'custom_field_definitions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organisations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('pod', sa.String(100), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('field_type', sa.String(50), nullable=False),  # text, number, select, date, checkbox
        sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_required', sa.Boolean(), default=False),
        sa.Column('display_order', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_cfd_org_pod', 'custom_field_definitions', ['org_id', 'pod'])


def downgrade():
    op.drop_index('ix_cfd_org_pod', table_name='custom_field_definitions')
    op.drop_table('custom_field_definitions')
    op.drop_index('ix_jt_custom_fields', table_name='jira_tickets')
    op.drop_column('jira_tickets', 'custom_fields')
