"""add price_at_buy to theme portfolio picks

Revision ID: 00cee284d001
Revises: c20a1ebb89d5
Create Date: 2026-08-31 19:30:56.161864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00cee284d001'
down_revision: Union[str, Sequence[str], None] = 'c20a1ebb89d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, no backfill: existing picks predate this column and there's
    # no reliable way to recover the price at the time they were built, so
    # older rows just won't show a since-buy return in the UI.
    with op.batch_alter_table("theme_portfolio_picks") as batch_op:
        batch_op.add_column(sa.Column("price_at_buy", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("theme_portfolio_picks") as batch_op:
        batch_op.drop_column("price_at_buy")
