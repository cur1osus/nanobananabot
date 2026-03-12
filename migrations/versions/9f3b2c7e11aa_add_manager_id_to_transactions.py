"""add manager_id to transactions

Revision ID: 9f3b2c7e11aa
Revises: 1ee579c2dfa9
Create Date: 2026-03-12 09:31:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f3b2c7e11aa"
down_revision: Union[str, None] = "1ee579c2dfa9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_transactions_manager_id",
        "transactions",
        ["manager_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_manager_id", table_name="transactions")
    op.drop_column("transactions", "manager_id")
