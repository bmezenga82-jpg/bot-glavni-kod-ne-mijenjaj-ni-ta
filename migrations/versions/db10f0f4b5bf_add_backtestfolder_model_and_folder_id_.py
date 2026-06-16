"""Add BacktestFolder model and folder_id to BacktestResult

Revision ID: db10f0f4b5bf
Revises: 835966e5e1ed
Create Date: 2026-06-16 10:10:42.119309

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db10f0f4b5bf'
down_revision = '835966e5e1ed'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if 'backtest_folder' not in tables:
        op.create_table('backtest_folder',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('parent_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    existing_cols = [c['name'] for c in inspector.get_columns('backtest_result')]
    if 'folder_id' not in existing_cols:
        with op.batch_alter_table('backtest_result', schema=None) as batch_op:
            batch_op.add_column(sa.Column('folder_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('backtest_result', schema=None) as batch_op:
        batch_op.drop_column('folder_id')
    op.drop_table('backtest_folder')
