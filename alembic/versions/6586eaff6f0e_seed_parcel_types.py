"""seed parcel types

Revision ID: 6586eaff6f0e
Revises: 38e6bf8af41d
Create Date: 2026-09-29 19:55:42.887443

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6586eaff6f0e"
down_revision: str | Sequence[str] | None = "38e6bf8af41d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

parcel_types = sa.table("parcel_types", sa.column("name", sa.String()))


def upgrade() -> None:
    """Upgrade schema."""
    op.bulk_insert(
        parcel_types,
        [
            {"name": "clothes"},
            {"name": "electronics"},
            {"name": "misc"},
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        parcel_types.delete().where(
            parcel_types.c.name.in_(
                (
                    op.inline_literal("clothes"),
                    op.inline_literal("electronics"),
                    op.inline_literal("misc"),
                )
            )
        )
    )
