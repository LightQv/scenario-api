<div align="center">

<img src="https://raw.githubusercontent.com/LightQv/scenario-expo/main/assets/images/icon.png" alt="Scenario icon" width="96" height="96" />

# SCENARIO API

FastAPI backend for authentication, watchlists, viewing history, statistics, and media metadata persistence.

[About](#about) · [Setup](#setup) · [Development](#development) · [Database](#database) · [Configuration](#configuration) · [API Documentation](#api-documentation) · [Related Projects](#related-projects) · [License](#license)

</div>

---

## About

Scenario API is the backend service for the Scenario movie and TV tracking applications.

It provides user authentication, profile management, watchlists, viewing history, statistics, uploads, and persistence for media records consumed by the web and mobile clients. Authentication uses JWT tokens stored in HTTPOnly cookies.

Core components:

- FastAPI application and versioned API routes
- PostgreSQL persistence with SQLAlchemy and Alembic
- Pydantic request and response schemas
- Email-based password reset flow
- Docker configuration for development and production deployments

### Private episode progress and releases

`GET /api/v1/up-next?language=en-US` (or `fr-FR`) combines the authenticated
owner's tracked shows with **PENDING Bookmarks in their SYSTEM watchlist**.
It returns an owner-labelled, `private, no-store` snapshot with `to_watch`,
`upcoming`, `caught_up`, `finished`, `as_of` and an explicit metadata-failure count. Custom
watchlists do not feed this queue. Public TMDB catalogues are persisted and
refreshed by a background worker; feed/progress reads and mutations never call
TMDB inline. Regular seasons are fetched in append batches of at most 15.
Air dates do not imply streaming or local availability.
The PWA calls this destination **Next / La suite**, retaining `/up-next` for
compatibility. Ended/canceled shows are omitted from `caught_up` only after
their released regular episodes are all watched; unwatched episodes and any
announced future release remain visible. Such completed titles remain available
in `finished`, a consult-only listing (no restore action).

Migration `0018` (`q7r8s9t0u1v2`, after `0017`) adds account-owned
`show_exclusion` preferences. `PUT /api/v1/up-next/shows/{tmdb_id}/exclusion`
accepts a validated display-only `{ title, poster_path }` snapshot; DELETE on
the same path restores the show. Both require the cookie and matching
`X-Scenario-Owner` guard and are idempotent. The feed's `excluded` list remains
available without querying TMDB for these shows; exclusion wins over Bookmarks
and hides the TV identity from both sections, not a same-ID movie. Neither
operation modifies history, bookmarks, cutoffs or individual episode progress.
The original cutoff remains fixed while excluded. Preferences are independent
of views/progress and cascade only on account deletion; metadata snapshots are
private display copy, not authoritative TMDB records.

Migration `0017` (`p6q7r8s9t0u1`, after `0016`) creates separate show/episode
progress tables and seeds one fixed UTC conversion-date cutoff per distinct
existing owner/viewed show. All known released regular episodes through that
day are assumed watched, by product decision. It **never modifies existing view
rows, dates or statistics**. Season zero, unknown dates and future episodes are
excluded. New whole-show watched actions initialize the same fixed assumption;
duplicate views never slide a nonempty cutoff. A first whole-show action after
partial/start-only tracking catches up released episodes too. Removing the final show-level view clears only
that owner's progress for that show.

- `PUT /api/v1/up-next/shows/{tmdb_id}/episodes` accepts positive
  `{ season_number, episode_number, watched: true|false }`, validates the episode's
  air date against the published catalogue and upserts the explicit desired state
  under a unique owner/show/season/episode key. Omitted `watched` defaults to true
  for older clients. Explicit false overrides inherited whole-show cutoffs.
  A first episode automatically starts tracking with an empty baseline; it never
  assumes earlier episodes/seasons were watched or adds a viewing-history row.
- `GET /api/v1/up-next/shows/{tmdb_id}/progress` returns an owner-labelled,
  no-store snapshot of released regular episode watched states and `as_of`.
- `PUT /api/v1/up-next/shows/{tmdb_id}/tracking` starts tracking at the empty
  `0001-01-01` cutoff after verifying the show. Replays preserve existing progress.
- `PUT /api/v1/up-next/shows/{tmdb_id}/seasons/{season_number}` accepts
  `{ through: YYYY-MM-DD, watched: true|false }` from the progress snapshot,
  verifies the season and sets only its released regular episodes through that day. Unknown/future dates
  and specials are excluded. It starts tracking without creating history.
- `PUT /api/v1/up-next/shows/{tmdb_id}/watched` accepts the same dated boolean
  request and atomically sets all released regular children and preserves explicit
  whole-show history behavior (create once on watch, remove owned TV records on
  unwatch). `/caught-up` sets progress only, without changing history. Neither
  slides historical cutoffs. Child-derived parent selection never inserts history.
- `POST /api/v1/up-next/refresh?language=en-US` queues public catalogue updates
  and returns 202; subsequent GETs read status/data only, never retrigger the pipeline.
- All writes require the normal cookie and matching `X-Scenario-Owner` UUID.
  The header only detects stale-account actions; it cannot choose an owner or
  replace authentication. CORS allows it for the existing approved origins.

Initial release on 2026-10-18 from revision `fea08f8`; the direct season/episode
tracking and finished-list extension deployed on 2026-10-19 from `6e79d5b`. The
persistent-catalogue/reversible-progress release deployed later that day from
`635bb08`, followed by the notification/HTTPS release `7de3454` at migration
`0021` (`t0u1v2w3x4y5`), without reseeding the 140 initial
show-progress cutoffs. The validated database
backup and previous API image are retained. Existing data fingerprints matched
across migration; the recording-date backfill was not rerun. See the sibling
PWA's `docs/DEPLOYMENT_AUDIT.md` for immutable image identities and verification
boundaries. Episode marking already uses private progress records, not viewing
history rows, so episode entries never appear in the viewing pages/statistics.
The direct season/episode tracking extension reuses migration `0018`'s schema;
do not reseed progress or rerun any migration/backfill to enable it.

The reversible-progress/persisted-catalogue follow-up deployed on 2026-10-19.
Migration `0019` (`r8s9t0u1v2w3`) defaults existing episode rows
to `watched=true` and creates `release_catalog` (public data only). It does not
modify history, statistics or existing cutoffs. The lifespan-managed worker
discovers tracked shows/system PENDING Bookmarks at startup and hourly in both
EN/FR. Database leases (`SKIP LOCKED`, 15-minute expiry, fenced publication)
deduplicate work across API processes. Each consumer fetches one title at a time without
holding a database connection, then published atomically; failed fetches preserve
the last good snapshot and back off five minutes. Continuing titles refresh every
six hours, terminal shows weekly. Manual refresh shares the same jobs and has a
one-minute completion cooldown. Cold reads queue preparation; warm feed reads
batch-load catalogues and derive private progress. The feed exposes `syncing`,
`sync_failed` and `updated_at`; details expose `ready` while preparing.

Migration `0020` (`s9t0u1v2w3x4`) adds owner-private ordered `progress_action`
receipts and catalogue priority. `PUT /up-next/shows/{id}/actions` accepts an
operation UUID, regular target (nullable season/episode for whole show), original
`through` date, desired `watched` boolean and optional `record_history` (default
true for explicit show actions; Next sends false). Child actions never write
history regardless of that flag. It returns a private/no-store 202 receipt:
pending, applied, failed or cancelled. Later explicit legacy history additions
and final removals cancel older pending intents, preventing worker resurrection.
Owner-row locking serializes overlapping intents;
catalogue validation and history/progress writes share the receipt transaction.
Conflicting reuse of an operation UUID is 409; at most 150 actions may await
preparation per owner. Progress reads include ordered receipts. Final receipts
are kept seven days after completion; pending intents survive restarts and are not expired.

Three bounded worker consumers prioritize interactive misses over feed misses
and scheduled warming. Published snapshots omit irrelevant episode synopses and
crew lists, reducing request deserialization. The PostgreSQL rehearsal prints a
reproducible full-vs-compact 60-show/300-episode benchmark; these local timings are
not evidence of phone/network performance. No real metadata calls run in that test.

For future installations, **apply additive migrations through `0020` before
running this API version**, with a verified backup and watched writes paused
across migration/API cutover to prevent old writers creating unseeded views.
Deploy the compatible API before the PWA. Leave additive tables on code rollback;
the explicit downgrade discards the public cache/negative overrides without
changing original history. Prefer code rollback retaining the additive schema.
Do not rerun any historical recording-date backfill for this feature.

Hermetic contracts: `.venv/bin/python -m unittest discover -s contract_tests -v`.
Actual PostgreSQL rehearsal:
`.venv/bin/python scripts/test_up_next_postgres.py` uses an already installed
`postgres:16-alpine` image with `--pull never`, generated fixtures, tmpfs and a
loopback-only random port; its owned container is removed afterward. It does
not read configured database credentials or contact TMDB/production.

Release evidence: API publisher [39297925255](https://github.com/LightQv/scenario-api/actions/runs/39297925255),
immutable digest `sha256:6ade733edad4cf4a9f687824c1cc5429d735e3d7fc2287be6e22927404e37536`.
All 115 tracked application/runtime files matched the published image. The 58
hermetic contracts and PostgreSQL rehearsal passed locally; the existing API
workflow publishes images but does not run tests. Before migration, the production
backup was decoded and fully restored in an isolated disposable PostgreSQL 16
instance with matching data fingerprints. Every existing table's original columns
matched across migration and candidate verification; old episode rows became
`watched=true`. History, cutoffs and recording dates were not reseeded/backfilled.
Production HTTP health, private-route rejection and initial public catalogue
publication passed; authenticated watched writes and physical iPhone acceptance
were not used as release probes. The old API image is retained as `api-rollback`;
retain additive schema during code rollback. Full receipts and the backup are
under `~/web_app/scenario/api/backups/current-rollback/` on the server.

### Private viewing insights

`GET /api/v1/insights/views` requires the existing authenticated cookie and
returns `{ date_semantics: "recorded_at", views: [...] }` for the authenticated
owner only, with `Cache-Control: private, no-store`. Each allowlisted legacy
view adds nullable `recorded_at`; existing public history schemas, watched POST
payload/success bodies, DELETE responses and release-year statistics are unchanged.

`recorded_at` is an explicit UTC record-creation instant, **not playback time**.
New records created by the watched route receive it. Removing/re-adding a
record creates a new date. This is a current snapshot, not an immutable event log.
TV runtime remains episode count, not minutes.

Timestamp discovery: shared `Base.created_at` and initial migrations use naive
`DateTime`/database `now()`. The SQL-dump restore path supplies no historical
timezone or provenance guarantee. No live database was inspected to establish a
different convention. Consequently, legacy/imported dates remain unknown; the
new endpoint does not reinterpret `created_at` or `updated_at` or append `Z`.
An optional operator-approved backfill can now adopt legacy creation dates after
their source timezone and provenance have been reviewed (see below).

Migration `0016` adds only nullable timezone-aware `view_model.recorded_at`, with
**no default and no backfill**. It must precede running the new backend code.
Backend release/migration requires separate approval: verify the current Alembic
head/schema, take a consistent database backup and verify its restore procedure
before applying the additive migration. Prefer API-first release; the new PWA
falls back to all-time history on an old API's 404. To roll back the API, retain
the unused nullable column; no destructive downgrade is necessary. The migration's
explicit downgrade drops recording dates and must not be run casually on live data.

Hermetic route/schema/SQL contracts (no settings files or database connections):

```bash
.venv/bin/python -m unittest discover -s contract_tests -v
```

#### Optional historical recording-date backfill

This is a separately approved **data migration**, not an automatic Alembic step
or startup action. It works after migration `0016` and can be run after production
deployment. It changes no schema or public API. No production backfill has been
performed or real PostgreSQL rehearsal established by the hermetic tests.

Before use:

1. Take a consistent database backup and verify how to restore it. Record the
   database/release and the chosen timezone in the operator's change record.
2. Establish the **historical DB session timezone** used when naive `created_at`
   values were written, plus import provenance. A current `SHOW TimeZone` is
   evidence, not proof of historical configuration. These are creation/import
   dates, not playback dates. Never use the viewer's current timezone as a guess.
3. If histories have different conventions, scope each operation with `--owner
   ACCOUNT_UUID`. Do not apply one timezone across mixed-provenance accounts.
   Mixed conventions within one account require separate investigation.
4. Set `SOURCE_ZONE` to the verified IANA timezone (for example `UTC` only if
   verified), then preview from the API project root in its configured environment:

   ```bash
   python -m app.database.backfill_view_dates --source-timezone "$SOURCE_ZONE"
   ```

   Preview uses a read-only transaction and reports candidate/convertible/rejected
   counts and up to five timestamp-only samples. Check timezone conversions,
   especially year/month boundaries. Keep output private. Invalid dates, DST gaps
   and repeated local times are rejected, not silently assigned an offset.

5. After separate execution approval, use the reviewed count (not blindly 575):

   ```bash
   python -m app.database.backfill_view_dates --source-timezone "$SOURCE_ZONE" \
     --apply --expected-count REVIEWED_COUNT --acknowledge-inferred-dates
   ```

   Include the same `--owner` on preview and apply if scoped. All candidates must
   be convertible and their count must match. Apply locks candidate rows, fills
   only `recorded_at IS NULL`, and commits atomically; failures roll back. Five-
   second lock and sixty-second statement timeouts bound contention. Existing
   recording dates, `created_at` and `updated_at` are never overwritten. Repeat
   preview should show no candidates unless new undated imports have arrived.

6. Reopen Your Scenario to refresh its snapshot; verify totals are unchanged and
   month/year selection now uses adopted creation dates. Imports can cluster on
   their import date. The current API does not distinguish inferred creation dates
   from new explicit recording dates: accepting that equivalence is part of this
   opt-in operation. Comparisons still require their existing coverage checks.

There is deliberately no blanket “clear dates” rollback: it could erase genuine
new dates. Retain the backup and operator record; any reversal must be scoped to
the actual affected records. Never run an Alembic downgrade to undo this backfill.

These check authorization, owner-bound SQL, allowlisted serialization, legacy
responses and offline PostgreSQL DDL. They are not a PostgreSQL migration rehearsal.
The historical pytest bootstrap still references removed `app.core.database`;
its repair is outside this feature.

---

### Viewing-activity release · 2026-10-20

Deployed **16:16 UTC** from
`58b12282eef590bf37e55e27fb0aac914d19edc4` after successful
[publication 39455401780](https://github.com/LightQv/scenario-api/actions/runs/39455401780).
Immutable digest:
`sha256:b3bb14aa0dad9d90bab4519fb63129d7a28c72e7bfef6f6219450fe94437bd08`;
running AMD64 image:
`sha256:b8dd10f570d0b8bff5fe7e8f4b1771080c4c46edad84de6c5aeca1a7a0170b86`.
All **123** tracked application/runtime files matched the candidate image.
The protected production backup was fully restored on an internal-only disposable
PostgreSQL network; startup, Alembic no-op and EN/FR feed/Viewed/notification
projections for restored accounts preserved all **19** table fingerprints,
including `alembic_version`. No external requests or real push transport were
possible. Live startup preserved all private-table fingerprints; the public
catalogue scheduler retains its normal refresh behavior. Schema stays at **0022**.
The first rehearsal hit an output-parser error after projection checks and safely
restored the old runtime; parsing the final JSON line corrected the operator script,
then the full rehearsal and cutover passed without application-source changes.

Base Compose, **5001:8000**, stable push/JWT/integration keys, HTTPS origin/CORS,
`DEBUG=false`, mode-600 `web-push.env` and unrelated containers were preserved.
Anonymous private-route rejection and the new activity query/Viewed OpenAPI
contracts passed. No authenticated production writes or test pushes were used.
Current rollback is the previous `c38ff0711e192d2bf16d34fb479fa11d175aa837`
image `sha256:37b9e907f92a4c8e089edee1ccbe0c725aabffdd4e932919e10ac2baf27262c2`,
local tag `vivianquerenet/scenario:api-rollback`. Retain schema 0022 and the saved
`web-push.env` overlay on rollback. Backup/checksum/Compose/receipts are server-local
under `backups/current-rollback/`; older evidence remains under `pre-activity-*`.
These are not off-host disaster-recovery backups. Frontend cutover evidence belongs
in the sibling PWA's `docs/DEPLOYMENT_AUDIT.md`; installed-iPhone acceptance is separate.

Updated clients request `GET /api/v1/up-next?activity=true`. Next derives TV
eligibility from PENDING system Bookmarks, whole-show history or effective watched
released regular episodes. Empty/negative-only baselines do not keep following a
show. Bookmarked TV starts at the first released unwatched episode; bookmarked
unwatched films move from Coming soon to To watch on release. Watched films are
excluded using full movie/TV identity. Removing the last visible reference stops
following, without deleting dormant cutoffs/negative overrides or bookmarks.
Legacy clients omit `activity` and retain their episode-only response contract
until app activation; the old explicit `/tracking` baseline endpoint is deprecated.

`GET /api/v1/up-next/viewed` is cookie-owner-only, owner-labelled and no-store. It
projects TV progress/status for legacy history and shows with watched episodes;
the PWA merges these rows by TV identity without fabricating View rows/dates.
Exclusions affect Next and notifications, never Viewed. Shared owner-bound source
selectors also govern release notifications, which still send only on qualifying
local release days and recheck at send/retry time. Historical statistics,
achievements/story inputs and existing View records remain unchanged. No new
migration or historical backfill is needed. Deploy API before PWA; retain the
existing 0022 additive schema/runtime push overlay and rollback safeguards.

Local checks: 72 hermetic API contracts, targeted Pylint errors-only and disposable
PostgreSQL progress/notification/activity rehearsals. The new lifecycle rehearsal
is `.venv/bin/python scripts/test_viewing_activity_postgres.py`; it verifies
bookmark/episode/season/show/removal transitions, negative overrides, exclusions,
movie/TV collisions, owner isolation and unchanged original history/statistics
inputs without configured databases, TMDB or real push transport. The separate
protected production-backup restore rehearsal also passed as recorded above.

### Release notifications (migrations 0021–0022)

Owner-private `/api/v1/notifications` GET/PUT and `/device` PUT/DELETE plus `/test`
POST implement opt-in daily release summaries. Writes require the authenticated
cookie and matching `X-Scenario-Owner`. Preferences default off; each browser must
separately grant permission. Only today's unwatched regular tracked episodes and
bookmarked unwatched movies qualify; no qualifying release means no automatic
notification, and no history/progress is changed. Payloads are generic by default.
The separate account-wide `show_details` consent allows up to three bounded media
titles/episode codes plus a remaining-release count on device lock screens. No
account identifiers or title snapshots are retained in the outbox. Eligibility
and the current consent are checked again before each send/retry; turning details
off cannot recall already delivered notifications. Manual tests remain generic.
Meaningful localized notification titles replace the repeated app name.

Apply additive migrations `0021` (`t0u1v2w3x4y5`) and `0022`
(`u1v2w3x4y5z6`) before starting compatible code. The latter adds only
`show_details NOT NULL DEFAULT false`, preserving existing opt-ins and all other
preferences/devices/receipts. Older clients omitting the field leave it unchanged.
See the verified release below for deployed source and acceptance boundaries.
Configure server-only `WEB_PUSH_ENABLED`, `WEB_PUSH_PRIVATE_KEY`,
`WEB_PUSH_PUBLIC_KEY`, `WEB_PUSH_SUBJECT`, and the existing integration encryption
key. Only the public VAPID key is returned to authenticated browsers. Keep private
keys stable, out of images/source/logs. The worker uses stored catalogues, bounded
provider requests, PostgreSQL owner locks and unique device/day receipts; expired
devices are removed and retries stop at midnight/four attempts. Delivery is
best-effort, not exact-time/exactly-once. Provider destinations are allowlisted and
redirects disabled. Apple/Google/Mozilla still carry encrypted push traffic.

Run `.venv/bin/python scripts/test_notifications_postgres.py` for isolated real
PostgreSQL migration/concurrency/DST/retry/opt-out checks (owned disposable
database, no configured credentials or real push delivery). Frontend setup,
isolated Tailscale HTTPS and physical-iPhone acceptance boundaries are documented
in the sibling PWA's `docs/NOTIFICATIONS.md`. This section describes the
implementation and platform boundaries, not a claim of physical-device acceptance.

The previous release-details update deployed on **2026-10-20 at 13:34 UTC** from
`c38ff0711e192d2bf16d34fb479fa11d175aa837` after successful
[API publication 39427892800](https://github.com/LightQv/scenario-api/actions/runs/39427892800).
API digest: `sha256:df4d373f74715f9a66a5b8df18ab28ec9457fa07964fad6907244448f9653aec`;
running AMD64 image: `sha256:37b9e907f92a4c8e089edee1ccbe0c725aabffdd4e932919e10ac2baf27262c2`.
All 121 tracked application/runtime files matched the image. The existing publisher
has no test stage; 67 local hermetic contracts (including real encryption/fake
transport), targeted Pylint and isolated PostgreSQL migration/concurrency checks
passed separately. Full production backup restore, candidate migration/startup and
production 0021→0022 migration preserved original-column fingerprints for all 18
tables, including preferences/devices/receipts; startup also preserved them.
Existing details consent is false. Base Compose/ports/network and the extra
`web-push.env` overlay, stable keys, HTTPS origin/CORS and Secure-cookie settings
were retained. Unrelated containers were unchanged. Health, anonymous private-route
rejection and the API schema's default-off consent passed; no real test push or
authenticated account mutation was used for acceptance. Frontend `6738184` deployed
after its exact-commit checks (473 browser tests) and publisher passed; see its
`docs/DEPLOYMENT_AUDIT.md` for full evidence and physical-device limits.

The release-details rollout's historical API rollback retained `7de3454`, image
`sha256:a7f608bace170dcec43dd6b38f673e1ad4cc4280446410f685a8ae50764515bf`,
as local `vivianquerenet/scenario:api-rollback`. Keep additive schema on runtime
rollback; the saved override bypasses the old image's unresolvable 0022 Alembic
hook, runs Uvicorn directly and retains `web-push.env`. Restore-tested backup,
checksum, Compose/overrides and fingerprints are in `backups/current-rollback/`;
older receipts remain under timestamped `pre-release-details-*` directories.
Later evidence-only commits do not change the deployed runtime source identity.

The previous release deployed on 2026-10-19 from `7de3454` after successful
[API publication 39315357440](https://github.com/LightQv/scenario-api/actions/runs/39315357440)
and exact-commit frontend checks/publication. Immutable API digest:
`sha256:ad5f69a9677ec6c20408a54b4527a47f90fb36db7f084245b1225a051b17deac`.
All 121 tracked application/runtime files matched the image. The production
backup restored in isolated PostgreSQL with matching fingerprints; migration
0021 preserved all existing tables and candidate startup preserved private data.
New tables began empty and notifications remain opt-in. Live HTTPS shell/worker,
offline guest reload and private-route rejection passed; physical iPhone delivery
and authenticated settings writes remain user acceptance.

Runtime now uses `https://scenario.tail9c702b.ts.net`, appended to existing CORS
origins, and `DEBUG=false` for Secure cookies. Both original base Compose files and
the original API `.env` remain unchanged. **Keep the API candidate override's extra
`web-push.env` on subsequent recreates/releases**, or Web Push/HTTPS flags revert to
old defaults. Keys are stable and server-only (mode 600). The retained old API image
cannot resolve migration 0022: the saved rollback override bypasses its Alembic
entrypoint and starts the compatible Uvicorn app directly. Retain additive schema;
do not delete users' notification/progress data just to roll back code. Full receipts
and restore-tested backup remain in `backups/current-rollback/`; older release
evidence was archived, not deleted.

## Setup

Clone the repository:

```bash
git clone https://github.com/LightQv/scenario-fast-api.git
cd scenario-fast-api
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the local environment file:

```bash
cp .env.example .env
```

Apply database migrations:

```bash
alembic upgrade head
```

---

## Development

Run the API server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run tests:

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov
```

Run linting:

```bash
pylint app/
```

Run with Docker:

```bash
docker-compose -f docker-compose.yaml up
```

Run the production Docker stack:

```bash
docker-compose -f docker-compose.prod.yaml up
```

---

## Database

Create a migration after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "migration message"
```

Apply migrations:

```bash
alembic upgrade head
```

Rollback the latest migration:

```bash
alembic downgrade -1
```

Restore data from a SQL dump:

```bash
python app/database/restore_data.py
```

The restore script replaces the current database content.

---

## Configuration

Configuration is loaded from environment variables.

Required groups:

- `DATABASE_URL` and PostgreSQL connection settings
- `JWT_SECRET_KEY` and token expiration settings
- `FRONTEND_URL` for CORS
- SMTP settings for password reset emails
- Optional monitoring settings for production deployments

See `.env.example` for the expected local configuration shape.

---

## API Documentation

When the development server is running, API documentation is available at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

---

## Project Structure

```text
app/
├── api/          # Versioned API routes and dependencies
├── core/         # Settings, security, middleware, logging, email configuration
├── database/     # SQLAlchemy session, Alembic migrations, restore tools
├── models/       # SQLAlchemy ORM models
├── schemas/      # Pydantic schemas
├── services/     # Reusable service layer
└── utils/        # Shared utility code
```

---

## Related Projects

- [Scenario Web](https://github.com/LightQv/scenario-web-client)
- [Scenario Expo](https://github.com/LightQv/scenario-expo)

---

## License

Scenario API is licensed under the MIT License. See [LICENSE](LICENSE).
