from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales_report import SalesReportDaily
from app.models.traffic_hourly import TrafficHourly
from app.models.traffic_manual import TrafficManualDaily


def conversion_pct(transactions_count: int, visitor_count: int) -> float | None:
    """transactions ÷ visitor_count × 100.

    visitor_count is individual guest headcount (male + female, workers
    excluded) — not Vitrac groups.
    """
    if visitor_count <= 0:
        return None
    return round(100.0 * transactions_count / visitor_count, 2)


async def get_daily_visitor_counts(
    session: AsyncSession,
    shop_id: str,
) -> dict[date, int]:
    """Daily guest headcount per shop (male + female, workers excluded).

    Prefer summed TrafficHourly.visitor_count. Fall back to manual daily
    entry of the same headcount.
    """
    hourly = await session.execute(
        select(
            TrafficHourly.report_date,
            func.coalesce(func.sum(TrafficHourly.visitor_count), 0),
        )
        .where(TrafficHourly.shop_id == shop_id)
        .group_by(TrafficHourly.report_date)
    )
    counts = {row[0]: int(row[1] or 0) for row in hourly.all() if int(row[1] or 0) > 0}

    result = await session.execute(
        select(TrafficManualDaily.report_date, TrafficManualDaily.visitor_count).where(
            TrafficManualDaily.shop_id == shop_id
        )
    )
    for report_date, visitor_count in result.all():
        counts.setdefault(report_date, int(visitor_count or 0))
    return counts


async def get_daily_group_counts(
    session: AsyncSession,
    shop_id: str,
) -> dict[date, int]:
    """Daily Vitrac group totals per shop. Not used for conversion."""
    hourly = await session.execute(
        select(
            TrafficHourly.report_date,
            func.coalesce(func.sum(TrafficHourly.group_count), 0),
        )
        .where(TrafficHourly.shop_id == shop_id)
        .group_by(TrafficHourly.report_date)
    )
    return {row[0]: int(row[1] or 0) for row in hourly.all() if int(row[1] or 0) > 0}


async def conversion_series(
    session: AsyncSession,
    shop_id: str,
) -> list[dict[str, Any]]:
    visitors = await get_daily_visitor_counts(session, shop_id)
    if not visitors:
        return []
    groups = await get_daily_group_counts(session, shop_id)

    sales = await session.execute(
        select(SalesReportDaily.report_date, SalesReportDaily.transactions_count).where(
            SalesReportDaily.shop_id == shop_id,
            SalesReportDaily.report_date.in_(visitors.keys()),
        ).order_by(SalesReportDaily.report_date)
    )

    rows: list[dict[str, Any]] = []
    for report_date, transactions_count in sales.all():
        visitor_count = visitors.get(report_date)
        if visitor_count is None:
            continue
        rows.append(
            {
                "date": report_date.isoformat(),
                "visitor_count": visitor_count,
                "group_count": groups.get(report_date, 0),
                "transactions_count": int(transactions_count or 0),
                "conversion_pct": conversion_pct(int(transactions_count or 0), visitor_count),
            }
        )
    return rows


async def weekly_heatmap(
    session: AsyncSession,
    shop_id: str,
) -> dict[str, Any]:
    """Average visitors by ISO weekday (Mon=1) and hour across all stored days."""
    day_count = int(
        await session.scalar(
            select(func.count(func.distinct(TrafficHourly.report_date))).where(
                TrafficHourly.shop_id == shop_id
            )
        )
        or 0
    )
    grouped = (
        await session.execute(
            select(
                TrafficHourly.report_date,
                TrafficHourly.hour,
                TrafficHourly.visitor_count,
            ).where(TrafficHourly.shop_id == shop_id)
        )
    ).all()

    totals: dict[tuple[int, int], list[int]] = {}
    for report_date, hour, visitors in grouped:
        weekday = report_date.isoweekday()
        totals.setdefault((weekday, int(hour)), []).append(int(visitors or 0))

    rows: list[dict[str, Any]] = []
    peak = 0.0
    for weekday in range(1, 8):
        hours: list[float] = []
        for hour in range(24):
            samples = totals.get((weekday, hour), [])
            average = round(sum(samples) / len(samples), 1) if samples else 0.0
            hours.append(average)
            if average > peak:
                peak = average
        rows.append({"weekday": weekday, "hours": hours})

    return {
        "shop_id": shop_id,
        "day_count": day_count,
        "max_visitors": peak,
        "rows": rows,
    }
