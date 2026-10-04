"""seed parcel types

Revision ID: 6586eaff6f0e
Revises: 38e6bf8af41d
Create Date: 2026-09-29 19:55:42.887443

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "6586eaff6f0e"
down_revision: str | Sequence[str] | None = "38e6bf8af41d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

parcel_types = sa.table("parcel_types", sa.column("name", sa.String()))


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        insert(parcel_types)
        .values([{"name": "clothes"}, {"name": "electronics"}, {"name": "misc"}])
        .on_conflict_do_nothing(index_elements=["name"])
    )


def downgrade() -> None:
    """Keep reference data: existing parcels may still depend on these types.

    Downgrading the seed must not delete business data or violate foreign keys.
    Re-upgrade is safe because upgrade inserts only missing names.
    """
