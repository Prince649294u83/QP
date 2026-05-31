# AI Question Paper Generator Backend

FastAPI backend for the teacher, HOD, and admin workflows shown in the project framework.

## What is included

- JWT authentication with `teacher`, `hod`, and `admin` roles
- Department and subject-aware RBAC
- Question bank CRUD and document upload ingestion
- Ollama-ready AI services targeting `llama3.2:3b`
- Question paper generation, preview, submission, review, and DOCX export
- Audit logs and admin dashboard summary
- SQLite default for local setup, with `DATABASE_URL` override for PostgreSQL later

## Quick start

1. Create a virtual environment and install dependencies.
2. Copy `.env.example` to `.env`.
3. Run:

```bash
uvicorn app.main:app --reload --app-dir backend
```

If `ALLOW_DEMO_SEED=true`, the app seeds demo users:

- `teacher@dsatm.edu` / `Teacher@123`
- `hod@dsatm.edu` / `Hod@123`
- `admin@dsatm.edu` / `Admin@123`

## Notes

- If Ollama is reachable, the backend will try to use `llama3.2:3b`.
- If Ollama is unavailable, the system falls back to deterministic local parsing and paper selection so the flow remains testable.
