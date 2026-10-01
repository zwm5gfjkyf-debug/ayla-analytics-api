from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.models.daily_staffing import DailyStaffing
from app.models.hourly_cashier_activity import HourlyCashierActivity
from app.models.sales_hourly import SalesHourly
from app.models.sales_report import SalesReportDaily
from app.services.billz_client import BillzAPIError, BillzClient, billz_client

logger = logging.getLogger(__name__)

PAGE_SIZE = 100
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
AYLA_SHOP_ID = "588ac214-069a-42a7-8df6-b4bc8ac0cdfb"
DAILY_REFRESH_TTL = timedelta(seconds=45)
HOURLY_REFRESH_TTL = timedelta(seconds=45)
FAILED_REFRESH_TTL = timedelta(seconds=10)

_daily_refresh_lock = asyncio.Lock()
_daily_refresh_until: datetime | None = None
_daily_refresh_result: dict[str, Any] | None = None
_hourly_refresh_lock = asyncio.Lock()
_hourly_refresh_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}


def get_tashkent_today() -> date:
    return datetime.now(TASHKENT_TZ).date()


def range_overlaps_today_or_yesterday(start: date | None, end: date | None) -> bool:
    """True when a query window includes Tashkent today or yesterday."""
    if start is None or end is None:
        return True
    today = get_tashkent_today()
    yesterday = today - timedelta(days=1)
    return start <= today and end >= yesterday


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _as_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _as_optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("shop_stats_by_date")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("shop_stats_by_date"), list):
        return [row for row in data["shop_stats_by_date"] if isinstance(row, dict)]
    return []


