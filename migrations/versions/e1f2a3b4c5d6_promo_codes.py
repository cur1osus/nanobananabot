"""promo codes and redemptions (merges the two open heads)

Revision ID: e1f2a3b4c5d6
Revises: 1ee579c2dfa9, d8b2c3e4f5a6
Create Date: 2026-07-02 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
# Сводим две открытые головы графа (music lyrics и generation queue) в одну
# точку и заодно добавляем таблицы промокодов.
down_revision = ("1ee579c2dfa9", "d8b2c3e4f5a6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("credits", sa.INTEGER(), nullable=False),
        sa.Column(
            "max_activations",
            sa.INTEGER(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "used_activations",
            sa.INTEGER(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("expires_at", mysql.TIMESTAMP(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            mysql.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_promo_codes_code"), "promo_codes", ["code"], unique=True
    )

    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("promo_idpk", sa.INTEGER(), nullable=False),
        sa.Column("user_idpk", sa.INTEGER(), nullable=False),
        sa.Column("credits", sa.INTEGER(), nullable=False),
        sa.Column(
            "created_at",
            mysql.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["promo_idpk"], ["promo_codes.id"]),
        sa.ForeignKeyConstraint(["user_idpk"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("promo_idpk", "user_idpk", name="uq_promo_user"),
    )
    op.create_index(
        op.f("ix_promo_redemptions_promo_idpk"),
        "promo_redemptions",
        ["promo_idpk"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promo_redemptions_user_idpk"),
        "promo_redemptions",
        ["user_idpk"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_promo_redemptions_user_idpk"), table_name="promo_redemptions"
    )
    op.drop_index(
        op.f("ix_promo_redemptions_promo_idpk"), table_name="promo_redemptions"
    )
    op.drop_table("promo_redemptions")
    op.drop_index(op.f("ix_promo_codes_code"), table_name="promo_codes")
    op.drop_table("promo_codes")
