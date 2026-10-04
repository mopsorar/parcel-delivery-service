import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text

from parcel_delivery.db.session import engine


def test_seed_downgrade_preserves_referenced_types_and_allows_reupgrade() -> None:
    asyncio.run(_test_seed_downgrade_preserves_referenced_types_and_allows_reupgrade())


async def _test_seed_downgrade_preserves_referenced_types_and_allows_reupgrade() -> None:
    migration_path = Path(__file__).resolve().parents[1] / (
        "alembic/versions/6586eaff6f0e_seed_parcel_types.py"
    )
    spec = importlib.util.spec_from_file_location("seed_parcel_types", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def check_seed(connection: Connection) -> None:
        # Session-local temporary tables shadow public tables. No production data or
        # alembic_version is changed, but the migration executes against real PostgreSQL.
        connection.execute(
            text(
                "CREATE TEMP TABLE parcel_types "
                "(id SERIAL PRIMARY KEY, name VARCHAR NOT NULL UNIQUE) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "CREATE TEMP TABLE parcels "
                "(id SERIAL PRIMARY KEY, type_id INTEGER REFERENCES parcel_types(id)) ON COMMIT DROP"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(
                text(
                    "INSERT INTO parcels (type_id) SELECT id FROM parcel_types WHERE name = 'clothes'"
                )
            )
            migration.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM parcels")) == 1
            assert connection.scalar(text("SELECT count(*) FROM parcel_types")) == 3
            migration.upgrade()
            assert connection.scalar(text("SELECT count(*) FROM parcel_types")) == 3
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM parcels JOIN parcel_types ON parcels.type_id = parcel_types.id"
                    )
                )
                == 1
            )

    try:
        async with engine.connect() as connection:
            await connection.begin()
            await connection.run_sync(check_seed)
            # Connection exit rolls back and removes all temporary test tables.
    finally:
        await engine.dispose()
