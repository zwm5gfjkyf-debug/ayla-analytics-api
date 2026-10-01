import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.billz_client import BillzAPIError, BillzClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    client = BillzClient()
    try:
        await client.login()
        print("BILLZ login succeeded")
    except BillzAPIError as exc:
        print(f"BILLZ login failed: {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"BILLZ login failed: {exc}")
        raise
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
