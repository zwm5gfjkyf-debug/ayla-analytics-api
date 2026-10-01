from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MAX_429_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 2, 4)


class VitracAPIError(Exception):
    pass


class VitracClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _get_http(self) -> httpx.AsyncClient:
        if not settings.TASSVISION_API_KEY:
            raise VitracAPIError("TASSVISION_API_KEY is not set")

        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=settings.TASSVISION_BASE_URL.rstrip("/"),
                timeout=30.0,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {settings.TASSVISION_API_KEY}",
                },
                trust_env=False,
            )
            self._owns_http = True
        return self._http

    async def get_branches(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/v1/branches")
        branches = _as_list(body, keys=("data", "branches", "items", "result"))
        if branches is None:
            raise VitracAPIError(f"Unexpected Vitrac branches response: {body!r}")
        return branches

    async def get_indoor_hourly(
        self,
        branch_key: str,
        start_date: str,
        end_date: str,
        entrance_key: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "branchKey": branch_key,
            "startDate": start_date,
            "endDate": end_date,
        }
        if entrance_key:
            params["entranceKey"] = entrance_key
        return await self._request("GET", "/v1/indoor/hourly", params=params)

    async def get_indoor_groups_hourly_aggregated(
        self,
        branch_key: str,
        start_date: str,
        end_date: str,
        entrance_key: str | None = None,
    ) -> Any:
        params: dict[str, str] = {
            "branchKey": branch_key,
            "startDate": start_date,
            "endDate": end_date,
        }
        if entrance_key:
            params["entranceKey"] = entrance_key
        return await self._request(
            "GET",
            "/v1/indoor/groups/hourly-aggregated",
            params=params,
        )

    async def get_indoor_daily(
        self,
        branch_key: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return await self._request(
            "GET",
            "/v1/indoor/daily",
            params={
                "branchKey": branch_key,
                "startDate": start_date,
                "endDate": end_date,
            },
        )

    async def get_outdoor_hourly(
        self,
        branch_key: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return await self._request(
            "GET",
            "/v1/outdoor/hourly",
            params={
                "branchKey": branch_key,
                "startDate": start_date,
                "endDate": end_date,
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await self._send(method, path, params=params)
        if response.status_code >= 400:
            logger.error(
                "Vitrac request failed: %s %s -> %s %s",
                method,
                path,
                response.status_code,
                response.text,
            )
            raise VitracAPIError(
                f"Vitrac request failed with status {response.status_code}: {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise VitracAPIError("Vitrac returned a non-JSON response") from exc

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        http = await self._get_http()
        response: httpx.Response | None = None
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                response = await http.request(method, path, params=params)
            except httpx.HTTPError as exc:
                logger.error("Vitrac HTTP error on %s %s: %s", method, path, exc)
                raise VitracAPIError(f"Vitrac request error: {exc}") from exc

            if response.status_code != 429 or attempt >= MAX_429_RETRIES:
                return response

            delay = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "Vitrac rate limited (429) on %s %s; retry %s/%s in %ss",
                method,
                path,
                attempt + 1,
                MAX_429_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)

        assert response is not None
        return response


def _as_list(body: Any, keys: tuple[str, ...]) -> list[dict[str, Any]] | None:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return None
    for key in keys:
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return None


vitrac_client = VitracClient()
