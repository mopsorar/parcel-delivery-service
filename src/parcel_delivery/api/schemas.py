from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field

POSTGRES_INTEGER_MAX = 2**31 - 1


class ParcelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    weight: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=3)]
    type_id: Annotated[int, Field(gt=0, le=POSTGRES_INTEGER_MAX)]
    content_value_usd: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class ParcelCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int


class ParcelTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ParcelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    weight: Decimal
    type_id: int
    type_name: str
    content_value_usd: Decimal
    delivery_cost_rub: Decimal | None
    transport_company_id: int | None

    @computed_field
    @property
    def delivery_cost_display(self) -> str:
        if self.delivery_cost_rub is None:
            return "Не рассчитано"
        return f"{self.delivery_cost_rub:.2f}"


class DeliveryCostCalculationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processed_count: int


class TransportCompanyAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: Annotated[int, Field(gt=0, strict=True)]


class TransportCompanyAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: int
    transport_company_id: int
