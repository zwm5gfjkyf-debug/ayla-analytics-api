from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DailyStaffing(Base):
    """Distinct cashiers per shop per day, derived from BILLZ receipts."""

    __tablename__ = "daily_staffing"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "report_date",
            name="uq_daily_staffing_shop_date",
        ),
        CheckConstraint(
            "distinct_cashier_count >= 0",
            name="ck_daily_staffing_cashier_count",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    distinct_cashier_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cashier_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
