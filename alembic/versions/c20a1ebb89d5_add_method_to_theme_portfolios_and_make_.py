"""add method to theme portfolios and make pick verdict nullable

Revision ID: c20a1ebb89d5
Revises: 3f0a55b8f7db
Create Date: 2026-08-31 15:21:56.897301

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c20a1ebb89d5'
down_revision: Union[str, Sequence[str], None] = '3f0a55b8f7db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # method backfills existing rows to 'ai_team' (a server_default, not
    # just the ORM-level Python default) since those rows predate this
    # column and genuinely were all AI-team runs - SQLite requires batch
    # mode to alter an existing column, hence the batch_alter_table blocks.
    with op.batch_alter_table("theme_portfolio_picks") as batch_op:
        batch_op.alter_column("verdict", existing_type=sa.VARCHAR(length=8), nullable=True)
    with op.batch_alter_table("theme_portfolios") as batch_op:
        batch_op.add_column(sa.Column("method", sa.String(length=16), nullable=False, server_default="ai_team"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("theme_portfolios") as batch_op:
        batch_op.drop_column("method")
    with op.batch_alter_table("theme_portfolio_picks") as batch_op:
        batch_op.alter_column("verdict", existing_type=sa.VARCHAR(length=8), nullable=False)
