"""create traffic_hourly table

Revision ID: 0008_create_traffic_hourly
Revises: 0007_hourly_cashier_activity
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_create_traffic_hourly"
down_revision: Union[str, Sequence[str], None] = "0007_hourly_cashier_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS traffic_hourly (
            id SERIAL PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL,
            report_date DATE NOT NULL,
            hour INTEGER NOT NULL,
            visitor_count INTEGER NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_traffic_hourly_shop_date_hour UNIQUE (shop_id, report_date, hour),
            CONSTRAINT ck_traffic_hourly_hour CHECK (hour >= 0 AND hour <= 23),
            CONSTRAINT ck_traffic_hourly_visitors CHECK (visitor_count >= 0)
        )
        """
    )


def downgrade() -> None:
    op.drop_table("traffic_hourly")
