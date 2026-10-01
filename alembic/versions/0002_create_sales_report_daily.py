"""create sales_report_daily table

Revision ID: 0002_create_sales_report_daily
Revises: 0001_create_billz_tokens
Create Date: 2026-09-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_sales_report_daily"
down_revision: Union[str, Sequence[str], None] = "0001_create_billz_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_report_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("gross_sales", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_gross_sales", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(18, 2), nullable=False),
        sa.Column("transactions_count", sa.Integer(), nullable=False),
        sa.Column("orders_count", sa.Integer(), nullable=False),
        sa.Column("returns_count", sa.Integer(), nullable=False),
        sa.Column("exchanges_count", sa.Integer(), nullable=False),
        sa.Column("average_cheque", sa.Numeric(18, 2), nullable=False),
        sa.Column("products_sold", sa.Integer(), nullable=False),
        sa.Column("target", sa.Numeric(18, 2), nullable=True),
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
            name="uq_sales_report_daily_shop_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("sales_report_daily")
