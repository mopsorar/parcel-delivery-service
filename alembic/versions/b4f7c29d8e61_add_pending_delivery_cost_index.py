"""Add an ordered partial index for pending delivery-cost batches.

Revision ID: b4f7c29d8e61
Revises: a7c1e42b9d60
"""

import sqlalchemy as sa
from alembic import op

revision = "b4f7c29d8e61"
down_revision = "a7c1e42b9d60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_parcels_pending_delivery_cost_id",
        "parcels",
        ["id"],
        unique=False,
        postgresql_where=sa.text("delivery_cost_rub IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_parcels_pending_delivery_cost_id", table_name="parcels")
