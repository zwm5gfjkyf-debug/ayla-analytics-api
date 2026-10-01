"""add discount_sum to sales_report_daily

Revision ID: 0003_add_discount_sum
Revises: 0002_create_sales_report_daily
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_discount_sum"
down_revision: Union[str, Sequence[str], None] = "0002_create_sales_report_daily"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales_report_daily",
        sa.Column(
            "discount_sum",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("sales_report_daily", "discount_sum", server_default=None)


def downgrade() -> None:
    op.drop_column("sales_report_daily", "discount_sum")
