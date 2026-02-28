"""

Revision ID: d3f4a9b8c7e1
Revises: c2b7e1d4ab1c
Create Date: 2026-01-20 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d3f4a9b8c7e1"
down_revision = "c2b7e1d4ab1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "music_tasks",
        sa.Column("audio_file_ids", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("music_tasks", "audio_file_ids")
