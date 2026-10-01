"""add group_count to traffic_hourly

Revision ID: 0011_traffic_hourly_group_count
Revises: 0010_traffic_hourly_gender
Create Date: 2026-09-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_traffic_hourly_group_count"
down_revision: Union[str, Sequence[str], None] = "0010_traffic_hourly_gender"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "traffic_hourly",
        sa.Column("group_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_traffic_hourly_groups",
        "traffic_hourly",
        "group_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_traffic_hourly_groups", "traffic_hourly", type_="check")
    op.drop_column("traffic_hourly", "group_count")
