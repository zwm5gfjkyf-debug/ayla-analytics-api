import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import billz, sales, staffing, traffic
from app.services.billz_client import billz_client
from app.services.vitrac_client import vitrac_client

_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _app_logger.addHandler(_handler)
_app_logger.setLevel(logging.INFO)
_app_logger.propagate = False

LOCAL_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


VERCEL_ORIGIN_REGEX = r"https://([a-z0-9-]+\.)+vercel\.app"


def allowed_cors_origins() -> list[str]:
    origins = list(LOCAL_CORS_ORIGINS)
    for raw in settings.CORS_ORIGINS.split(","):
        origin = raw.strip().rstrip("/")
        if not origin:
            continue
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        if origin not in origins:
            origins.append(origin)
    return origins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await billz_client.aclose()
    await vitrac_client.aclose()


app = FastAPI(title="Ayla Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_cors_origins(),
    allow_origin_regex=VERCEL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(billz.router)
app.include_router(sales.router)
app.include_router(staffing.router)
app.include_router(traffic.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
