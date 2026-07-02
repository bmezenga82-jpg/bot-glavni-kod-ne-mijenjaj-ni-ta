"""add profit_mode to profit_log

Revision ID: 271b0a298d36
Revises: dbe4b472b6e3
Create Date: 2026-07-02 09:33:08.380630

"""
from alembic import op
import sqlalchemy as sa

revision = '271b0a298d36'
down_revision = 'dbe4b472b6e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('profit_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profit_mode', sa.String(length=10), server_default='usdc', nullable=False))


def downgrade():
    with op.batch_alter_table('profit_log', schema=None) as batch_op:
        batch_op.drop_column('profit_mode')
