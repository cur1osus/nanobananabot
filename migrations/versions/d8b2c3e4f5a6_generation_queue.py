"""generation tasks queue (restart-survivable, non-blocking)

Revision ID: d8b2c3e4f5a6
Revises: c7a1f2b3d4e5
Create Date: 2026-06-28 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d8b2c3e4f5a6"
down_revision = "c7a1f2b3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("status_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("params", sa.Text(), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("provider_task_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column(
            "attempts",
            sa.INTEGER(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_tasks", "attempts")
    op.drop_column("generation_tasks", "provider_task_id")
    op.drop_column("generation_tasks", "params")
    op.drop_column("generation_tasks", "status_message_id")
    op.drop_column("generation_tasks", "chat_id")
