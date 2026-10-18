# API examples

Base URL: `http://127.0.0.1:8765`. OpenAPI: `/docs` and `/openapi.json`.

If `SENTINEL_API_KEY` is set, send `X-API-Key` for every `/api/` request. `/health` and static dashboard files remain accessible; the dashboard's data calls require the key.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service health |
| GET | `/api/overview` | Counts, recent events, jobs and models |
| GET | `/api/catalog` | Public dataset sources |
| GET / POST | `/api/datasets` / `/api/datasets/upload` | List / import labeled CSV |
| GET | `/api/datasets/{id}/sample` | First eight observations |
| GET | `/api/datasets/{id}/download` | Canonical CSV |
| POST | `/api/demo/seed` | Generate/reuse synthetic example datasets |
| GET / POST | `/api/experiments` | List / enqueue a training job |
| GET | `/api/models` | Model metadata and metrics |
| GET | `/api/models/{id}/report` | Download a JSON report |
| POST | `/api/predict` | Up to 512 feature observations |
| POST | `/api/signals/simulate` | Analyze a labeled offline signal fixture |
| POST | `/api/signals/upload` | Analyze I/Q CSV with sample rate |
| POST | `/api/drift` / `/api/drift/upload` | Compare batch features against training reference |
| GET | `/api/events` | Incident list, optional status and limit |
| PATCH | `/api/events/{id}` | Set open / acknowledged / resolved |
| GET | `/api/events/export` | CSV export with formula-escaped text |

## Example Python client

```python
import time
import httpx

client = httpx.Client(base_url="http://127.0.0.1:8765", timeout=60)
# For a protected instance: headers={"X-API-Key": "..."}
datasets = client.post("/api/demo/seed").raise_for_status().json()
dataset = next(d for d in datasets if d["task"] == "jamming")
job = client.post("/api/experiments", json={"dataset_id": dataset["id"], "seed": 42}).raise_for_status().json()
while True:
    run = next(j for j in client.get("/api/experiments").raise_for_status().json() if j["id"] == job["id"])
    if run["status"] in {"completed", "failed"}:
        break
    time.sleep(2)
if run["status"] != "completed":
    raise RuntimeError(run["stage"])
result = client.post("/api/signals/simulate", json={
    "kind": "chirp", "snr_db": 10, "seed": 123, "model_id": run["model_id"]
}).raise_for_status().json()
print(result["prediction"])
```

## Prediction semantics

The response preserves the model's dataset provenance. `confidence` is the maximum uncalibrated class probability. `top_class` retains the highest-scoring class even when `label` is `uncertain`. `outside_training_range` uses a simple feature-deviation heuristic. `anomaly_score` comes from a normal-only Isolation Forest, when available; negative values indicate its anomaly decision.

`deviations` lists the largest differences from training medians in training-standard-deviation units. These are descriptive diagnostics, not SHAP values, causal explanations, or proof of attack. Classification, anomaly and drift scores answer different questions and should not be combined as probabilities.

Prediction calls may create incidents. Set `record_incident: false` for batch experiments that should not populate the log. Signal Lab creates an incident only when a selected classifier flags a synthetic or uploaded recording. Incident status changes preserve the original prediction.

Error responses use `detail`; invalid data gives 422, unknown IDs 404, invalid credentials 401, unsupported origin writes 403, outdated drift artifacts 409, and a full training queue 429.
