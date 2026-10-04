import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from parcel_delivery.api.middleware import RequestLoggingMiddleware
from parcel_delivery.api.parcels import router as parcels_router
from parcel_delivery.db.session import engine
from parcel_delivery.integrations.redis import redis_client
from parcel_delivery.logging_config import configure_logging
from parcel_delivery.tasks.delivery_costs import run_delivery_cost_calculation_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    calculation_task = asyncio.create_task(
        run_delivery_cost_calculation_loop(),
        name="delivery-cost-calculation",
    )
    try:
        yield
    finally:
        calculation_task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await calculation_task
        finally:
            try:
                await redis_client.aclose()
            finally:
                await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(parcels_router)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
        headers={"X-Request-ID": request.state.request_id},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"state": "healthy"}
