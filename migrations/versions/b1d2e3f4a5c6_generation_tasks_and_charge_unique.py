"""generation_tasks table + unique telegram_charge_id

Revision ID: b1d2e3f4a5c6
Revises: 9f3b2c7e11aa
Create Date: 2026-06-26 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "b1d2e3f4a5c6"
down_revision = "9f3b2c7e11aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_tasks",
        sa.Column("user_idpk", sa.INTEGER(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("credits_cost", sa.INTEGER(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
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
    )
    op.create_index(
        op.f("ix_generation_tasks_user_idpk"),
        "generation_tasks",
        ["user_idpk"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generation_tasks_status"),
        "generation_tasks",
        ["status"],
        unique=False,
    )

    # Идемпотентность платежей: один telegram charge → одно начисление.
    op.create_unique_constraint(
        "uq_transactions_telegram_charge_id",
        "transactions",
        ["telegram_charge_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_transactions_telegram_charge_id",
        "transactions",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_generation_tasks_status"), table_name="generation_tasks"
    )
    op.drop_index(
        op.f("ix_generation_tasks_user_idpk"), table_name="generation_tasks"
    )
    op.drop_table("generation_tasks")
