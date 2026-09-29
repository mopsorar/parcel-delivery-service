from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.api.schemas import ParcelCreate
from parcel_delivery.db.models import Parcel, ParcelType


class ParcelTypeNotFoundError(Exception):
    def __init__(self, type_id: int) -> None:
        self.type_id = type_id
        super().__init__(f"Parcel type with id {type_id} was not found")


async def get_parcel_type_by_id(session: AsyncSession, type_id: int) -> ParcelType:
    parcel_type = await session.scalar(select(ParcelType).where(ParcelType.id == type_id))
    if parcel_type is None:
        raise ParcelTypeNotFoundError(type_id)

    return parcel_type


async def create_parcel(
    db: AsyncSession,
    parcel_data: ParcelCreate,
    session_id: UUID,
) -> Parcel:
    await get_parcel_type_by_id(db, parcel_data.type_id)

    parcel = Parcel(
        name=parcel_data.name,
        weight=parcel_data.weight,
        type_id=parcel_data.type_id,
        content_value_usd=parcel_data.content_value_usd,
        session_id=session_id,
    )
    db.add(parcel)
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise

    await db.refresh(parcel)
    return parcel
