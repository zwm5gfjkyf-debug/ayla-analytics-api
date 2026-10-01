from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TrafficHourly(Base):
    """Hourly indoor traffic per shop, from Vitrac (Tassvision).

    visitor_count is customer headcount (male + female). group_count is
    Vitrac «Jami guruhlar» — a family of 5 is one group. Conversion uses
    groups, not headcount. Workers are stored separately.
    """

    __tablename__ = "traffic_hourly"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "report_date",
            "hour",
            name="uq_traffic_hourly_shop_date_hour",
        ),
        CheckConstraint("hour >= 0 AND hour <= 23", name="ck_traffic_hourly_hour"),
        CheckConstraint("visitor_count >= 0", name="ck_traffic_hourly_visitors"),
        CheckConstraint("group_count >= 0", name="ck_traffic_hourly_groups"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    visitor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    group_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    male_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    female_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    worker_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
