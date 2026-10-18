import time
import numpy as np
import pytest
from fastapi.testclient import TestClient

from gnss_sentinel.api import create_app
from gnss_sentinel.config import Settings
from gnss_sentinel.datasets import spoofing_fixture, SPOOF_FEATURES


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as c:
        yield c


def test_dashboard_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/overview").json()["counts"]["models"] == 0


def test_auth_and_origin(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, api_key="test-key"))) as c:
        assert c.get("/api/models").status_code == 401
        assert c.get("/api/models", headers={"X-API-Key":"test-key"}).status_code == 200
        assert c.post("/api/demo/seed", headers={"X-API-Key":"test-key","Origin":"https://foreign.example"}).status_code == 403


def test_invalid_inputs_and_missing_model(client):
    assert client.post("/api/signals/simulate",json={"kind":"invalid"}).status_code == 422
    assert client.get("/api/models/does-not-exist/report").status_code == 404
    assert client.post("/api/datasets/upload", files={"file":("bad.csv",b"a,b\n1,2")}).status_code == 422
    assert client.post("/api/signals/upload", files={"file":("bad.csv",b"a,b\n1,2")}).status_code == 422


def test_iq_upload_analyzed(client):
    from gnss_sentinel.signals import synthesize
    import pandas as pd
    x = synthesize("narrowband",samples=512)
    raw = pd.DataFrame({"I":x.real,"Q":x.imag}).to_csv(index=False)
    r=client.post("/api/signals/upload", files={"file":("capture.csv",raw)},data={"sample_rate":"2000000"})
    assert r.status_code == 200
    assert r.json()["sample_count"] == 512
    assert r.json()["origin"] == "uploaded recording"


def test_full_import_train_predict_incident_lifecycle(client):
    frame = spoofing_fixture(samples=800)
    r = client.post("/api/datasets/upload",files={"file":("receiver.csv",frame.to_csv(index=False))},data={"name":"Receiver study"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert "path" not in data
    assert client.get(f"/api/datasets/{data['id']}/sample").status_code == 200
    job = client.post("/api/experiments",json={"dataset_id":data["id"]}).json()
    deadline = time.monotonic()+120
    while time.monotonic()<deadline:
        run=next(j for j in client.get("/api/experiments").json() if j["id"]==job["id"])
        if run["status"] in {"completed","failed"}:
            break
        time.sleep(.1)
    assert run["status"] == "completed", run
    row=frame.iloc[1][SPOOF_FEATURES].to_dict()
    row["CN0"] = 10000  # Force a review incident independently of classifier accuracy.
    r=client.post("/api/predict",json={"model_id":run["model_id"],"rows":[row],"sensor":"=malicious formula"})
    assert r.status_code == 200, r.text
    event_id=r.json()["incident_ids"][0]
    assert client.patch(f"/api/events/{event_id}",json={"status":"resolved"}).json()["status"]=="resolved"
    assert client.get("/api/overview").json()["counts"]["open_incidents"]==0
    export=client.get("/api/events/export")
    assert "'=malicious formula" in export.text
    assert "artifact_path" not in client.get("/api/models").json()[0]
    assert client.get(f"/api/models/{run['model_id']}/report").status_code==200
    drift=client.post("/api/drift",json={"model_id":run["model_id"],"rows":frame[SPOOF_FEATURES].head(100).to_dict(orient="records")})
    assert drift.status_code==200,drift.text
    assert len(drift.json()["features"])==13
    drift_csv=client.post("/api/drift/upload",files={"file":("batch.csv",frame.head(100).to_csv(index=False))},data={"model_id":run["model_id"]})
    assert drift_csv.status_code==200,drift_csv.text


def test_startup_marks_interrupted_jobs_failed(tmp_path):
    app=create_app(Settings(data_dir=tmp_path))
    job=app.state.store.add("jobs",{"status":"running","progress":25})
    with TestClient(app) as c:
        restored=c.get("/api/experiments").json()[0]
        assert restored["id"]==job["id"]
        assert restored["status"]=="failed"
