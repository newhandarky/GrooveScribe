# Backend

FastAPI API server for GrooveScribe.

## Responsibility

- Receive upload, status, result, and download requests.
- Persist metadata through database models.
- Store and retrieve artifacts through a storage adapter.
- Enqueue long-running transcription work for the background worker.

The backend must not run ffmpeg, Demucs, ADTOF-pytorch, or other long-running audio processing inside an API request.

## Current Scope

This scaffold covers `GS-P2-001`:

- FastAPI app factory.
- Root health check: `GET /health`.
- API v1 health check: `GET /api/v1/health`.
- Config loading through `pydantic-settings`.
- API route structure for future MVP endpoints.

## Local Commands

```bash
cd backend
python -m pytest
uvicorn app.main:app --reload
```

## Database Migrations

After installing backend dependencies, run from `backend/`:

```bash
alembic upgrade head
alembic downgrade -1
```

The initial migration creates `users`, `audio_files`, `transcription_jobs`, `drum_tracks`, and `export_files`.
