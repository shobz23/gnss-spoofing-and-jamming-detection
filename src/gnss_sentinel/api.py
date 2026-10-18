import csv
import io
import json
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings
from .datasets import catalog, import_csv, register, spoofing_fixture, iq_fixture, validate_frame
from .signals import analyze, synthesize
from .store import Store, now
from .training import predict, train_dataset, load_artifact
from .monitoring import population_stability

log = logging.getLogger("sentinel")


class TrainingRequest(BaseModel):
    dataset_id: str
    seed: int = Field(default=42, ge=0, le=2**31-1)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    model_id: str
    rows: list[dict[str, float]] = Field(min_length=1, max_length=512)
    sensor: str = Field(default="Local receiver", min_length=1, max_length=100)
    record_incident: bool = True


class SimulationRequest(BaseModel):
    kind: Literal["clean", "narrowband", "chirp", "pulsed", "am", "fm"] = "chirp"
    snr_db: float = Field(default=10, ge=-20, le=35, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=2**31-1)
    model_id: str | None = None


class EventUpdate(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]


class DriftRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    model_id: str
    rows: list[dict[str, float]] = Field(min_length=50, max_length=5000)


def public_record(record):
    return {k: v for k, v in record.items() if k not in {"path", "artifact_path", "report_path"}}