def _extract_transaction_rows(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        return [], 0
    rows = payload.get("rows")
    if not isinstance(rows, list):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            rows = data["rows"]
        else:
            rows = []
    parsed = [row for row in rows if isinstance(row, dict)]
    count = payload.get("count")
    if count is None:
        data = payload.get("data")
        if isinstance(data, dict):
            count = data.get("count")
    return parsed, _as_int(count)


def _order_kind(order_type: Any) -> str:
    label = str(order_type or "").strip().casefold()
    if label in {"возврат", "return"}:
        return "return"
    if label in {"обмен", "exchange"}:
        return "exchange"
    return "sale"


def _normalize_name(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cashier_entry(raw: dict[str, Any]) -> tuple[str, str] | None:
    cashier_id = str(raw.get("cashier_id") or "").strip()
    name = _normalize_name(raw.get("cashier_name"))
    if not cashier_id and not name:
        return None
    return cashier_id or name, name or cashier_id


def _hour_from_timestamp(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("T", " ", 1)
    try:
        parsed = datetime.strptime(normalized[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.hour


async def _fetch_transaction_rows(
    client: BillzClient,
    start_date: str,
    end_date: str,
    shop_ids: list[str] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while True:
        payload = await client.get_transaction_report(
            start_date=start_date,
            end_date=end_date,
            shop_ids=shop_ids,
            page=page,
            limit=PAGE_SIZE,
        )
        batch, count = _extract_transaction_rows(payload)
        if total is None and count > 0:
            total = count
        rows.extend(batch)
        if not batch:
            break
        if total is not None and len(rows) >= total:
            break
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return rows


async def _fetch_daily_rows(
    client: BillzClient,
    start_date: str,
    end_date: str,
    shop_ids: list[str] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = await client.get_sales_report(
            start_date=start_date,
            end_date=end_date,
            shop_ids=shop_ids,
            detalization="day",
            limit=PAGE_SIZE,
            page=page,
        )
        batch = _extract_rows(payload)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return rows


async def sync_daily_sales(
    start_date: str,
    end_date: str,
    shop_ids: list[str] | None = None,
    client: BillzClient | None = None,
) -> dict[str, int]:
    client = client or billz_client
    raw_rows = await _fetch_daily_rows(client, start_date, end_date, shop_ids)
    now = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()

    for raw in raw_rows:
        shop_id = str(raw.get("shop_id") or "").strip()
        report_date = _as_date(raw.get("date"))
        if not shop_id or report_date is None:
            logger.warning("Skipping sales row missing shop_id or date: %s", raw)
            continue
        key = (shop_id, report_date)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "shop_id": shop_id,
                "shop_name": str(raw.get("shop_name") or ""),
                "report_date": report_date,
                "gross_sales": _as_decimal(raw.get("gross_sales")),
                "net_gross_sales": _as_decimal(raw.get("net_gross_sales")),
                "discount_sum": _as_decimal(raw.get("discount_sum")),
                "gross_profit": _as_decimal(raw.get("gross_profit")),
                "transactions_count": _as_int(raw.get("transactions_count")),
                "orders_count": _as_int(raw.get("orders_count")),
                "returns_count": _as_int(raw.get("returns_count")),
                "exchanges_count": _as_int(raw.get("exchanges_count")),
                "average_cheque": _as_decimal(raw.get("average_cheque")),
                "products_sold": _as_int(raw.get("products_sold")),
                "target": _as_optional_decimal(raw.get("target")),
                "fetched_at": now,
            }
        )

    if not records:
        return {"inserted": 0, "updated": 0, "upserted": 0}

    async with AsyncSessionLocal() as session:
        existing_result = await session.execute(
            select(SalesReportDaily.shop_id, SalesReportDaily.report_date).where(
                SalesReportDaily.report_date.between(
                    date.fromisoformat(start_date),
                    date.fromisoformat(end_date),
                )
            )
        )
        existing = {(row.shop_id, row.report_date) for row in existing_result.all()}
        inserted = sum(
            1 for record in records if (record["shop_id"], record["report_date"]) not in existing
        )
        updated = len(records) - inserted

        stmt = insert(SalesReportDaily).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_sales_report_daily_shop_date",
            set_={
                "shop_name": stmt.excluded.shop_name,
                "gross_sales": stmt.excluded.gross_sales,
                "net_gross_sales": stmt.excluded.net_gross_sales,
                "discount_sum": stmt.excluded.discount_sum,
                "gross_profit": stmt.excluded.gross_profit,
                "transactions_count": stmt.excluded.transactions_count,
                "orders_count": stmt.excluded.orders_count,
                "returns_count": stmt.excluded.returns_count,
                "exchanges_count": stmt.excluded.exchanges_count,
                "average_cheque": stmt.excluded.average_cheque,
                "products_sold": stmt.excluded.products_sold,
                "target": stmt.excluded.target,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await session.execute(stmt)
        await session.commit()

    logger.info(
        "Synced %s daily sales rows (%s inserted, %s updated)",
        len(records),
        inserted,
        updated,
    )
    return {"inserted": inserted, "updated": updated, "upserted": len(records)}


async def sync_hourly_sales(
    report_date: str,
    shop_ids: list[str] | None = None,
    client: BillzClient | None = None,
) -> dict[str, int]:
    """Build hourly buckets from BILLZ transaction-report-table for one date.

    ``total_price`` is already signed: sales are positive, returns are negative,
    and exchanges carry the cash difference (positive or negative). Summing it
    as-is is the net cash for the hour.
    """
    client = client or billz_client
    day = date.fromisoformat(report_date)
    raw_rows = await _fetch_transaction_rows(client, report_date, report_date, shop_ids)
    now = datetime.now(timezone.utc)
    buckets: dict[tuple[str, int], dict[str, Any]] = {}
    cashiers_by_shop: dict[str, dict[str, str]] = {}
    cashier_hours: dict[tuple[str, int, str], dict[str, Any]] = {}

    for raw in raw_rows:
        shop_id = str(raw.get("shop_id") or "").strip()
        hour = _hour_from_timestamp(raw.get("date"))
        if not shop_id:
            logger.warning("Skipping transaction row missing shop_id: %s", raw)
            continue
        cashier = _cashier_entry(raw)
        if cashier is not None:
            cashiers_by_shop.setdefault(shop_id, {})[cashier[0]] = cashier[1]
        if hour is None:
            logger.warning("Skipping transaction row missing date: %s", raw)
            continue
        if cashier is not None:
            cashier_key = (shop_id, hour, cashier[0])
            cashier_bucket = cashier_hours.get(cashier_key)
            if cashier_bucket is None:
                cashier_bucket = {
                    "shop_id": shop_id,
                    "report_date": day,
                    "hour": hour,
                    "cashier_id": cashier[0],
                    "cashier_name": cashier[1],
                    "transactions_count": 0,
                    "gross_sales": Decimal("0"),
                    "fetched_at": now,
                }
                cashier_hours[cashier_key] = cashier_bucket
            elif cashier[1]:
                cashier_bucket["cashier_name"] = cashier[1]
            cashier_bucket["transactions_count"] += 1
            cashier_bucket["gross_sales"] += _as_decimal(raw.get("total_price"))
        key = (shop_id, hour)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "shop_id": shop_id,
                "shop_name": str(raw.get("shop_name") or ""),
                "report_date": day,
                "hour": hour,
                "gross_sales": Decimal("0"),
                "transactions_count": 0,
                "returns_count": 0,
                "exchanges_count": 0,
                "fetched_at": now,
            }
            buckets[key] = bucket
        elif raw.get("shop_name"):
            bucket["shop_name"] = str(raw.get("shop_name"))

        bucket["gross_sales"] += _as_decimal(raw.get("total_price"))
        kind = _order_kind(raw.get("order_type"))
        if kind == "return":
            bucket["returns_count"] += 1
        elif kind == "exchange":
            bucket["exchanges_count"] += 1
        else:
            bucket["transactions_count"] += 1

    records = list(buckets.values())
    shop_ids_seen = {record["shop_id"] for record in records} | set(cashiers_by_shop)
    if shop_ids:
        shop_ids_seen |= set(shop_ids)

    staffing_records: list[dict[str, Any]] = []
    for shop_id in sorted(shop_ids_seen):
        names_by_id = cashiers_by_shop.get(shop_id, {})
        names = sorted(set(names_by_id.values()), key=str.casefold)
        staffing_records.append(
            {
                "shop_id": shop_id,
                "report_date": day,
                "distinct_cashier_count": len(names_by_id),
                "cashier_names": names,
                "fetched_at": now,
            }
        )

    cashier_records = list(cashier_hours.values())

    if not records and not staffing_records and not cashier_records:
        return {
            "inserted": 0,
            "updated": 0,
            "upserted": 0,
            "staffing_upserted": 0,
            "cashier_hour_upserted": 0,
        }

    async with AsyncSessionLocal() as session:
        inserted = 0
        updated = 0
        if records:
            existing_result = await session.execute(
                select(SalesHourly.shop_id, SalesHourly.hour).where(
                    SalesHourly.report_date == day
                )
            )
            existing = {(row.shop_id, row.hour) for row in existing_result.all()}
            inserted = sum(
                1 for record in records if (record["shop_id"], record["hour"]) not in existing
            )
            updated = len(records) - inserted

            stmt = insert(SalesHourly).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sales_hourly_shop_date_hour",
                set_={
                    "shop_name": stmt.excluded.shop_name,
                    "gross_sales": stmt.excluded.gross_sales,
                    "transactions_count": stmt.excluded.transactions_count,
                    "returns_count": stmt.excluded.returns_count,
                    "exchanges_count": stmt.excluded.exchanges_count,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            await session.execute(stmt)

        if staffing_records:
            staff_stmt = insert(DailyStaffing).values(staffing_records)
            staff_stmt = staff_stmt.on_conflict_do_update(
                constraint="uq_daily_staffing_shop_date",
                set_={
                    "distinct_cashier_count": staff_stmt.excluded.distinct_cashier_count,
                    "cashier_names": staff_stmt.excluded.cashier_names,
                    "fetched_at": staff_stmt.excluded.fetched_at,
                },
            )
            await session.execute(staff_stmt)

        if shop_ids_seen:
            await session.execute(
                delete(HourlyCashierActivity).where(
                    HourlyCashierActivity.report_date == day,
                    HourlyCashierActivity.shop_id.in_(list(shop_ids_seen)),
                )
            )
        if cashier_records:
            await session.execute(insert(HourlyCashierActivity).values(cashier_records))

        await session.commit()

    logger.info(
        "Synced %s hourly sales rows for %s (%s inserted, %s updated); staffing shops=%s cashier-hours=%s",
        len(records),
        report_date,
        inserted,
        updated,
        len(staffing_records),
        len(cashier_records),
    )
    return {
        "inserted": inserted,
        "updated": updated,
        "upserted": len(records),
        "staffing_upserted": len(staffing_records),
        "cashier_hour_upserted": len(cashier_records),
    }


async def refresh_hourly_if_recent(
    report_date: date,
    shop_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Re-sync hourly buckets for today/yesterday; skip settled historical dates."""
    today = get_tashkent_today()
    yesterday = today - timedelta(days=1)
    ids = shop_ids or [AYLA_SHOP_ID]
    if report_date not in (today, yesterday):
        logger.info(
            "Skipping hourly BILLZ refresh for settled date %s (today=%s)",
            report_date.isoformat(),
            today.isoformat(),
        )
        return {"ok": True, "skipped": True, "error": None}

    cache_key = (report_date.isoformat(), ",".join(sorted(ids)))
    now = datetime.now(timezone.utc)
    async with _hourly_refresh_lock:
        cached = _hourly_refresh_cache.get(cache_key)
        if cached is not None:
            expires_at, result = cached
            if now < expires_at:
                logger.info(
                    "Reusing hourly BILLZ refresh for %s (cached until %s)",
                    report_date.isoformat(),
                    expires_at.isoformat(),
                )
                return result

        day = report_date.isoformat()
        try:
            result = await sync_hourly_sales(report_date=day, shop_ids=ids)
            logger.info("Live hourly BILLZ refresh succeeded for %s: %s", day, result)
            payload = {"ok": True, "skipped": False, "error": None, **result}
            ttl = HOURLY_REFRESH_TTL
        except BillzAPIError:
            logger.exception("Live hourly BILLZ refresh failed for %s", day)
            payload = {"ok": False, "skipped": False, "error": "billz"}
            ttl = FAILED_REFRESH_TTL
        except Exception:
            logger.exception("Live hourly BILLZ refresh failed unexpectedly for %s", day)
            payload = {"ok": False, "skipped": False, "error": "unexpected"}
            ttl = FAILED_REFRESH_TTL

        _hourly_refresh_cache[cache_key] = (now + ttl, payload)
        return payload


async def refresh_today_and_yesterday() -> dict[str, Any]:
    today = get_tashkent_today()
    yesterday = today - timedelta(days=1)
    now = datetime.now(timezone.utc)

    async with _daily_refresh_lock:
        global _daily_refresh_until, _daily_refresh_result
        if (
            _daily_refresh_result is not None
            and _daily_refresh_until is not None
            and now < _daily_refresh_until
            and _daily_refresh_result.get("today") == today
        ):
            logger.info(
                "Reusing daily BILLZ refresh for %s–%s (cached until %s)",
                yesterday.isoformat(),
                today.isoformat(),
                _daily_refresh_until.isoformat(),
            )
            return _daily_refresh_result

        start = yesterday.isoformat()
        end = today.isoformat()
        try:
            result = await sync_daily_sales(start, end)
            logger.info("Live BILLZ refresh succeeded for %s–%s: %s", start, end, result)
            payload = {
                "ok": True,
                "today": today,
                "yesterday": yesterday,
                "error": None,
                **result,
            }
            ttl = DAILY_REFRESH_TTL
        except BillzAPIError:
            logger.exception("Live BILLZ refresh failed for %s–%s", start, end)
            payload = {
                "ok": False,
                "today": today,
                "yesterday": yesterday,
                "error": "billz",
                "inserted": 0,
                "updated": 0,
                "upserted": 0,
            }
            ttl = FAILED_REFRESH_TTL
        except Exception:
            logger.exception("Live BILLZ refresh failed unexpectedly for %s–%s", start, end)
            payload = {
                "ok": False,
                "today": today,
                "yesterday": yesterday,
                "error": "unexpected",
                "inserted": 0,
                "updated": 0,
                "upserted": 0,
            }
            ttl = FAILED_REFRESH_TTL

        _daily_refresh_result = payload
        _daily_refresh_until = now + ttl
        return payload
