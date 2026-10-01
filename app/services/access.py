from __future__ import annotations

import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import AccessSession, AuthorizedPerson

MATCH_MAX_DISTANCE = 0.52
SESSION_HOURS = 12
EMBEDDING_SIZE = 128


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def embedding_distance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 999.0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def valid_embedding(values: list[float]) -> bool:
    if len(values) != EMBEDDING_SIZE:
        return False
    return all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in values)


async def person_count(session: AsyncSession) -> int:
    result = await session.scalar(select(func.count()).select_from(AuthorizedPerson))
    return int(result or 0)


async def create_session(db: AsyncSession, person_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        AccessSession(
            token_hash=hash_token(token),
            person_id=person_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
        )
    )
    await db.commit()
    return token


async def person_for_token(db: AsyncSession, token: str | None) -> AuthorizedPerson | None:
    if not token:
        return None
    row = await db.scalar(
        select(AccessSession).where(
            AccessSession.token_hash == hash_token(token),
            AccessSession.expires_at > datetime.now(timezone.utc),
        )
    )
    if row is None:
        return None
    return await db.get(AuthorizedPerson, row.person_id)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    kind, _, value = authorization.partition(" ")
    if kind.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def best_match(
    db: AsyncSession,
    embedding: list[float],
) -> tuple[AuthorizedPerson | None, float]:
    people = (await db.scalars(select(AuthorizedPerson))).all()
    winner: AuthorizedPerson | None = None
    best = 999.0
    for person in people:
        stored = [float(item) for item in person.embedding]
        distance = embedding_distance(stored, embedding)
        if distance < best:
            best = distance
            winner = person
    if winner is None or best > MATCH_MAX_DISTANCE:
        return None, best
    return winner, best
