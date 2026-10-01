from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.daily_staffing import DailyStaffing
from app.models.hourly_cashier_activity import HourlyCashierActivity
from app.services.sales_sync import refresh_hourly_if_recent

router = APIRouter(prefix="/staffing", tags=["staffing"])


class DailyStaffingRow(BaseModel):
    shop_id: str
    date: str
    distinct_cashier_count: int
    cashier_names: list[str]


class HourlyCashierRow(BaseModel):
    cashier_id: str
    cashier_name: str
    transactions_count: int
    gross_sales: float


class HourlyStaffingBucket(BaseModel):
    hour: int
    cashiers: list[HourlyCashierRow]


class HourlyStaffingResponse(BaseModel):
    shop_id: str
    date: str
    hours: list[HourlyStaffingBucket]


@router.get("/daily", response_model=DailyStaffingRow)
async def get_daily_staffing(
    date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    shop_id: str = Query(..., description="Shop UUID"),
) -> DailyStaffingRow:
    shop = shop_id.strip()
    if not shop:
        raise HTTPException(status_code=400, detail="shop_id is required")

    await refresh_hourly_if_recent(date, shop_ids=[shop])

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(DailyStaffing).where(
                    DailyStaffing.shop_id == shop,
                    DailyStaffing.report_date == date,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="staffing_not_found")

    names = row.cashier_names if isinstance(row.cashier_names, list) else []
    return DailyStaffingRow(
        shop_id=row.shop_id,
        date=row.report_date.isoformat(),
        distinct_cashier_count=row.distinct_cashier_count,
        cashier_names=[str(name) for name in names],
    )


@router.get("/hourly", response_model=HourlyStaffingResponse)
async def get_hourly_staffing(
    date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    shop_id: str = Query(..., description="Shop UUID"),
) -> HourlyStaffingResponse:
    shop = shop_id.strip()
    if not shop:
        raise HTTPException(status_code=400, detail="shop_id is required")

    await refresh_hourly_if_recent(date, shop_ids=[shop])

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(HourlyCashierActivity)
            .where(
                HourlyCashierActivity.shop_id == shop,
                HourlyCashierActivity.report_date == date,
            )
            .order_by(HourlyCashierActivity.hour, HourlyCashierActivity.cashier_name)
        )
        rows = result.scalars().all()

    by_hour: dict[int, list[HourlyCashierRow]] = {hour: [] for hour in range(24)}
    for row in rows:
        by_hour[row.hour].append(
            HourlyCashierRow(
                cashier_id=row.cashier_id,
                cashier_name=row.cashier_name,
                transactions_count=row.transactions_count,
                gross_sales=float(row.gross_sales or 0),
            )
        )

    return HourlyStaffingResponse(
        shop_id=shop,
        date=date.isoformat(),
        hours=[HourlyStaffingBucket(hour=hour, cashiers=by_hour[hour]) for hour in range(24)],
    )

