"""create traffic_manual_daily table

Revision ID: 0005_create_traffic_manual_daily
Revises: 0004_create_sales_hourly
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_create_traffic_manual_daily"
down_revision: Union[str, Sequence[str], None] = "0004_create_sales_hourly"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "traffic_manual_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("visitor_count", sa.Integer(), nullable=False),
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
            name="uq_traffic_manual_daily_shop_date",
        ),
        sa.CheckConstraint("visitor_count >= 0", name="ck_traffic_manual_daily_visitors"),
    )


def downgrade() -> None:
    op.drop_table("traffic_manual_daily")
