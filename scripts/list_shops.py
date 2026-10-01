import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.billz_client import BillzAPIError, BillzClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    client = BillzClient()
    try:
        data = await client.request("GET", "/v1/shop")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except BillzAPIError as exc:
        print(f"Failed to list shops: {exc}")
        raise SystemExit(1) from exc
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
