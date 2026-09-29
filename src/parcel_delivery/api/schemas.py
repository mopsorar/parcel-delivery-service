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
