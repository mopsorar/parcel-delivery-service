from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from parcel_delivery.api.dependencies import get_session_id
from parcel_delivery.api.schemas import (
    POSTGRES_INTEGER_MAX,
    DeliveryCostCalculationResponse,
    ParcelCreate,
    ParcelCreateResponse,
    ParcelResponse,
    ParcelTypeResponse,
    TransportCompanyAssignmentRequest,
    TransportCompanyAssignmentResponse,
)
from parcel_delivery.db.dependencies import get_db_session
from parcel_delivery.db.models import ParcelType
from parcel_delivery.integrations.exchange_rates import ExchangeRateError
from parcel_delivery.services.delivery_costs import calculate_pending_delivery_costs
from parcel_delivery.services.parcels import (
    ParcelAlreadyAssignedError,
    ParcelNotFoundError,
    ParcelTypeNotFoundError,
    assign_transport_company,
    create_parcel,
    get_parcel_by_id,
    get_parcel_types,
    get_parcels_by_session,
)

router = APIRouter()


@router.get(
    "/parcel-types",
    response_model=list[ParcelTypeResponse],
    status_code=status.HTTP_200_OK,
)
async def list_parcel_types(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ParcelType]:
    return await get_parcel_types(db)


@router.get(
    "/parcels",
    response_model=list[ParcelResponse],
    status_code=status.HTTP_200_OK,
)
async def list_parcels(
    session_id: Annotated[UUID, Depends(get_session_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=POSTGRES_INTEGER_MAX)] = 0,
    type_id: Annotated[int | None, Query(gt=0, le=POSTGRES_INTEGER_MAX)] = None,
    delivery_cost_calculated: Annotated[bool | None, Query()] = None,
) -> list[ParcelResponse]:
    parcels = await get_parcels_by_session(
        db,
        session_id,
        limit,
        offset,
        type_id,
        delivery_cost_calculated,
    )
    return [ParcelResponse.model_validate(parcel) for parcel in parcels]


@router.post(
    "/parcels/calculate-delivery-costs",
    response_model=DeliveryCostCalculationResponse,
    status_code=status.HTTP_200_OK,
    summary="Debug: calculate delivery costs for one pending batch",
)
async def calculate_parcel_delivery_costs(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeliveryCostCalculationResponse:
    try:
        processed_count = await calculate_pending_delivery_costs(db)
    except ExchangeRateError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to retrieve USD/RUB exchange rate",
        ) from error
    return DeliveryCostCalculationResponse(processed_count=processed_count)


@router.get(
    "/parcels/{parcel_id}",
    response_model=ParcelResponse,
    status_code=status.HTTP_200_OK,
)
async def get_parcel(
    parcel_id: Annotated[int, Path(gt=0, le=POSTGRES_INTEGER_MAX)],
    session_id: Annotated[UUID, Depends(get_session_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ParcelResponse:
    try:
        parcel = await get_parcel_by_id(db, parcel_id, session_id)
    except ParcelNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return ParcelResponse.model_validate(parcel)


@router.post(
    "/parcels/{parcel_id}/transport-company",
    response_model=TransportCompanyAssignmentResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Parcel not found in the current session"},
        409: {"description": "Transport company is already assigned"},
    },
)
async def assign_parcel_transport_company(
    parcel_id: Annotated[int, Path(gt=0, le=POSTGRES_INTEGER_MAX)],
    assignment: TransportCompanyAssignmentRequest,
    session_id: Annotated[UUID, Depends(get_session_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransportCompanyAssignmentResponse:
    try:
        result = await assign_transport_company(db, parcel_id, session_id, assignment.company_id)
    except ParcelNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ParcelAlreadyAssignedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return TransportCompanyAssignmentResponse.model_validate(result)


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
