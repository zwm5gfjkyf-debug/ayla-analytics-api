"""clear Ayla Sept 4-12 group-count manual traffic

Revision ID: 0012_clear_sept_manual
Revises: 0011_traffic_hourly_group_count
Create Date: 2026-10-01

Those days were entered as Vitrac «Jami guruhlar». Conversion now uses
individual guest headcount, so the old rows must be re-entered.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012_clear_sept_manual"
down_revision: Union[str, Sequence[str], None] = "0011_traffic_hourly_group_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AYLA_SHOP_ID = "588ac214-069a-42a7-8df6-b4bc8ac0cdfb"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM traffic_manual_daily
        WHERE shop_id = '{AYLA_SHOP_ID}'
          AND (
            (report_date >= DATE '2025-09-04' AND report_date <= DATE '2025-09-12')
            OR (report_date >= DATE '2026-09-04' AND report_date <= DATE '2026-09-12')
          )
        """
    )


def downgrade() -> None:
    pass
