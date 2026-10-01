from datetime import date, timedelta
from decimal import Decimal
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.models.sales_hourly import SalesHourly
from app.models.sales_report import SalesReportDaily
from app.services.sales_sync import (
    get_tashkent_today,
    range_overlaps_today_or_yesterday,
    refresh_hourly_if_recent,
    refresh_today_and_yesterday,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sales", tags=["sales"])


class BranchBreakdown(BaseModel):
    shop_id: str
    shop_name: str
    gross_sales: float
    net_gross_sales: float
    discount_sum: float
    transactions_count: int
    average_cheque: float


class DailySales(BaseModel):
    date: str
    net_gross_sales: float


class HourlySalesRow(BaseModel):
    shop_id: str
    shop_name: str
    date: str
    hour: int
    gross_sales: float
    transactions_count: int
    returns_count: int
    exchanges_count: int


class SalesSummaryResponse(BaseModel):
    start_date: str
    end_date: str
    total_gross_sales: float
    total_net_gross_sales: float
    total_transactions_count: int
    top_branch: BranchBreakdown | None
    top_branch_date: str | None
    server_today: str
    latest_synced_date: str | None
    is_live: bool
    as_of_date: str | None
    live_refresh_ok: bool
    branches: list[BranchBreakdown]
    daily: list[DailySales]


def _as_float(value: Decimal | float | int | None) -> float:
    return float(value or 0)


def _as_int(value: int | None) -> int:
    return int(value or 0)


def _average_cheque(net: Decimal | float | int | None, transactions: int | None) -> float:
    txn = _as_int(transactions)
    if txn <= 0:
        return 0.0
    return _as_float(net) / txn


def _branch(
    shop_id: str,
    shop_name: str,
    gross: Decimal | float | int | None,
    net: Decimal | float | int | None,
    discount: Decimal | float | int | None,
    transactions: int | None,
) -> BranchBreakdown:
    return BranchBreakdown(
        shop_id=shop_id,
        shop_name=shop_name,
        gross_sales=round(_as_float(gross), 2),
        net_gross_sales=round(_as_float(net), 2),
        discount_sum=round(_as_float(discount), 2),
        transactions_count=_as_int(transactions),
        average_cheque=round(_average_cheque(net, transactions), 2),
    )


def _empty_summary(
    start: date,
    end: date,
    server_today: date,
    *,
    live_refresh_ok: bool = False,
) -> SalesSummaryResponse:
    return SalesSummaryResponse(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        total_gross_sales=0,
        total_net_gross_sales=0,
        total_transactions_count=0,
        top_branch=None,
        top_branch_date=None,
        server_today=server_today.isoformat(),
        latest_synced_date=None,
        is_live=False,
        as_of_date=None,
        live_refresh_ok=live_refresh_ok,
        branches=[],
        daily=[],
    )


@router.get("/summary", response_model=SalesSummaryResponse)
async def sales_summary(
    start_date: date | None = Query(None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="Inclusive end date (YYYY-MM-DD)"),
) -> SalesSummaryResponse:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    tashkent_today = get_tashkent_today()
    live_refresh_ok = True
    if range_overlaps_today_or_yesterday(start_date, end_date):
        refresh = await refresh_today_and_yesterday()
        tashkent_today = refresh["today"]
        live_refresh_ok = bool(refresh["ok"])
    else:
        logger.info(
            "Skipping daily BILLZ refresh for historical range %s–%s (today=%s)",
            start_date.isoformat() if start_date else None,
            end_date.isoformat() if end_date else None,
            tashkent_today.isoformat(),
        )

    async with AsyncSessionLocal() as session:
        latest_synced_date = await session.scalar(select(func.max(SalesReportDaily.report_date)))
        today_row_count = await session.scalar(
            select(func.count())
            .select_from(SalesReportDaily)
            .where(SalesReportDaily.report_date == tashkent_today)
        )
        has_today = (today_row_count or 0) > 0

        if start_date is None or end_date is None:
            bounds = await session.execute(
                select(
                    func.min(SalesReportDaily.report_date),
                    func.max(SalesReportDaily.report_date),
                )
            )
            min_date, max_date = bounds.one()
            if min_date is None or max_date is None:
                empty_start = start_date or tashkent_today
                empty_end = end_date or empty_start
                logger.info(
                    "highlight_card_dates server_today=%s latest_synced_date=%s card_query_date=%s",
                    tashkent_today.isoformat(),
                    None,
                    None,
                )
                return _empty_summary(
                    empty_start,
                    empty_end,
                    tashkent_today,
                    live_refresh_ok=live_refresh_ok,
                )
            start_date = start_date or min_date
            end_date = end_date or max_date

        date_filter = (
            SalesReportDaily.report_date >= start_date,
            SalesReportDaily.report_date <= end_date,
        )

        totals = await session.execute(
            select(
                func.coalesce(func.sum(SalesReportDaily.gross_sales), 0),
                func.coalesce(func.sum(SalesReportDaily.net_gross_sales), 0),
                func.coalesce(func.sum(SalesReportDaily.transactions_count), 0),
            ).where(*date_filter)
        )
        total_gross, total_net, total_txn = totals.one()

        branch_rows = await session.execute(
            select(
                SalesReportDaily.shop_id,
                SalesReportDaily.shop_name,
                func.sum(SalesReportDaily.gross_sales),
                func.sum(SalesReportDaily.net_gross_sales),
                func.sum(SalesReportDaily.discount_sum),
                func.sum(SalesReportDaily.transactions_count),
            )
            .where(*date_filter)
            .group_by(SalesReportDaily.shop_id, SalesReportDaily.shop_name)
            .having(func.sum(SalesReportDaily.net_gross_sales) > 0)
            .order_by(func.sum(SalesReportDaily.net_gross_sales).desc())
        )
        branches = [
            _branch(shop_id, shop_name, gross, net, discount, txn)
            for shop_id, shop_name, gross, net, discount, txn in branch_rows.all()
        ]

        daily_rows = await session.execute(
            select(
                SalesReportDaily.report_date,
                func.coalesce(func.sum(SalesReportDaily.net_gross_sales), 0),
            )
            .where(*date_filter)
            .group_by(SalesReportDaily.report_date)
            .order_by(SalesReportDaily.report_date)
        )
        daily_map = {row_date: amount for row_date, amount in daily_rows.all()}
        daily: list[DailySales] = []
        cursor = start_date
        while cursor <= end_date:
            daily.append(
                DailySales(
                    date=cursor.isoformat(),
                    net_gross_sales=round(_as_float(daily_map.get(cursor)), 2),
                )
            )
            cursor += timedelta(days=1)

        latest_date = await session.scalar(
            select(func.max(SalesReportDaily.report_date)).where(*date_filter)
        )
        top_branch = None
        if latest_date is not None:
            top_row = (
                await session.execute(
                    select(
                        SalesReportDaily.shop_id,
                        SalesReportDaily.shop_name,
                        SalesReportDaily.gross_sales,
                        SalesReportDaily.net_gross_sales,
                        SalesReportDaily.discount_sum,
                        SalesReportDaily.transactions_count,
                    )
                    .where(
                        SalesReportDaily.report_date == latest_date,
                        SalesReportDaily.net_gross_sales > 0,
                    )
                    .order_by(SalesReportDaily.net_gross_sales.desc())
                    .limit(1)
                )
            ).first()
            if top_row is not None:
                top_branch = _branch(*top_row)

        card_query_date = latest_date.isoformat() if latest_date is not None and top_branch else None
        range_includes_today = start_date <= tashkent_today <= end_date
        is_live = has_today and range_includes_today and live_refresh_ok
        as_of_date = None
        if range_includes_today and not is_live:
            as_of_date = (
                latest_synced_date.isoformat() if latest_synced_date is not None else None
            )
        logger.info(
            "highlight_card_dates server_today=%s latest_synced_date=%s card_query_date=%s is_live=%s",
            tashkent_today.isoformat(),
            latest_synced_date.isoformat() if latest_synced_date is not None else None,
            card_query_date,
            is_live,
        )

    return SalesSummaryResponse(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        total_gross_sales=round(_as_float(total_gross), 2),
        total_net_gross_sales=round(_as_float(total_net), 2),
        total_transactions_count=_as_int(total_txn),
        top_branch=top_branch,
        top_branch_date=card_query_date,
        server_today=tashkent_today.isoformat(),
        latest_synced_date=latest_synced_date.isoformat() if latest_synced_date is not None else None,
        is_live=is_live,
        as_of_date=as_of_date,
        live_refresh_ok=live_refresh_ok,
        branches=branches,
        daily=daily,
    )


@router.get("/hourly", response_model=list[HourlySalesRow])
async def sales_hourly(
    date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    shop_id: str = Query(..., description="Shop UUID"),
) -> list[HourlySalesRow]:
    shop = shop_id.strip()
    if not shop:
        raise HTTPException(status_code=400, detail="shop_id is required")

    await refresh_hourly_if_recent(date, shop_ids=[shop])

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SalesHourly)
            .where(
                SalesHourly.report_date == date,
                SalesHourly.shop_id == shop,
            )
            .order_by(SalesHourly.hour)
        )
        rows = result.scalars().all()

    return [
        HourlySalesRow(
            shop_id=row.shop_id,
            shop_name=row.shop_name,
            date=row.report_date.isoformat(),
            hour=row.hour,
            gross_sales=round(_as_float(row.gross_sales), 2),
            transactions_count=row.transactions_count,
            returns_count=row.returns_count,
            exchanges_count=row.exchanges_count,
        )
        for row in rows
    ]
