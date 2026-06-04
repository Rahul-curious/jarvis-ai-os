# JARVIS Backend

FastAPI foundation for the JARVIS cloud control plane.

Phase 3 responsibilities:

- Provide versioned API routing under `/api/v1`.
- Connect to PostgreSQL through SQLAlchemy async sessions.
- Manage Alembic migrations for auth persistence.
- Support open registration, login, refresh, logout, and user profile endpoints.
- Store JWT access and refresh tokens in HttpOnly cookies.
- Persist users, sessions, and audit logs.

Business logic for assistant orchestration, memory, RAG, agents, browser automation, and voice is intentionally deferred.

## Environment

Required production-sensitive settings:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `BACKEND_CORS_ORIGINS`
- `AUTH_COOKIE_SECURE`

Local defaults are documented in the repository `.env.example`.

## Migrations

Run migrations manually:

```bash
alembic upgrade head
```

The backend Docker container runs this command automatically before starting Uvicorn.

## API

- `GET /api/v1/health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/users/me`

## Tests

```bash
pytest
```
