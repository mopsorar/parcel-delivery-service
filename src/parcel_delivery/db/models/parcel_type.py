from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from parcel_delivery.db.base import Base


class ParcelType(Base):
    __tablename__ = "parcel_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
