from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.sales_hourly import SalesHourly
from app.models.sales_report import SalesReportDaily
from app.models.traffic_hourly import TrafficHourly
from app.services.conversion import conversion_pct
from app.services.sales_sync import AYLA_SHOP_ID, get_tashkent_today, refresh_hourly_if_recent
from app.services.vitrac_client import VitracAPIError, vitrac_client

logger = logging.getLogger(__name__)

_refresh_lock = asyncio.Lock()
_refresh_cache: dict[str, tuple[datetime, None]] = {}
CACHE_SECONDS = 45
AYLA_BRANCH_NAME = "Shodlik"


def _pad24(values: Any) -> list[int]:
    if not isinstance(values, list):
        return [0] * 24
    out: list[int] = []
    for index in range(24):
        if index >= len(values):
            out.append(0)
            continue
        try:
            out.append(max(0, int(values[index] or 0)))
        except (TypeError, ValueError):
            out.append(0)
    return out


def _unwrap_rows(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            return [data]
    return []


def branch_key_for_shop(shop_id: str) -> str | None:
    if shop_id == AYLA_SHOP_ID:
        return settings.AYLA_VITRAC_BRANCH_KEY.strip() or None
    return None


def _groups_hours_by_date(body: Any) -> dict[str, list[int]]:
    hours_by_date: dict[str, list[int]] = {}
    for row in _unwrap_rows(body):
        raw_date = str(row.get("date") or "")
        if not raw_date:
            continue
        hours_by_date[raw_date] = _pad24(row.get("hours"))
    return hours_by_date


async def _upsert_indoor_days(
    shop_id: str,
    rows: list[dict[str, Any]],
    groups_by_date: dict[str, list[int]] | None = None,
) -> list[str]:
    fetched_at = datetime.now(timezone.utc)
    stored: list[str] = []
    groups_by_date = groups_by_date or {}
    async with AsyncSessionLocal() as session:
        for row in rows:
            raw_date = str(row.get("date") or "")
            try:
                report_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            breakdown = row.get("hourlyBreakdown") or {}
            male = _pad24(breakdown.get("male"))
            female = _pad24(breakdown.get("female"))
            workers = _pad24(breakdown.get("workers"))
            groups = groups_by_date.get(raw_date)
            for hour in range(24):
                # Conversion denominator: guests only (male + female). Workers excluded.
                visitors = male[hour] + female[hour]
                values: dict[str, Any] = {
                    "shop_id": shop_id,
                    "report_date": report_date,
                    "hour": hour,
                    "visitor_count": visitors,
                    "male_count": male[hour],
                    "female_count": female[hour],
                    "worker_count": workers[hour],
                    "fetched_at": fetched_at,
                }
                if groups is not None:
                    values["group_count"] = groups[hour]
                stmt = insert(TrafficHourly).values(values)
                set_: dict[str, Any] = {
                    "visitor_count": stmt.excluded.visitor_count,
                    "male_count": stmt.excluded.male_count,
                    "female_count": stmt.excluded.female_count,
                    "worker_count": stmt.excluded.worker_count,
                    "fetched_at": stmt.excluded.fetched_at,
                }
                if groups is not None:
                    set_["group_count"] = stmt.excluded.group_count
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_traffic_hourly_shop_date_hour",
                    set_=set_,
                )
                await session.execute(stmt)
            stored.append(report_date.isoformat())
        await session.commit()
    return stored


async def refresh_vitrac_hourly(report_date: date, shop_id: str) -> None:
    await refresh_vitrac_hourly_range(shop_id, report_date, report_date)


async def refresh_vitrac_hourly_range(shop_id: str, start: date, end: date) -> None:
    branch_key = branch_key_for_shop(shop_id)
    if not branch_key:
        return
    if end < start:
        start, end = end, start

    cache_key = f"{shop_id}:{start.isoformat()}:{end.isoformat()}"
    now = datetime.now(timezone.utc)
    async with _refresh_lock:
        cached = _refresh_cache.get(cache_key)
        if cached is not None and now < cached[0]:
            return
        try:
            body = await vitrac_client.get_indoor_hourly(
                branch_key,
                start.isoformat(),
                end.isoformat(),
            )
            groups_by_date: dict[str, list[int]] = {}
            try:
                groups_body = await vitrac_client.get_indoor_groups_hourly_aggregated(
                    branch_key,
                    start.isoformat(),
                    end.isoformat(),
                )
                groups_by_date = _groups_hours_by_date(groups_body)
            except VitracAPIError:
                logger.exception(
                    "Vitrac indoor groups refresh failed for %s–%s",
                    start.isoformat(),
                    end.isoformat(),
                )
            stored = await _upsert_indoor_days(
                shop_id,
                _unwrap_rows(body),
                groups_by_date,
            )
            _refresh_cache[cache_key] = (now + timedelta(seconds=CACHE_SECONDS), None)
            logger.info(
                "Vitrac hourly refresh succeeded for %s–%s (%s): %s days",
                start.isoformat(),
                end.isoformat(),
                shop_id,
                len(stored),
            )
        except VitracAPIError:
            logger.exception(
                "Vitrac hourly refresh failed for %s–%s",
                start.isoformat(),
                end.isoformat(),
            )
            raise


