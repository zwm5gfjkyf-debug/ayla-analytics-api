"""create daily_staffing table

Revision ID: 0006_create_daily_staffing
Revises: 0005_create_traffic_manual_daily
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_create_daily_staffing"
down_revision: Union[str, Sequence[str], None] = "0005_create_traffic_manual_daily"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_staffing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("distinct_cashier_count", sa.Integer(), nullable=False),
        sa.Column("cashier_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "report_date", name="uq_daily_staffing_shop_date"),
        sa.CheckConstraint(
            "distinct_cashier_count >= 0",
            name="ck_daily_staffing_cashier_count",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_staffing")
