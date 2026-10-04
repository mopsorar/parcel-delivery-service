"""add transport company to parcel

Revision ID: a7c1e42b9d60
Revises: 6586eaff6f0e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1e42b9d60"
down_revision: str | Sequence[str] | None = "6586eaff6f0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("parcels", sa.Column("transport_company_id", sa.Numeric(), nullable=True))
    op.create_check_constraint(
        "ck_parcels_transport_company_id_positive_integer",
        "parcels",
        "transport_company_id > 0 "
        "AND transport_company_id < 'Infinity'::numeric "
        "AND transport_company_id = trunc(transport_company_id)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_parcels_transport_company_id_positive_integer", "parcels", type_="check")
    op.drop_column("parcels", "transport_company_id")
