---
description: Verify Phase 5 Production Readiness (ML Training & Hot-Reload)
---

# Phase 5 Verification

This workflow verifies that the ML Service can train a model, promote it, and that the Trading Engine picks it up via the shared volume.

## 1. Start the Stack
// turbo
```bash
docker-compose up -d --build
```

## 2. Trigger Training
Trigger a training run manually via the ML Service API.
```bash
curl -X POST "http://localhost:8015/train?n_states=3&promote=true"
```

## 3. Verify Model Promotion
Check if the model was promoted in the ML Service logs.
```bash
docker logs hmm_ml_service | grep "Promoted"
```

## 4. Verify Engine Hot-Reload
Check if the Engine detected the new model.
```bash
docker logs hmm_engine_binance | grep "Reloading model"
```

## 5. Verify Model File in Engine
Ensure the engine container can see the model file.
```bash
docker exec hmm_engine_binance ls -l /app/engine/models/current/model.joblib
```
