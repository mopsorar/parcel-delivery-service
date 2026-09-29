from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from parcel_delivery.api.parcels import router as parcels_router
from parcel_delivery.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(parcels_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"state": "healthy"}
