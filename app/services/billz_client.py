from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.db import AsyncSessionLocal
from app.models.billz_token import BillzToken

logger = logging.getLogger(__name__)

SINGLE_TOKEN_ID = 1
ACCESS_REFRESH_SKEW = timedelta(hours=1)
MAX_429_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 2, 4)


class BillzAPIError(Exception):
    pass


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _unwrap_payload(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            return data
        return body
    raise BillzAPIError(f"Unexpected BILLZ response body: {body!r}")


def _is_invalid_grant(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return "invalid_grant" in response.text
    return "invalid_grant" in str(body)


class BillzClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=settings.BILLZ_BASE_URL.rstrip("/"),
                timeout=30.0,
                headers={"Accept": "application/json"},
                trust_env=False,
            )
            self._owns_http = True
        return self._http

    async def login(self) -> BillzToken:
        if not settings.BILLZ_SECRET_KEY:
            raise BillzAPIError("BILLZ_SECRET_KEY is not set")

        logger.info("Logging in to BILLZ")
        response = await self._send(
            "POST",
            "/v1/auth/login",
            json={"secret_token": settings.BILLZ_SECRET_KEY},
        )
        if response.status_code >= 400:
            logger.error(
                "BILLZ login failed: %s %s",
                response.status_code,
                response.text,
            )
            raise BillzAPIError(
                f"BILLZ login failed with status {response.status_code}: {response.text}"
            )

        token = await self._store_token_response(response)
        logger.info("BILLZ login succeeded")
        return token

    async def refresh(self) -> BillzToken:
        current = await self._load_token()
        if current is None or not current.refresh_token:
            logger.info("No BILLZ refresh token stored; falling back to login")
            return await self.login()

        logger.info("Refreshing BILLZ access token")
        headers = {"platform-id": settings.BILLZ_PLATFORM_ID}
        response = await self._send(
            "POST",
            "/v2/auth/refresh",
            json={"refresh_token": current.refresh_token},
            headers=headers,
        )

        if response.status_code == 400 or _is_invalid_grant(response):
            logger.warning(
                "BILLZ refresh failed (%s, invalid_grant or 400): %s; falling back to login",
                response.status_code,
                response.text,
            )
            return await self.login()

        if response.status_code >= 400:
            logger.error(
                "BILLZ refresh failed: %s %s",
                response.status_code,
                response.text,
            )
            raise BillzAPIError(
                f"BILLZ refresh failed with status {response.status_code}: {response.text}"
            )

        token = await self._store_token_response(response)
        logger.info("BILLZ token refresh succeeded")
        return token

    async def get_access_token(self) -> str:
        token = await self._load_token()
        now = datetime.now(timezone.utc)
        expires_at = _as_utc(token.access_expires_at) if token else None
        needs_refresh = (
            token is None
            or expires_at is None
            or expires_at <= now + ACCESS_REFRESH_SKEW
        )

        if needs_refresh:
            if token is None or not token.refresh_token:
                token = await self.login()
            else:
                token = await self.refresh()

        if not token.access_token:
            raise BillzAPIError("BILLZ access token is empty after login/refresh")
        return token.access_token

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        token = await self.get_access_token()
        response = await self._send(
            method,
            path,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code == 401:
            logger.warning("BILLZ returned 401; refreshing token and retrying once")
            refreshed = await self.refresh()
            response = await self._send(
                method,
                path,
                params=params,
                headers={"Authorization": f"Bearer {refreshed.access_token}"},
            )

        if response.status_code >= 400:
            logger.error(
                "BILLZ request failed: %s %s -> %s %s",
                method,
                path,
                response.status_code,
                response.text,
            )
            raise BillzAPIError(
                f"BILLZ request failed with status {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise BillzAPIError("BILLZ returned a non-JSON response") from exc

    async def get_sales_report(
        self,
        start_date: str,
        end_date: str,
        shop_ids: list[str] | None,
        detalization: str = "hour",
        currency: str = "UZS",
        limit: int = 50,
        page: int = 1,
    ) -> Any:
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "detalization": detalization,
            "currency": currency,
            "limit": limit,
            "page": page,
        }
        if shop_ids:
            params["shop_ids"] = ",".join(shop_ids)
        return await self.request("GET", "/v1/general-report-table", params=params)

    async def get_transaction_report(
        self,
        start_date: str,
        end_date: str,
        shop_ids: list[str] | None,
        page: int = 1,
        limit: int = 100,
    ) -> Any:
        params: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "page": page,
        }
        if shop_ids:
            params["shop_ids"] = ",".join(shop_ids)
        return await self.request("GET", "/v1/transaction-report-table", params=params)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        http = await self._get_http()
        response: httpx.Response | None = None
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                response = await http.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                logger.error("BILLZ HTTP error on %s %s: %s", method, path, exc)
                raise BillzAPIError(f"BILLZ request error: {exc}") from exc

            if response.status_code != 429 or attempt >= MAX_429_RETRIES:
                return response

            delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "BILLZ rate limited (429) on %s %s; retry %s/%s in %ss",
                method,
                path,
                attempt + 1,
                MAX_429_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)

        assert response is not None
        return response

    async def _load_token(self) -> BillzToken | None:
        async with AsyncSessionLocal() as session:
            return await session.get(BillzToken, SINGLE_TOKEN_ID)

    async def _store_token_response(self, response: httpx.Response) -> BillzToken:
        try:
            body = response.json()
        except ValueError as exc:
            raise BillzAPIError("BILLZ token response was not JSON") from exc

        payload = _unwrap_payload(body)
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not access_token or not refresh_token:
            raise BillzAPIError(f"BILLZ token response missing tokens: {payload}")

        now = datetime.now(timezone.utc)
        expires_in = int(payload.get("expires_in") or 0)
        refresh_expires_in = int(payload.get("refresh_expires_in") or expires_in)
        if expires_in <= 0:
            raise BillzAPIError("BILLZ token response missing expires_in")

        access_expires_at = now + timedelta(seconds=expires_in)
        refresh_expires_at = now + timedelta(seconds=refresh_expires_in)

        async with AsyncSessionLocal() as session:
            token = await session.get(BillzToken, SINGLE_TOKEN_ID)
            if token is None:
                token = BillzToken(id=SINGLE_TOKEN_ID)
                session.add(token)
            token.access_token = str(access_token)
            token.refresh_token = str(refresh_token)
            token.access_expires_at = access_expires_at
            token.refresh_expires_at = refresh_expires_at
            token.updated_at = now
            await session.commit()
            await session.refresh(token)
            return token


billz_client = BillzClient()
