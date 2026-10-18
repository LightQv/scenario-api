"""Preview or explicitly backfill legacy recording dates; never run at startup."""

import argparse
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.engine import Connection


def recording_date(created_at: datetime, source_zone: ZoneInfo) -> datetime:
    """Interpret a naive legacy date without guessing across DST transitions.

    Args:
        created_at: Original timezone-naive database creation timestamp.
        source_zone: Operator-verified historical source timezone.

    Returns:
        The unambiguous UTC record-creation instant.

    Raises:
        ValueError: Date is aware, ambiguous or nonexistent in the source zone.
    """
    if created_at.tzinfo is not None:
        raise ValueError("Expected a timezone-naive created_at")
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = created_at.replace(tzinfo=source_zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(source_zone).replace(tzinfo=None) == created_at:
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError("Ambiguous or nonexistent historical local time")
    return candidates.pop()


def backfill(
    connection: Connection,
    source_zone: ZoneInfo,
    *,
    apply: bool = False,
    expected_count: int | None = None,
    owner: UUID | None = None,
) -> dict[str, Any]:
    """Preview candidates or update them inside the caller's transaction.

    Apply locks candidate rows, checks the reviewed count, and rejects all writes
    if any local date is ambiguous. Raw SQL intentionally preserves updated_at.

    Args:
        connection: PostgreSQL connection in an explicit transaction.
        source_zone: Verified source timezone, not the viewer's timezone.
        apply: Whether explicitly approved writes should be performed.
        expected_count: Reviewed candidate count required for apply.
        owner: Optional account scope for histories with different provenance.

    Returns:
        Aggregate counts and at most five timestamp-only conversion examples.

    Raises:
        ValueError: Apply count differs or any date cannot safely be converted.
    """
    if apply and (expected_count is None or expected_count < 0):
        raise ValueError("Apply requires a nonnegative reviewed expected count")
    predicate = "recorded_at IS NULL"
    parameters: dict[str, Any] = {}
    if owner is not None:
        predicate += " AND viewer_id = :owner"
        parameters["owner"] = owner
    rows = connection.execute(text(
        f"SELECT id, created_at FROM view_model WHERE {predicate} ORDER BY id"
        + (" FOR UPDATE" if apply else "")
    ), parameters).mappings().all()
    converted: list[dict[str, Any]] = []
    examples: list[dict[str, str]] = []
    rejected = 0
    for row in rows:
        try:
            date = recording_date(row["created_at"], source_zone)
        except (ValueError, TypeError, AttributeError, OverflowError):
            rejected += 1
            continue
        converted.append({"id": row["id"], "recorded_at": date})
        if len(examples) < 5:
            examples.append({"created_at": row["created_at"].isoformat(), "recorded_at": date.isoformat()})
    report: dict[str, Any] = {
        "mode": "apply" if apply else "preview",
        "source_timezone": source_zone.key,
        "scope": "one account" if owner else "all accounts",
        "candidates": len(rows), "convertible": len(converted),
        "rejected": rejected, "updated": 0,
        "examples": examples,
    }
    if not apply:
        return report
    if len(rows) != expected_count:
        raise ValueError("Candidate count changed; preview again before applying")
    if rejected:
        raise ValueError("Unsafe historical dates found; no dates were written")
    if converted:
        connection.execute(text(
            "UPDATE view_model SET recorded_at = :recorded_at "
            "WHERE id = :id AND recorded_at IS NULL"
        ), converted)
    report["updated"] = len(converted)
    return report


def main() -> None:
    """Run an opt-in operation using configured DB credentials without logging them."""
    import json
    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-timezone", required=True, help="Verified IANA zone, e.g. UTC or Europe/Paris")
    parser.add_argument("--owner", type=UUID, help="Restrict to one account UUID")
    parser.add_argument("--apply", action="store_true", help="Commit writes; default is read-only preview")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--acknowledge-inferred-dates", action="store_true")
    args = parser.parse_args()
    try:
        zone = ZoneInfo(args.source_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        parser.error("Unknown source timezone")
    if args.apply and (not args.acknowledge_inferred_dates or args.expected_count is None or args.expected_count < 0):
        parser.error("Apply requires --acknowledge-inferred-dates and --expected-count >= 0")
    from app.core.settings import settings

    engine = create_engine(settings.DATABASE_URL, echo=False)
    try:
        with engine.begin() as connection:
            if not args.apply:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            report = backfill(connection, zone, apply=args.apply, expected_count=args.expected_count, owner=args.owner)
        # Report success only after the transaction commits.
        print(json.dumps(report, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
