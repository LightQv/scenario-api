"""
Import a pre-cleaned Supabase dump directly into the local database.
No filtering or mapping needed (dump must already be ready).
"""

import logging
import sys
import subprocess
from pathlib import Path
from typing import List

from app.core.settings import settings

logger = logging.getLogger(__name__)


def get_local_tables() -> List[str]:
    """Return list of tables in local DB (public schema)."""
    container_name = settings.DB_CONTAINER_NAME
    try:
        command = [
            "docker",
            "exec",
            container_name,
            "psql",
            "-U",
            settings.POSTGRES_USER,
            "-d",
            settings.POSTGRES_DB,
            "-t",
            "-c",
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error(f"Could not get table names: {result.stderr}")
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception as e:
        logger.error(f"Error getting table names: {e}")
        return []


def import_dump(dump_path: str) -> bool:
    """Import the cleaned dump into the local DB."""
    container_name = settings.DB_CONTAINER_NAME
    dump_path = Path(dump_path)

    if not dump_path.exists():
        logger.error(f"Dump file not found: {dump_path}")
        return False

    # Copy dump into container
    temp_file = "/tmp/supabase_import.sql"
    copy_cmd = ["docker", "cp", str(dump_path), f"{container_name}:{temp_file}"]
    result = subprocess.run(copy_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Failed to copy dump into container: {result.stderr}")
        return False

    # Run import
    import_cmd = [
        "docker",
        "exec",
        "-i",
        container_name,
        "psql",
        "-U",
        settings.POSTGRES_USER,
        "-d",
        settings.POSTGRES_DB,
        "-f",
        temp_file,
    ]
    logger.info("📥 Importing dump into database...")
    result = subprocess.run(import_cmd, capture_output=True, text=True)

    # Cleanup
    subprocess.run(["docker", "exec", container_name, "rm", "-f", temp_file])

    if result.returncode != 0:
        logger.error("Import failed:")
        logger.error(result.stderr)
        return False

    logger.info("✅ Import completed successfully")
    return True


def main():
    print("🔄 Scenario API - Supabase Import (Cleaned)")
    print("=" * 55)

    if len(sys.argv) > 1:
        dump_path = sys.argv[1]
    else:
        project_root = Path(__file__).parent.parent.parent
        dump_path = project_root / "app" / "database" / "backup" / "scenario_dump.sql"

    logger.info(f"Using dump: {dump_path}")

    # Check local tables
    tables = get_local_tables()
    logger.info(f"Local tables: {tables}")

    if not tables:
        print(
            "❌ No local tables found. Did you run migrations? (alembic upgrade head)"
        )
        sys.exit(1)

    # Confirm
    print("\nThis will import data into your existing tables:")
    print(", ".join(tables))
    if input("Continue? (y/N): ").strip().lower() not in ["y", "yes"]:
        print("Cancelled.")
        sys.exit(0)

    # Import
    if import_dump(str(dump_path)):
        print("\n✅ Import successful!")
        print("💡 Check with: make db-shell → SELECT COUNT(*) FROM user_model;")
    else:
        print("\n❌ Import failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
