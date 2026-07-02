"""add auto_start to trading_pair

Revision ID: dbe4b472b6e3
Revises: db10f0f4b5bf
Create Date: 2026-07-01 23:41:00

"""
from alembic import op
import sqlalchemy as sa

revision = 'dbe4b472b6e3'
down_revision = 'db10f0f4b5bf'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('trading_pair', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_start', sa.Boolean(), nullable=False, server_default='0'))

def downgrade():
    with op.batch_alter_table('trading_pair', schema=None) as batch_op:
        batch_op.drop_column('auto_start')