async def _outdoor_visitors(shop_id: str, report_date: date) -> int:
    branch_key = branch_key_for_shop(shop_id)
    if not branch_key:
        return 0
    day = report_date.isoformat()
    try:
        body = await vitrac_client.get_outdoor_hourly(branch_key, day, day)
    except VitracAPIError:
        logger.exception("Vitrac outdoor hourly failed for %s", day)
        return 0

    total = 0
    for row in _unwrap_rows(body):
        counts = row.get("totalCounts")
        if isinstance(counts, dict):
            if counts.get("total") is not None:
                total += max(0, int(counts.get("total") or 0))
                continue
            total += max(0, int(counts.get("male") or 0) + int(counts.get("female") or 0))
            continue
        breakdown = row.get("hourlyBreakdown")
        if not isinstance(breakdown, dict):
            continue
        if "total" in breakdown:
            total += sum(_pad24(breakdown.get("total")))
        elif "passing" in breakdown:
            total += sum(_pad24(breakdown.get("passing")))
        else:
            total += sum(_pad24(breakdown.get("male"))) + sum(_pad24(breakdown.get("female")))
    return total


async def _week_visitors_from_vitrac(
    shop_id: str,
    start: date,
    end: date,
) -> dict[date, int]:
    branch_key = branch_key_for_shop(shop_id)
    if not branch_key:
        return {}
    try:
        body = await vitrac_client.get_indoor_daily(
            branch_key,
            start.isoformat(),
            end.isoformat(),
        )
    except VitracAPIError:
        logger.exception("Vitrac daily refresh failed for %s–%s", start, end)
        return {}

    visitors: dict[date, int] = {}
    for row in _unwrap_rows(body):
        raw_date = str(row.get("date") or "")
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        counts = row.get("totalCounts") if isinstance(row.get("totalCounts"), dict) else {}
        male = int(counts.get("male") or 0)
        female = int(counts.get("female") or 0)
        visitors[day] = max(0, male + female)
    return visitors


