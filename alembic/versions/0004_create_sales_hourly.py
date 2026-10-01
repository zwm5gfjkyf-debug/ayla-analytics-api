"""create sales_hourly table

Revision ID: 0004_create_sales_hourly
Revises: 0003_add_discount_sum
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_create_sales_hourly"
down_revision: Union[str, Sequence[str], None] = "0003_add_discount_sum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_hourly",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("gross_sales", sa.Numeric(18, 2), nullable=False),
        sa.Column("transactions_count", sa.Integer(), nullable=False),
        sa.Column("returns_count", sa.Integer(), nullable=False),
        sa.Column("exchanges_count", sa.Integer(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id",
            "report_date",
            "hour",
            name="uq_sales_hourly_shop_date_hour",
        ),
        sa.CheckConstraint("hour >= 0 AND hour <= 23", name="ck_sales_hourly_hour"),
    )


def downgrade() -> None:
    op.drop_table("sales_hourly")
