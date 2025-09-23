"""
Import a pre-cleaned Supabase dump directly into the production database.
This version works from within a Docker container.
"""

import logging
import sys
import subprocess
import os
from pathlib import Path
from typing import List

from sqlalchemy import create_engine, text
from app.core.settings import settings

logger = logging.getLogger(__name__)


def get_local_tables() -> List[str]:
    """Return list of tables in local DB (public schema)."""
    try:
        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
                )
            )
            return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Error getting table names: {e}")
        return []


def import_dump(dump_path: str) -> bool:
    """Import the cleaned dump into the database using psql."""
    dump_path = Path(dump_path)

    if not dump_path.exists():
        logger.error(f"Dump file not found: {dump_path}")
        return False

    # Parse DATABASE_URL to get connection parameters
    db_url = settings.DATABASE_URL
    # Extract connection details from DATABASE_URL
    # Format: postgresql://user:password@host:port/database

    import re

    match = re.match(r"postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url)
    if not match:
        logger.error("Could not parse DATABASE_URL")
        return False

    user, password, host, port, database = match.groups()

    # Set environment variable for password
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    # Run psql command directly
    import_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        database,
        "-f",
        str(dump_path),
    ]

    logger.info("📥 Importing dump into database...")
    result = subprocess.run(import_cmd, capture_output=True, text=True, env=env)

    if result.returncode != 0:
        logger.error("Import failed:")
        logger.error(result.stderr)
        return False

    logger.info("✅ Import completed successfully")
    return True


def main():
    print("🔄 Scenario API - Supabase Import (Production)")
    print("=" * 55)

    if len(sys.argv) > 1:
        dump_path = sys.argv[1]
    else:
        # In container, look for backup file
        dump_path = "/scenario/app/database/backup/scenario_dump.sql"

    logger.info(f"Using dump: {dump_path}")

    # Check local tables
    tables = get_local_tables()
    logger.info(f"Local tables: {tables}")

    if not tables:
        print("❌ No local tables found. Did migrations run properly?")
        sys.exit(1)

    print(f"\nImporting data into {len(tables)} tables:")
    print(", ".join(tables[:5]) + ("..." if len(tables) > 5 else ""))

    # Import (no confirmation in production)
    if import_dump(str(dump_path)):
        print("\n✅ Import successful!")
        # Quick verification
        try:
            engine = create_engine(settings.DATABASE_URL)
            with engine.connect() as connection:
                result = connection.execute(text("SELECT COUNT(*) FROM user_model;"))
                count = result.scalar()
                print(f"💡 Users imported: {count}")
        except Exception as e:
            logger.warning(f"Could not verify import: {e}")
    else:
        print("\n❌ Import failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
