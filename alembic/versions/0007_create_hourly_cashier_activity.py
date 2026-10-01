"""create hourly_cashier_activity table

Revision ID: 0007_hourly_cashier_activity
Revises: 0006_create_daily_staffing
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_hourly_cashier_activity"
down_revision: Union[str, Sequence[str], None] = "0006_create_daily_staffing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hourly_cashier_activity",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("cashier_id", sa.String(length=64), nullable=False),
        sa.Column("cashier_name", sa.String(length=255), nullable=False),
        sa.Column("transactions_count", sa.Integer(), nullable=False),
        sa.Column("gross_sales", sa.Numeric(18, 2), nullable=False),
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
            "cashier_id",
            name="uq_hourly_cashier_shop_date_hour_cashier",
        ),
        sa.CheckConstraint("hour >= 0 AND hour <= 23", name="ck_hourly_cashier_hour"),
        sa.CheckConstraint(
            "transactions_count >= 0",
            name="ck_hourly_cashier_transactions",
        ),
    )


def downgrade() -> None:
    op.drop_table("hourly_cashier_activity")
