# 🎬 SCENARIO API

**FastAPI backend for Scenario Web Client**  
Manage your watchlists and track your movie & TV show viewing history with a modern API built on FastAPI.

## 📊 Badges

<p align="left">
  <a href="https://github.com/LightQv/scenario-api/stargazers">
    <img src="https://img.shields.io/github/stars/LightQv/scenario-api?style=for-the-badge&logo=github" alt="GitHub stars"/>
  </a>
  <a href="https://github.com/LightQv/scenario-api/issues">
    <img src="https://img.shields.io/github/issues/LightQv/scenario-api?style=for-the-badge&logo=github" alt="GitHub issues"/>
  </a>
  <a href="https://github.com/LightQv/scenario-api/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/LightQv/scenario-api?style=for-the-badge" alt="License"/>
  </a>
  <a href="https://github.com/LightQv/scenario-api/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/LightQv/scenario-api/.github/workflows/prod-api-docker.yml?style=for-the-badge&logo=github" alt="CI Status"/>
  </a>
</p>

## 🛠️ Technologies

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-%232496ED.svg?style=for-the-badge&logo=docker&logoColor=white)
![Nginx](https://img.shields.io/badge/Nginx-%2325C65B.svg?style=for-the-badge&logo=nginx&logoColor=white)

## ✨ Features

- ✅ Full authentication: registration, login, password reset
- 🎬 Watchlist management: create, edit, delete lists of movies & TV shows
- 👁️ Viewing history: track watched content
- 📊 Statistics: analyze viewing habits
- 🔐 Security: JWT tokens with HTTPOnly cookies, bcrypt password hashing
- 📧 Email system: password reset via email
- 🐳 Multi-environments: development, staging, production with Docker
- 🔍 Monitoring: logging with Loguru, error tracking with Sentry

## 🏗️ Project Structure

```
app/
├── core/              # Configuration, database, security
├── models/            # SQLAlchemy models
├── schemas/           # Pydantic schemas
├── api/v1/            # API routes
├── services/          # Business logic
├── utils/             # Utilities (email templates, etc.)
└── database/          # Database tools and backups
├── backup/        # SQL dump files
└── restore\_data.py # Database restore script
```

## ⚙️ Installation

1. **Clone the repository**

```bash
git clone https://github.com/LightQv/scenario-api.git
cd scenario-api
```

2. **Copy environment variables**

```bash
cp .env.example .env
# Edit .env with your credentials
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
source venv/bin/activate
```

4. **Database**

```bash
alembic upgrade head
```

## 🐳 Docker

- `Dockerfile` / `Dockerfile.dev`
- `docker-compose.dev.yaml` / `docker-compose.prod.yaml`
- `nginx/` for configuration

## 🗄️ Database Management

Restore from SQL dump:

```bash
python app/database/restore_data.py
```

⚠️ Warning: This will erase current database content.

## 📚 API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 🔧 Useful Commands

### Database Migrations (Alembic)

```bash
# Create a new migration after changing models
alembic revision --autogenerate -m "your migration message"

# Apply migrations to the database
alembic upgrade head

# Downgrade to a previous migration (optional)
alembic downgrade -1
```

## 🔍 Monitoring & Security

- Logging with **Loguru**
- Error tracking with **Sentry**
- Nginx metrics & rate limiting
- JWT auth, bcrypt passwords, secure reset tokens
- Security headers: `Strict-Transport-Security`, `X-Frame-Options`, `CSP`, etc.

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.
