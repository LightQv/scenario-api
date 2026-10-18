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

### Private viewing insights

`GET /api/v1/insights/views` requires the existing authenticated cookie and
returns `{ date_semantics: "recorded_at", views: [...] }` for the authenticated
owner only, with `Cache-Control: private, no-store`. Each allowlisted legacy
view adds nullable `recorded_at`; existing public history schemas, watched POST
payload/success bodies, DELETE responses and release-year statistics are unchanged.

`recorded_at` is an explicit UTC record-creation instant, **not playback time**.
Only new records created by the watched route receive it. Removing/re-adding a
record creates a new date. This is a current snapshot, not an immutable event log.
TV runtime remains episode count, not minutes.

Timestamp discovery: shared `Base.created_at` and initial migrations use naive
`DateTime`/database `now()`. The SQL-dump restore path supplies no historical
timezone or provenance guarantee. No live database was inspected to establish a
different convention. Consequently, legacy/imported dates remain unknown; the
new endpoint does not reinterpret `created_at` or `updated_at` or append `Z`.

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

These check authorization, owner-bound SQL, allowlisted serialization, legacy
responses and offline PostgreSQL DDL. They are not a PostgreSQL migration rehearsal.
The historical pytest bootstrap still references removed `app.core.database`;
its repair is outside this feature.

---

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
