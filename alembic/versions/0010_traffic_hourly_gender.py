"""add gender counts to traffic_hourly

Revision ID: 0010_traffic_hourly_gender
Revises: 0009_create_access_tables
Create Date: 2026-09-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_traffic_hourly_gender"
down_revision: Union[str, Sequence[str], None] = "0009_create_access_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "traffic_hourly",
        sa.Column("male_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "traffic_hourly",
        sa.Column("female_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "traffic_hourly",
        sa.Column("worker_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("traffic_hourly", "worker_count")
    op.drop_column("traffic_hourly", "female_count")
    op.drop_column("traffic_hourly", "male_count")
