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
