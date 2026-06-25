# Backend Migrations

Alembic migration files for GrooveScribe backend.

## Commands

Run from `backend/` after installing backend dependencies:

```bash
alembic upgrade head
alembic downgrade -1
alembic current
```

The migration environment reads `DATABASE_URL` through backend settings. Keep migration files independent from local absolute paths.
