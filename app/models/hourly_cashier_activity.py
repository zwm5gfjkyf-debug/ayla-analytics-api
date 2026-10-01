from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class HourlyCashierActivity(Base):
    """Per-hour activity for one cashier at one shop, from BILLZ receipts."""

    __tablename__ = "hourly_cashier_activity"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "report_date",
            "hour",
            "cashier_id",
            name="uq_hourly_cashier_shop_date_hour_cashier",
        ),
        CheckConstraint("hour >= 0 AND hour <= 23", name="ck_hourly_cashier_hour"),
        CheckConstraint(
            "transactions_count >= 0",
            name="ck_hourly_cashier_transactions",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    cashier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cashier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transactions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
