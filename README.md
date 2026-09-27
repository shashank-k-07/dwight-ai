# Dwight

AI agent cost observability. Build plan: `docs/build-spec.md`. Vocabulary: `CONTEXT.md`. Decisions: `docs/adr/`.

**Developing:** see [docs/dev.md](docs/dev.md): how to run the API, dashboard, tests and pipeline stages, where fixtures live, and how to add a stage or panel. The API contract is in [docs/api-contract.md](docs/api-contract.md).

Quick start:

```bash
cd backend && .venv/bin/python -m dwight.pipeline run ingest fixtures/otlp/tracer_session.json
.venv/bin/uvicorn dwight.api.main:app --port 8000
cd ../dashboard && npm run dev   # http://localhost:3000
```
