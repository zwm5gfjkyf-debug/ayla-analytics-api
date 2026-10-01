from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.billz_client import BillzAPIError, billz_client
from app.services.sales_sync import sync_daily_sales, sync_hourly_sales

router = APIRouter(prefix="/billz", tags=["billz"])


def _parse_shop_ids(shop_ids: str | None) -> list[str] | None:
    if not shop_ids:
        return None
    ids = [part.strip() for part in shop_ids.split(",") if part.strip()]
    return ids or None


@router.get("/sales")
async def get_sales(
    start_date: str = Query(..., description="Report start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Report end date (YYYY-MM-DD)"),
    shop_ids: str | None = Query(
        None,
        description="Optional comma-separated shop IDs",
    ),
    detalization: str = Query("hour"),
) -> Any:
    try:
        return await billz_client.get_sales_report(
            start_date=start_date,
            end_date=end_date,
            shop_ids=_parse_shop_ids(shop_ids),
            detalization=detalization,
        )
    except BillzAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync-sales")
async def post_sync_sales(
    start_date: str = Query(..., description="Report start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="Report end date (YYYY-MM-DD)"),
    shop_ids: str | None = Query(
        None,
        description="Optional comma-separated shop IDs",
    ),
) -> dict[str, int]:
    try:
        return await sync_daily_sales(
            start_date=start_date,
            end_date=end_date,
            shop_ids=_parse_shop_ids(shop_ids),
        )
    except BillzAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync-hourly-sales")
async def post_sync_hourly_sales(
    date: str = Query(..., description="Report date (YYYY-MM-DD)"),
    shop_ids: str | None = Query(
        None,
        description="Optional comma-separated shop IDs",
    ),
) -> dict[str, int]:
    try:
        return await sync_hourly_sales(
            report_date=date,
            shop_ids=_parse_shop_ids(shop_ids),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BillzAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
