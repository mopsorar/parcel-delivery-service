"""create parcel tables

Revision ID: 38e6bf8af41d
Revises:
Create Date: 2026-09-28 22:13:23.641966

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "38e6bf8af41d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "parcel_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "parcels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("content_value_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("delivery_cost_rub", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.CheckConstraint("content_value_usd > 0", name="ck_parcels_content_value_usd_positive"),
        sa.CheckConstraint("weight > 0", name="ck_parcels_weight_positive"),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["parcel_types.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_parcels_session_id_type_id", "parcels", ["session_id", "type_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_parcels_session_id_type_id", table_name="parcels")
    op.drop_table("parcels")
    op.drop_table("parcel_types")
