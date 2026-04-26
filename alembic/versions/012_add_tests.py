"""012_add_tests

Revision ID: 012_add_tests
Revises: 18b2fa29171e
Create Date: 2026-04-25 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '012_add_tests'
down_revision = '18b2fa29171e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'test_cases',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('organisations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('pod', sa.String(100), nullable=False),
        sa.Column('ticket_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('jira_tickets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ticket_key', sa.String(50), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('preconditions', sa.Text(), nullable=True),
        sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('priority', sa.String(20), server_default='medium', nullable=False),
        sa.Column('status', sa.String(20), server_default='active', nullable=False),
        sa.Column('ai_generated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_by', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_testcase_org_pod', 'test_cases', ['org_id', 'pod'])
    op.create_index('ix_testcase_ticket', 'test_cases', ['ticket_id'])

    op.create_table(
        'test_cycles',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('organisations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('pod', sa.String(100), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sprint_id', sa.String(100), nullable=True),
        sa.Column('release_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), server_default='planning', nullable=False),
        sa.Column('created_by', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_tcycle_org_pod', 'test_cycles', ['org_id', 'pod'])
    op.create_index('ix_tcycle_status', 'test_cycles', ['org_id', 'pod', 'status'])

    op.create_table(
        'test_executions',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('cycle_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('test_cycles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('test_case_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('test_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('executed_by', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_texec_cycle', 'test_executions', ['cycle_id'])
    op.create_index('ix_texec_case', 'test_executions', ['test_case_id'])


def downgrade():
    op.drop_index('ix_texec_case', table_name='test_executions')
    op.drop_index('ix_texec_cycle', table_name='test_executions')
    op.drop_table('test_executions')

    op.drop_index('ix_tcycle_status', table_name='test_cycles')
    op.drop_index('ix_tcycle_org_pod', table_name='test_cycles')
    op.drop_table('test_cycles')

    op.drop_index('ix_testcase_ticket', table_name='test_cases')
    op.drop_index('ix_testcase_org_pod', table_name='test_cases')
    op.drop_table('test_cases')
