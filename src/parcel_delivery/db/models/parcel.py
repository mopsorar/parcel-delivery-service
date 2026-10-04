import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from parcel_delivery.db.base import Base


class _CompanyId(TypeDecorator[int]):
    """Store large integer IDs exactly while exposing Python ints to the application."""

    impl = Numeric
    cache_ok = True

    def process_bind_param(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return Decimal(value) if value is not None else None

    def process_result_value(self, value: Decimal | None, dialect: Dialect) -> int | None:
        return int(value) if value is not None else None


class Parcel(Base):
    __tablename__ = "parcels"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_parcels_weight_positive"),
        CheckConstraint(
            "content_value_usd > 0",
            name="ck_parcels_content_value_usd_positive",
        ),
        CheckConstraint(
            "transport_company_id > 0 "
            "AND transport_company_id < 'Infinity'::numeric "
            "AND transport_company_id = trunc(transport_company_id)",
            name="ck_parcels_transport_company_id_positive_integer",
        ),
        Index("ix_parcels_session_id_type_id", "session_id", "type_id"),
        Index(
            "ix_parcels_pending_delivery_cost_id",
            "id",
            postgresql_where=text("delivery_cost_rub IS NULL"),
        ),
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
    transport_company_id: Mapped[int | None] = mapped_column(_CompanyId(), nullable=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
