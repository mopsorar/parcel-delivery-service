from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ParcelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    weight: Annotated[Decimal, Field(gt=0)]
    type_id: Annotated[int, Field(gt=0)]
    content_value_usd: Annotated[Decimal, Field(gt=0)]


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
