import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vitrac_client import VitracAPIError, VitracClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _field(branch: dict, *names: str) -> str:
    for name in names:
        value = branch.get(name)
        if value is not None and str(value).strip() != "":
            return str(value)
    return "—"


async def main() -> None:
    client = VitracClient()
    try:
        branches = await client.get_branches()
    except VitracAPIError as exc:
        print(f"Failed to list Vitrac branches: {exc}")
        raise SystemExit(1) from exc
    finally:
        await client.aclose()

    if not branches:
        print("No Vitrac branches returned.")
        return

    print(f"Found {len(branches)} Vitrac branch(es):\n")
    print(f"{'key':<36}  {'status':<12}  name")
    print(f"{'-' * 36}  {'-' * 12}  {'-' * 24}")
    for branch in branches:
        key = _field(branch, "key", "branchKey", "branch_key", "id")
        name = _field(branch, "name", "branchName", "title")
        status = _field(branch, "status", "state")
        print(f"{key:<36}  {status:<12}  {name}")


if __name__ == "__main__":
    asyncio.run(main())
