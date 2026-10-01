from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.models.traffic_manual import TrafficManualDaily
from app.services.conversion import conversion_series, weekly_heatmap
from app.services.sales_sync import AYLA_SHOP_ID, get_tashkent_today, refresh_today_and_yesterday
from app.services.vitrac_client import VitracAPIError
from app.services.vitrac_sync import growth_payload, refresh_vitrac_hourly_range

router = APIRouter(prefix="/traffic", tags=["traffic"])


class ManualTrafficEntry(BaseModel):
    shop_id: str = Field(..., min_length=1)
    date: date
    visitor_count: int = Field(
        ...,
        ge=0,
        description="Individual guest headcount (male + female, workers excluded).",
    )


class ConversionRow(BaseModel):
    date: str
    visitor_count: int
    group_count: int
    transactions_count: int
    conversion_pct: float | None


@router.post("/manual-entry")
async def post_manual_entry(payload: ManualTrafficEntry) -> dict[str, str]:
    shop_id = payload.shop_id.strip()
    if not shop_id:
        raise HTTPException(status_code=400, detail="shop_id is required")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        stmt = insert(TrafficManualDaily).values(
            {
                "shop_id": shop_id,
                "report_date": payload.date,
                "visitor_count": payload.visitor_count,
                "fetched_at": now,
            }
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_traffic_manual_daily_shop_date",
            set_={
                "visitor_count": stmt.excluded.visitor_count,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await session.execute(stmt)
        await session.commit()

    return {"status": "ok", "shop_id": shop_id, "date": payload.date.isoformat()}


@router.get("/conversion", response_model=list[ConversionRow])
async def get_conversion(
    shop_id: str = Query(..., description="Shop UUID"),
) -> list[ConversionRow]:
    shop = shop_id.strip()
    if not shop:
        raise HTTPException(status_code=400, detail="shop_id is required")

    await refresh_today_and_yesterday()
    today = get_tashkent_today()
    try:
        await refresh_vitrac_hourly_range(shop, today - timedelta(days=30), today)
    except VitracAPIError:
        pass

    async with AsyncSessionLocal() as session:
        rows = await conversion_series(session, shop)

    return [ConversionRow(**row) for row in rows]


@router.get("/weekly-heatmap")
async def get_weekly_heatmap(
    shop_id: str = Query(default=AYLA_SHOP_ID, description="Shop UUID"),
) -> dict:
    shop = shop_id.strip() or AYLA_SHOP_ID
    today = get_tashkent_today()
    try:
        await refresh_vitrac_hourly_range(shop, today - timedelta(days=13), today)
    except VitracAPIError:
        pass

    async with AsyncSessionLocal() as session:
        return await weekly_heatmap(session, shop)


@router.get("/growth")
async def get_growth(
    date: date = Query(..., description="Report date (YYYY-MM-DD)"),
    shop_id: str = Query(default=AYLA_SHOP_ID, description="Shop UUID"),
) -> dict:
    shop = shop_id.strip() or AYLA_SHOP_ID
    return await growth_payload(date, shop)
