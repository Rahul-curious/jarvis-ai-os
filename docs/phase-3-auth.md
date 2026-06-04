# Phase 3 Authentication And Control Plane

## Summary

Phase 3 implements the first secure control-plane slice for JARVIS: user identity, JWT sessions, audit logging, PostgreSQL persistence, and login/register/dashboard UI.

This phase intentionally does not implement memory, RAG, agents, browser automation, computer control, voice, or assistant business logic.

## Scope

Implemented:

- FastAPI auth endpoints.
- PostgreSQL-backed SQLAlchemy models.
- Alembic migration for `users`, `sessions`, and `audit_logs`.
- JWT access and refresh tokens stored in HttpOnly cookies.
- Argon2 password hashing.
- Open registration.
- Login, refresh, logout, and current-user profile flow.
- React login, register, and dashboard pages.
- Docker Compose startup for `postgres`, `backend`, and `frontend`.

Deferred:

- Tenants, workspaces, RBAC, and policy engine.
- Long-term memory and RAG.
- LangGraph agent execution.
- Browser automation and computer control.
- Voice assistant.

## Database Tables

```mermaid
erDiagram
    USER ||--o{ SESSION : owns
    USER ||--o{ AUDIT_LOG : creates

    USER {
      uuid id
      string email
      string full_name
      string password_hash
      boolean is_active
      boolean is_admin
      datetime last_login_at
      datetime created_at
      datetime updated_at
    }

    SESSION {
      uuid id
      uuid user_id
      string refresh_token_hash
      string refresh_token_jti
      string user_agent
      string ip_address
      datetime expires_at
      datetime revoked_at
      datetime created_at
      datetime updated_at
    }

    AUDIT_LOG {
      uuid id
      uuid user_id
      string action
      string outcome
      string resource_type
      string resource_id
      string ip_address
      string user_agent
      json metadata
      datetime created_at
    }
```

## Auth Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Frontend
    participant Backend
    participant DB as PostgreSQL

    Browser->>Frontend: Submit register/login form
    Frontend->>Backend: POST auth request with credentials
    Backend->>DB: Create or verify user
    Backend->>DB: Create session and audit event
    Backend-->>Frontend: Set HttpOnly access and refresh cookies
    Frontend->>Backend: GET /api/v1/users/me
    Backend->>DB: Validate access JWT and session
    Backend-->>Frontend: Return profile
```

## Security Notes

- Passwords are hashed with Argon2 via `pwdlib`.
- Access tokens default to 15 minutes.
- Refresh tokens default to 14 days and are backed by session rows.
- Logout revokes the active session and clears cookies.
- The frontend uses `credentials: "include"` and never stores JWTs directly.
- Production deployments must set a strong `JWT_SECRET_KEY` and enable secure cookies behind HTTPS.
