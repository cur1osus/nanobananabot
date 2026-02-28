"""

Revision ID: c2b7e1d4ab1c
Revises: a451d9935d85
Create Date: 2026-01-12 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "c2b7e1d4ab1c"
down_revision = "a451d9935d85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "music_tasks",
        sa.Column("user_idpk", sa.INTEGER(), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("chat_id", sa.BIGINT(), nullable=False),
        sa.Column("filename_base", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("errors", sa.INTEGER(), nullable=False),
        sa.Column("credits_cost", sa.INTEGER(), nullable=False),
        sa.Column("poll_timeout", sa.INTEGER(), nullable=False),
        sa.Column("last_polled_at", mysql.TIMESTAMP(), nullable=True),
        sa.Column(
            "created_at",
            mysql.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(["user_idpk"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(op.f("ix_music_tasks_task_id"), "music_tasks", ["task_id"], unique=True)
    op.create_index(op.f("ix_music_tasks_user_idpk"), "music_tasks", ["user_idpk"], unique=False)



def downgrade() -> None:
    op.drop_index(op.f("ix_music_tasks_user_idpk"), table_name="music_tasks")
    op.drop_index(op.f("ix_music_tasks_task_id"), table_name="music_tasks")
    op.drop_table("music_tasks")
