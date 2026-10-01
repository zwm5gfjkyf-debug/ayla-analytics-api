from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TrafficManualDaily(Base):
    """Daily guest headcount per shop (male + female, workers excluded).

    Manual fallback for conversion when hourly Vitrac rows have not been
    synced yet. visitor_count is individual people, not group count.
    """

    __tablename__ = "traffic_manual_daily"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "report_date",
            name="uq_traffic_manual_daily_shop_date",
        ),
        CheckConstraint("visitor_count >= 0", name="ck_traffic_manual_daily_visitors"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    visitor_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Individual guests: male + female, workers excluded. Not group count.",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
