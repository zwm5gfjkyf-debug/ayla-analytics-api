from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.access import AccessSession, AuthorizedPerson
from app.services.access import (
    bearer_token,
    best_match,
    create_session,
    hash_token,
    person_count,
    person_for_token,
    valid_embedding,
)

router = APIRouter(prefix="/access", tags=["access"])

MAX_THUMBNAIL = 180_000


class FacePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    embedding: list[float]
    thumbnail: str = Field(..., min_length=32, max_length=MAX_THUMBNAIL)


class UnlockPayload(BaseModel):
    embedding: list[float]


class PersonOut(BaseModel):
    id: int
    name: str
    thumbnail: str


def _require_data_url(thumbnail: str) -> None:
    if not thumbnail.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="thumbnail must be an image")


@router.get("/status")
async def access_status() -> dict[str, bool | int]:
    async with AsyncSessionLocal() as session:
        count = await person_count(session)
    return {"setup_required": count == 0, "enrolled_count": count}


@router.get("/me")
async def access_me(authorization: str | None = Header(default=None)) -> dict[str, str | int]:
    async with AsyncSessionLocal() as session:
        person = await person_for_token(session, bearer_token(authorization))
    if person is None:
        raise HTTPException(status_code=401, detail="locked")
    return {"id": person.id, "name": person.name}


@router.get("/people", response_model=list[PersonOut])
async def list_people(authorization: str | None = Header(default=None)) -> list[PersonOut]:
    async with AsyncSessionLocal() as session:
        count = await person_count(session)
        person = await person_for_token(session, bearer_token(authorization))
        if count > 0 and person is None:
            raise HTTPException(status_code=401, detail="locked")
        rows = (await session.scalars(select(AuthorizedPerson).order_by(AuthorizedPerson.id))).all()
    return [PersonOut(id=row.id, name=row.name, thumbnail=row.thumbnail) for row in rows]


@router.post("/people")
async def add_person(
    payload: FacePayload,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    if not valid_embedding(payload.embedding):
        raise HTTPException(status_code=400, detail="invalid_embedding")
    _require_data_url(payload.thumbnail)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    async with AsyncSessionLocal() as session:
        count = await person_count(session)
        current = await person_for_token(session, bearer_token(authorization))
        if count > 0 and current is None:
            raise HTTPException(status_code=401, detail="locked")

        row = AuthorizedPerson(
            name=name,
            embedding=[float(item) for item in payload.embedding],
            thumbnail=payload.thumbnail,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        token = await create_session(session, row.id)

    return {
        "token": token,
        "person": {"id": row.id, "name": row.name, "thumbnail": row.thumbnail},
    }


@router.delete("/people/{person_id}")
async def delete_person(
    person_id: int,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        current = await person_for_token(session, bearer_token(authorization))
        if current is None:
            raise HTTPException(status_code=401, detail="locked")
        row = await session.get(AuthorizedPerson, person_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        await session.delete(row)
        await session.commit()
    return {"status": "ok"}


@router.post("/unlock")
async def unlock(payload: UnlockPayload) -> dict[str, object]:
    if not valid_embedding(payload.embedding):
        raise HTTPException(status_code=400, detail="invalid_embedding")

    async with AsyncSessionLocal() as session:
        if await person_count(session) == 0:
            raise HTTPException(status_code=409, detail="setup_required")
        person, _distance = await best_match(session, [float(item) for item in payload.embedding])
        if person is None:
            raise HTTPException(status_code=403, detail="no_match")
        token = await create_session(session, person.id)

    return {"token": token, "name": person.name}


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    token = bearer_token(authorization)
    if token:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(AccessSession).where(AccessSession.token_hash == hash_token(token))
            )
            if row is not None:
                await session.delete(row)
                await session.commit()
    return {"status": "ok"}
