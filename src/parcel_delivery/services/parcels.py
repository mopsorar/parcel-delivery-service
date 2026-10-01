from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.api.schemas import ParcelCreate
from parcel_delivery.db.models import Parcel, ParcelType


class ParcelTypeNotFoundError(Exception):
    def __init__(self, type_id: int) -> None:
        self.type_id = type_id
        super().__init__(f"Parcel type with id {type_id} was not found")


class ParcelNotFoundError(Exception):
    def __init__(self, parcel_id: int) -> None:
        self.parcel_id = parcel_id
        super().__init__(f"Parcel with id {parcel_id} was not found")


async def get_parcel_types(db: AsyncSession) -> list[ParcelType]:
    parcel_types = await db.scalars(select(ParcelType).order_by(ParcelType.id))
    return list(parcel_types.all())


async def get_parcels_by_session(
    db: AsyncSession,
    session_id: UUID,
    limit: int,
    offset: int,
    type_id: int | None,
    delivery_cost_calculated: bool | None,
) -> list[RowMapping]:
    statement = (
        select(
            Parcel.id,
            Parcel.name,
            Parcel.weight,
            Parcel.type_id,
            ParcelType.name.label("type_name"),
            Parcel.content_value_usd,
            Parcel.delivery_cost_rub,
        )
        .join(ParcelType, Parcel.type_id == ParcelType.id)
        .where(Parcel.session_id == session_id)
    )

    if type_id is not None:
        statement = statement.where(Parcel.type_id == type_id)

    if delivery_cost_calculated is True:
        statement = statement.where(Parcel.delivery_cost_rub.is_not(None))
    elif delivery_cost_calculated is False:
        statement = statement.where(Parcel.delivery_cost_rub.is_(None))

    statement = statement.order_by(Parcel.id).offset(offset).limit(limit)
    result = await db.execute(statement)
    return list(result.mappings().all())


async def get_parcel_by_id(
    db: AsyncSession,
    parcel_id: int,
    session_id: UUID,
) -> RowMapping:
    result = await db.execute(
        select(
            Parcel.id,
            Parcel.name,
            Parcel.weight,
            Parcel.type_id,
            ParcelType.name.label("type_name"),
            Parcel.content_value_usd,
            Parcel.delivery_cost_rub,
        )
        .join(ParcelType, Parcel.type_id == ParcelType.id)
        .where(
            Parcel.id == parcel_id,
            Parcel.session_id == session_id,
        )
    )
    parcel = result.mappings().one_or_none()
    if parcel is None:
        raise ParcelNotFoundError(parcel_id)

    return parcel


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
