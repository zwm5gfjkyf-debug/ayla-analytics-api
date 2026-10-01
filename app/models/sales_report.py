from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SalesReportDaily(Base):
    __tablename__ = "sales_report_daily"
    __table_args__ = (
        UniqueConstraint("shop_id", "report_date", name="uq_sales_report_daily_shop_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    gross_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_gross_sales: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_sum: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transactions_count: Mapped[int] = mapped_column(Integer, nullable=False)
    orders_count: Mapped[int] = mapped_column(Integer, nullable=False)
    returns_count: Mapped[int] = mapped_column(Integer, nullable=False)
    exchanges_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cheque: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    products_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
