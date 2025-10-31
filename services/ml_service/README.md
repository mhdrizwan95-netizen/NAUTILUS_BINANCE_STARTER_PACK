# ML Service (HMM) — Auto-train + Hot-reload

This containerized service trains Hidden Markov Models on your market data and exposes a FastAPI endpoint for inference. It promotes new models automatically when validation log-likelihood improves, and the inference server hot-reloads when a new model is promoted.

## TL;DR

```bash
# At project root
cp .env.example .env  # then edit as needed
docker compose -f docker-compose.yml -f compose.ml.yml up -d --build
```

Place your CSVs with at least `timestamp` and `close` columns into the shared `data` volume (or the host path you bind to `/data`).

## Endpoints

- `GET /health` — liveness
- `POST /train` — manual train (requires role `trainer` or `admin` if auth enabled)
- `POST /predict` — `{ "logret": [ ... ] }` -> regime probabilities for the last point
- `GET /model` — info about the active model and registry size

## RBAC / JWT

Set `REQUIRE_AUTH=true` and configure `JWT_SECRET` (HS256) or `JWT_PUBLIC_KEY` (RS/ES). Incoming JWT must include a `role` claim. Allowed roles:
- `reader` — for `GET` endpoints
- `trainer` — can POST `/train`
- `admin` — full access (not all admin endpoints are exposed yet to keep surface minimal)

## How it reloads

- Trained models are saved under `/models/registry/<version>/`.
- Promotion updates a symlink `/models/current` and touches `version.txt` to trigger a filesystem watcher in the inference app.
- Inference layer (`/predict`) reloads in-memory model on changes without a restart.

## Rollback

Manually repoint the symlink to an older version directory inside `/models/registry` and touch `version.txt`. The server will reload the previous model automatically.
