"""gift credits with end-of-day expiry

Revision ID: c7a1f2b3d4e5
Revises: b1d2e3f4a5c6
Create Date: 2026-06-26 14:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "c7a1f2b3d4e5"
down_revision = "b1d2e3f4a5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "gift_credits",
            sa.INTEGER(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "gift_expires_at",
            mysql.TIMESTAMP(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "gift_expires_at")
    op.drop_column("users", "gift_credits")
