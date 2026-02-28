"""
Revision ID: f8c65f1d7b12
Revises: d3f4a9b8c7e1
Create Date: 2026-01-17 18:20:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8c65f1d7b12"
down_revision = "d3f4a9b8c7e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "music_tasks",
        sa.Column("topic_key", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "music_tasks",
        sa.Column("style", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "music_tasks",
        sa.Column("prompt_source", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "music_tasks",
        sa.Column("prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "music_tasks",
        sa.Column(
            "custom_mode", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "music_tasks",
        sa.Column(
            "instrumental", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("music_tasks", "instrumental")
    op.drop_column("music_tasks", "custom_mode")
    op.drop_column("music_tasks", "prompt")
    op.drop_column("music_tasks", "prompt_source")
    op.drop_column("music_tasks", "style")
    op.drop_column("music_tasks", "topic_key")