async def growth_payload(report_date: date, shop_id: str) -> dict[str, Any]:
    await refresh_hourly_if_recent(report_date, shop_ids=[shop_id])
    vitrac_ok = True
    week_start = report_date - timedelta(days=6)
    try:
        await refresh_vitrac_hourly_range(shop_id, week_start, report_date)
    except VitracAPIError:
        vitrac_ok = False

    daily_visitors = await _week_visitors_from_vitrac(shop_id, week_start, report_date)
    async with AsyncSessionLocal() as session:
        hours = await _load_hours(session, shop_id, report_date)
        sales_day = await session.scalar(
            select(SalesReportDaily).where(
                SalesReportDaily.shop_id == shop_id,
                SalesReportDaily.report_date == report_date,
            )
        )
        recent_sales = (
            await session.execute(
                select(SalesReportDaily).where(
                    SalesReportDaily.shop_id == shop_id,
                    SalesReportDaily.report_date >= week_start,
                    SalesReportDaily.report_date <= report_date,
                )
            )
        ).scalars().all()
        recent_traffic = (
            await session.execute(
                select(
                    TrafficHourly.report_date,
                    TrafficHourly.visitor_count,
                    TrafficHourly.group_count,
                ).where(
                    TrafficHourly.shop_id == shop_id,
                    TrafficHourly.report_date >= week_start,
                    TrafficHourly.report_date <= report_date,
                )
            )
        ).all()

    sales_by_date = {row.report_date: row for row in recent_sales}
    hourly_sums: dict[date, int] = {}
    hourly_groups: dict[date, int] = {}
    for day, count, groups in recent_traffic:
        hourly_sums[day] = hourly_sums.get(day, 0) + int(count or 0)
        hourly_groups[day] = hourly_groups.get(day, 0) + int(groups or 0)
    visitors_by_date: dict[date, int] = dict(daily_visitors)
    visitors_by_date.update({day: total for day, total in hourly_sums.items() if total > 0})

    hourly_transactions = sum(row["transactions"] for row in hours)
    hourly_net_sales = sum(row["net_sales"] for row in hours)
    daily_transactions = int(sales_day.transactions_count or 0) if sales_day else 0
    if daily_transactions > 0:
        transactions = daily_transactions
        net_sales = float(sales_day.net_gross_sales or 0) if sales_day else hourly_net_sales
        average_cheque = float(sales_day.average_cheque or 0) if sales_day else 0.0
    else:
        transactions = hourly_transactions
        net_sales = hourly_net_sales
        average_cheque = (net_sales / transactions) if transactions else 0.0

    recent = []
    cursor = week_start
    while cursor <= report_date:
        visitors = visitors_by_date.get(cursor, 0)
        sale = sales_by_date.get(cursor)
        day_transactions = int(sale.transactions_count or 0) if sale else 0
        day_net_sales = float(sale.net_gross_sales or 0) if sale else 0.0
        if cursor == report_date and day_transactions == 0:
            day_transactions = hourly_transactions
            day_net_sales = hourly_net_sales
        recent.append(
            {
                "date": cursor.isoformat(),
                "visitors": visitors,
                "groups": hourly_groups.get(cursor, 0),
                "transactions": day_transactions,
                "net_sales": round(day_net_sales, 2),
                "conversion_pct": conversion_pct(day_transactions, visitors),
            }
        )
        cursor += timedelta(days=1)

    visitors = sum(row["visitors"] for row in hours)
    groups = sum(row["groups"] for row in hours)
    male = sum(row["male"] for row in hours)
    female = sum(row["female"] for row in hours)
    workers = sum(row["workers"] for row in hours)
    conversion = conversion_pct(transactions, visitors)
    busy_hours = [row for row in hours if row["visitors"] > 0]
    avg_visitors = (sum(row["visitors"] for row in busy_hours) / len(busy_hours)) if busy_hours else 0
    avg_conversion = (
        sum(row["conversion_pct"] or 0 for row in busy_hours) / len(busy_hours)
        if busy_hours
        else 0
    )
    peak = max(hours, key=lambda row: row["visitors"], default=None)
    weak_hours = [
        row["hour"]
        for row in busy_hours
        if row["visitors"] >= avg_visitors
        and row["conversion_pct"] is not None
        and row["conversion_pct"] < avg_conversion
    ]

    today = get_tashkent_today()
    outdoor_visitors = await _outdoor_visitors(shop_id, report_date)
    denom = outdoor_visitors + visitors
    outdoor_pct = 0.0 if denom == 0 else round(100.0 * outdoor_visitors / denom, 1)

    return {
        "date": report_date.isoformat(),
        "shop_id": shop_id,
        "shop_name": "Ayla",
        "branch_name": AYLA_BRANCH_NAME,
        "vitrac_ok": vitrac_ok,
        "is_live": report_date in (today, today - timedelta(days=1)),
        "visitors": visitors,
        "groups": groups,
        "male": male,
        "female": female,
        "workers": workers,
        "outdoor_visitors": outdoor_visitors,
        "outdoor_pct": outdoor_pct,
        "transactions": transactions,
        "net_sales": round(net_sales, 2),
        "average_cheque": round(average_cheque, 2),
        "conversion_pct": conversion,
        "sales_per_visitor": round(net_sales / visitors, 2) if visitors else None,
        "peak_hour": peak["hour"] if peak and peak["visitors"] else None,
        "peak_visitors": peak["visitors"] if peak else 0,
        "weak_hours": weak_hours,
        "hours": hours,
        "recent": recent,
    }


async def _load_hours(session: AsyncSession, shop_id: str, report_date: date) -> list[dict[str, Any]]:
    traffic_rows = (
        await session.execute(
            select(TrafficHourly)
            .where(
                TrafficHourly.shop_id == shop_id,
                TrafficHourly.report_date == report_date,
            )
            .order_by(TrafficHourly.hour)
        )
    ).scalars().all()
    sales_rows = (
        await session.execute(
            select(SalesHourly)
            .where(
                SalesHourly.shop_id == shop_id,
                SalesHourly.report_date == report_date,
            )
        )
    ).scalars().all()
    traffic_by_hour = {row.hour: row for row in traffic_rows}
    sales_by_hour = {row.hour: row for row in sales_rows}

    hours: list[dict[str, Any]] = []
    for hour in range(24):
        traffic = traffic_by_hour.get(hour)
        sale = sales_by_hour.get(hour)
        visitors = int(traffic.visitor_count) if traffic else 0
        groups = int(traffic.group_count) if traffic else 0
        male = int(traffic.male_count) if traffic else 0
        female = int(traffic.female_count) if traffic else 0
        workers = int(traffic.worker_count) if traffic else 0
        transactions = int(sale.transactions_count) if sale else 0
        net_sales = float(sale.gross_sales) if sale else 0.0
        hours.append(
            {
                "hour": hour,
                "label": f"{hour:02d}",
                "visitors": visitors,
                "groups": groups,
                "male": male,
                "female": female,
                "workers": workers,
                "transactions": transactions,
                "net_sales": round(net_sales, 2),
                "conversion_pct": conversion_pct(transactions, visitors),
            }
        )
    return hours
