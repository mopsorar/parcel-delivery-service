from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.api.dependencies import get_session_id
from parcel_delivery.api.schemas import ParcelCreate, ParcelCreateResponse
from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.services.parcels import ParcelTypeNotFoundError, create_parcel

router = APIRouter()


@router.post(
    "/parcels",
    response_model=ParcelCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_parcel(
    parcel_data: ParcelCreate,
    session_id: Annotated[UUID, Depends(get_session_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ParcelCreateResponse:
    try:
        parcel = await create_parcel(db, parcel_data, session_id)
    except ParcelTypeNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return ParcelCreateResponse(id=parcel.id)
