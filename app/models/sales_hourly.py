from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SalesHourly(Base):
    __tablename__ = "sales_hourly"
    __table_args__ = (
        UniqueConstraint(
            "shop_id",
            "report_date",
            "hour",
            name="uq_sales_hourly_shop_date_hour",
        ),
        CheckConstraint("hour >= 0 AND hour <= 23", name="ck_sales_hourly_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transactions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    returns_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exchanges_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
