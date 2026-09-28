import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from parcel_delivery.db.base import Base


class Parcel(Base):
    __tablename__ = "parcels"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_parcels_weight_positive"),
        CheckConstraint(
            "content_value_usd > 0",
            name="ck_parcels_content_value_usd_positive",
        ),
        Index("ix_parcels_session_id_type_id", "session_id", "type_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    type_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("parcel_types.id"),
        nullable=False,
    )
    content_value_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