def create_app(settings=None):
    settings = settings or Settings()
    settings.prepare()
    store = Store(settings.data_dir / "sentinel.db")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="training")
    slots = threading.BoundedSemaphore(3)

    @asynccontextmanager
    async def lifespan(app):
        for job in store.list("jobs", 10000):
            if job["status"] in {"queued", "running"}:
                store.update("jobs", job["id"], {"status": "failed", "stage": "Interrupted by previous server shutdown; submit again.", "finished": now()})
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="GNSS Sentinel", version=__version__, lifespan=lifespan,
                  description="Local GNSS interference research platform. Synthetic and uploaded data retain provenance.")
    app.state.store, app.state.settings = store, settings

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path.startswith("/api/") and settings.api_key:
            supplied = request.headers.get("X-API-Key", "")
            if not secrets.compare_digest(supplied, settings.api_key):
                return JSONResponse({"detail": "A valid X-API-Key is required."}, status_code=401)
        # Browser writes must originate from the same host; CLI clients need no Origin.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin writes are disabled."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(ValueError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing_record(request, exc):
        return JSONResponse({"detail": "Requested record does not exist."}, status_code=404)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/overview")
    def overview():
        return {"counts": store.summary(), "models": [public_record(m) for m in store.list("models", 8)],
                "events": store.list("events", 20), "jobs": store.list("jobs", 10), "time": now()}

    @app.get("/api/catalog")
    def sources():
        return catalog()

    @app.get("/api/datasets")
    def datasets():
        return [public_record(d) for d in store.list("datasets")]

    @app.post("/api/datasets/upload", status_code=201)
    async def upload(file: UploadFile = File(...), name: str = Form("Imported telemetry"), task: Literal["spoofing", "jamming"] = Form("spoofing")):
        raw = await file.read(settings.max_upload_bytes+1)
        await file.close()
        if not 1 <= len(name.strip()) <= 120:
            raise ValueError("Dataset name must contain 1–120 characters.")
        try:
            return public_record(import_csv(settings, store, raw, name.strip(), task=task))
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ValueError("Cannot parse file as a UTF-8 CSV.") from exc

    @app.get("/api/datasets/{dataset_id}/sample")
    def sample(dataset_id: str):
        data = store.get("datasets", dataset_id)
        frame = pd.read_csv(data["path"], nrows=8)
        return {"columns": list(frame.columns), "rows": frame.to_dict(orient="records")}

    @app.get("/api/datasets/{dataset_id}/download")
    def download_dataset(dataset_id: str):
        data = store.get("datasets", dataset_id)
        return FileResponse(data["path"], media_type="text/csv", filename=f"dataset-{dataset_id[:8]}.csv")

    @app.post("/api/demo/seed", status_code=201)
    def seed_demo():
        existing = store.list("datasets", 10000)
        result = []
        for task, name, factory in [("spoofing", "Synthetic receiver sessions", spoofing_fixture), ("jamming", "Synthetic IQ signal features", iq_fixture)]:
            match = next((d for d in existing if d["source"] == "Sentinel deterministic fixture v1" and d["task"] == task), None)
            result.append(public_record(match or register(settings, store, factory(), name, task, "synthetic", "Sentinel deterministic fixture v1")))
        return result

    def train_job(job_id, dataset_id, seed):
        try:
            store.update("jobs", job_id, {"status": "running", "progress": 5, "stage": "Validating dataset and splits"})
            model = train_dataset(settings, store, dataset_id, seed, job_id)
            store.update("jobs", job_id, {"status": "completed", "model_id": model["id"], "progress": 100, "stage": "Evaluation complete", "finished": now()})
        except Exception as exc:
            log.exception("Training failed")
            store.update("jobs", job_id, {"status": "failed", "stage": str(exc)[:500], "finished": now()})
        finally:
            slots.release()

    @app.post("/api/experiments", status_code=202)
    def start_training(body: TrainingRequest):
        dataset = store.get("datasets", body.dataset_id)
        if not slots.acquire(blocking=False):
            raise HTTPException(429, "Training queue is full (one active, two queued). Try again after a job completes.")
        try:
            job = store.add("jobs", {"dataset_id": body.dataset_id, "dataset_name": dataset["name"], "seed": body.seed,
                "status": "queued", "progress": 0, "stage": "Queued", "provenance": dataset["provenance"]})
            executor.submit(train_job, job["id"], body.dataset_id, body.seed)
        except Exception:
            slots.release()
            raise
        return job

    @app.get("/api/experiments")
    def jobs():
        return store.list("jobs")

    @app.get("/api/models")
    def models():
        return [public_record(m) for m in store.list("models")]

    @app.get("/api/models/{model_id}/report")
    def model_report(model_id: str):
        model = store.get("models", model_id)
        return JSONResponse(public_record(model), headers={"Content-Disposition": f'attachment; filename="model-{model_id[:8]}.json"'})

    def record_prediction(result, sensor, input_origin):
        pred = result["predictions"][0]
        if pred["label"] not in {"authentic", "clean", "0", "0.0"} or pred["anomaly"]:
            return store.add("events", {"sensor": sensor, "task": result["task"], "label": pred["label"], "confidence": pred["confidence"],
                "model_id": result["model_id"], "provenance": result["provenance"], "input_origin": input_origin,
                "severity": "review" if pred["label"] == "uncertain" else "high", "status": "open", "prediction": pred})
        return None

    @app.post("/api/predict")
    def prediction(body: PredictionRequest):
        result = predict(settings, store, body.model_id, body.rows)
        incidents = []
        if body.record_incident:
            for row in result["predictions"]:
                event = record_prediction({**result, "predictions": [row]}, body.sensor, "submitted telemetry")
                if event:
                    incidents.append(event["id"])
        return {**result, "incident_ids": incidents}

    @app.post("/api/signals/simulate")
    def simulation(body: SimulationRequest):
        result = analyze(synthesize(body.kind, body.snr_db, body.seed))
        result.update({"origin": "synthetic", "fixture_class": body.kind})
        if body.model_id:
            if store.get("models", body.model_id)["task"] != "jamming":
                raise ValueError("Select a jamming model for IQ analysis.")
            prediction_result = predict(settings, store, body.model_id, [result["features"]])
            result["prediction"] = prediction_result
            event = record_prediction(prediction_result, "Signal Lab", "synthetic")
            result["incident_id"] = event["id"] if event else None
        return result

    @app.post("/api/drift")
    def drift(body: DriftRequest):
        model, artifact = load_artifact(settings, store, body.model_id)
        if "drift_reference" not in artifact:
            raise HTTPException(409, "Retrain this model to generate a drift reference.")
        frame = validate_frame(pd.DataFrame(body.rows), model["task"], require_labels=False)
        return {"model_id": body.model_id, "provenance": model["provenance"],
                **population_stability(artifact["drift_reference"], frame)}

    @app.post("/api/drift/upload")
    async def drift_upload(file: UploadFile = File(...), model_id: str = Form(...)):
        raw = await file.read(settings.max_upload_bytes+1)
        await file.close()
        if len(raw) > settings.max_upload_bytes:
            raise ValueError("CSV exceeds 20 MB.")
        try:
            frame = pd.read_csv(io.BytesIO(raw), nrows=5001)
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ValueError("Cannot parse file as a UTF-8 CSV.") from exc
        if not 50 <= len(frame) <= 5000:
            raise ValueError("Drift analysis accepts 50–5000 observations.")
        model, artifact = load_artifact(settings, store, model_id)
        if "drift_reference" not in artifact:
            raise HTTPException(409, "Retrain this model to generate a drift reference.")
        frame = validate_frame(frame, model["task"], require_labels=False)
        return {"model_id": model_id, "provenance": model["provenance"],
                **population_stability(artifact["drift_reference"], frame)}

    @app.post("/api/signals/upload")
    async def upload_iq(file: UploadFile = File(...), sample_rate: float = Form(2_000_000), model_id: str = Form("")):
        raw = await file.read(settings.max_upload_bytes+1)
        await file.close()
        if len(raw) > settings.max_upload_bytes:
            raise ValueError("Recording exceeds 20 MB.")
        try:
            frame = pd.read_csv(io.BytesIO(raw), nrows=131073)
        except (pd.errors.ParserError, UnicodeDecodeError) as exc:
            raise ValueError("Recording must be a UTF-8 CSV with I and Q columns.") from exc
        if not {"I", "Q"}.issubset(frame.columns):
            raise ValueError("Recording CSV needs I and Q columns.")
        result = analyze(frame.I.to_numpy(dtype=float) + 1j*frame.Q.to_numpy(dtype=float), sample_rate)
        result["origin"] = "uploaded recording"
        if model_id:
            if store.get("models", model_id)["task"] != "jamming":
                raise ValueError("Select a jamming model for IQ analysis.")
            result["prediction"] = predict(settings, store, model_id, [result["features"]])
            event = record_prediction(result["prediction"], "Uploaded IQ", "uploaded recording")
            result["incident_id"] = event["id"] if event else None
        return result

    @app.get("/api/events")
    def events(status: Literal["all", "open", "acknowledged", "resolved"] = "all", limit: int = Query(200, ge=1, le=2000)):
        rows = store.list("events", limit)
        return rows if status == "all" else [row for row in rows if row["status"] == status]

    @app.patch("/api/events/{event_id}")
    def update_event(event_id: str, body: EventUpdate):
        return store.update("events", event_id, {"status": body.status, "updated": now()})

    @app.get("/api/events/export")
    def export_events():
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=["id", "created", "sensor", "task", "label", "confidence", "provenance", "input_origin", "status"], extrasaction="ignore")
        writer.writeheader()
        for row in store.list("events", 100000):
            # Spreadsheet formula injection protection for user-supplied sensor names.
            safe = {k: ("'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v) for k, v in row.items()}
            writer.writerow(safe)
        return Response(stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="sentinel-incidents.csv"'})

    web = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/")
    def index():
        return FileResponse(web / "index.html")

    return app
