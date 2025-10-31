# ML Service Integration — Drop-in Bundle

This bundle contains a containerized ML service (FastAPI) plus a scheduler to auto-retrain HMMs on your data and hot-reload improved models.

**Files added:**

- `services/ml_service/` — code + Dockerfile
- `compose.ml.yml` — Compose overlay defining `ml_service` and `ml_scheduler`
- `.env.example` — config you can copy to `.env`
- `.github/workflows/ml-service-ci.yml` — optional CI (builds image)

**How to integrate with your existing Compose setup:**

1. Copy everything to your repo root.
2. Bind the host path that contains your data to the `data` volume, or mount directly:
   ```yaml
   services:
     ml_service:
       volumes:
         - ./path/to/data:/data:ro
   ```
3. Build + run:
   ```bash
   docker compose -f docker-compose.yml -f compose.ml.yml up -d --build
   ```
4. Hit the service:
   ```bash
   curl -s http://localhost:8003/health
   curl -s -X POST http://localhost:8003/train -H 'Authorization: Bearer <jwt>' -d '{"n_states": 4}' -H 'Content-Type: application/json'
   ```
