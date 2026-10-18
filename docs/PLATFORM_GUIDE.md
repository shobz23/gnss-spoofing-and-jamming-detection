# GNSS Sentinel

An expanded GNSS interference research platform built from the original jamming and GPS spoofing notebooks. It combines offline signal analysis, reproducible machine-learning experiments, an optional deep-learning workflow, and a local analyst dashboard.

## Start here

Python 3.11+ is required. Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m gnss_sentinel.cli demo
.\.venv\Scripts\python.exe -m gnss_sentinel.cli serve
```

Open **http://127.0.0.1:8765**. API documentation is at **http://127.0.0.1:8765/docs**.

On Windows, `powershell -ExecutionPolicy Bypass -File scripts/start.ps1 -Demo` performs initial setup, prepares example models, and launches the application. Omit `-Demo` on subsequent starts. It changes the execution policy for that PowerShell process only.

On Linux/macOS, activate `.venv/bin/activate`, install with `pip install -e '.[dev]'`, then run `gnss-sentinel demo` and `gnss-sentinel serve`.

The demonstration really trains models on generated fixtures. Its scores are **synthetic software demonstrations, not accuracy claims on public datasets or real receivers**. Public datasets are not bundled or silently downloaded. The original notebooks' historical results are separate.

## What's implemented

| Workspace | Working capabilities |
|---|---|
| Overview | Persistent dataset/model/incident counts, latest evaluation, signal spectrum and class distributions |
| Signal Lab | Complex IQ CSV upload, six synthetic signal patterns, short-time FFT, spectrogram, spectrum, 12 signal features, optional model classification |
| Spoofing analysis | 13-feature receiver schema, model probabilities, abstention on low confidence/extreme inputs, normal-reference Isolation Forest |
| Data library | CSV registration, validation, duplicate rejection, SHA-256 fingerprints, previews and downloads |
| Experiments | Bounded background queue, comparison of Random Forest/Extra Trees/logistic regression, grouped splits, model registry and JSON reports |
| Drift monitor | Batch population stability index against a training-only reference, per-feature diagnostics |
| Incidents | Stored prediction evidence, provenance, analyst status changes, CSV export |
| Research & sources | Original public dataset links, credits, integration notes and method references |

Supporting components include a Python CLI, optional ResNet18 training/inference, raw recording feature extraction, FastAPI/OpenAPI, SQLite persistence, Docker Compose, CI, and automated integration tests.

## Repository layout

```text
src/gnss_sentinel/
  api.py             HTTP API, training queue, static dashboard
  datasets.py        Input contracts, registry, deterministic fixtures
  signals.py         Complex IQ DSP and signal feature extraction
  training.py        Splits, model comparison, anomaly reference, persistence
  monitoring.py      Distribution shift diagnostics
  vision.py          Optional ResNet18 image pipeline
  store.py           SQLite registry and incident persistence
  config.py          Environment-based configuration
  cli.py             Command-line workflows
  catalog.json       Public sources and provenance notes
  web/               HTML, CSS and JavaScript dashboard; no Node build needed
scripts/
  start.ps1          Windows launcher
  extract_iq_features.py
tests/               DSP, data integrity, evaluation and API regression tests
docs/                Architecture, data guide, API examples, research references
runtime/             Ignored datasets, database and generated model artifacts
Jamming Detection/   Original research notebooks
GPS Spoofing Detection/  Original research notebook
```

## Evaluation protocol

1. Validate numeric features, labels, duplicate rows and optional capture groups.
2. Split before fitting any transformation. With `group`, capture/session IDs remain disjoint. Without it, stratified random splitting is labeled as lacking verified session independence.
3. Fit each scaler and classifier on the training partition only. Use class weights rather than balancing the test set.
4. Select the algorithm by validation macro F1.
5. Evaluate the selected fitted model once on the test partition. Save confusion matrix, per-class metrics, dataset fingerprint, seed, package version and exact split indices.
6. Fit the anomaly detector and drift reference only on training data. Isolation Forest is available when at least 20 normal training samples are identifiable as `authentic`, `clean`, `0` or `0.0`.

Default split proportions are approximately 70/15/15. Group sizes can change exact proportions. The pipeline rejects splits that omit a class; it never silently falls back to row-level splitting when supplied groups fail.

Predictions abstain with `uncertain` when the highest model score is below 0.55 or a feature is over 8 training standard deviations from its training median. These defaults are research heuristics, not calibrated operating thresholds. Numeric class `0` is assumed normal **only for the anomaly/incident policy**; verify or remap labels before using another dataset.

## Use recorded datasets

See [data contracts and imports](DATA_GUIDE.md). Register a CSV and train:

```powershell
.\.venv\Scripts\python.exe -m gnss_sentinel.cli import receiver.csv --name "Receiver session study" --source "Capture campaign / dataset DOI"
.\.venv\Scripts\python.exe -m gnss_sentinel.cli train DATASET_ID --seed 42
```

For raw IQ recordings, create a manifest with `path,label,group,sample_rate`, then:

```powershell
.\.venv\Scripts\python.exe scripts/extract_iq_features.py manifest.csv features.csv
.\.venv\Scripts\python.exe -m gnss_sentinel.cli import features.csv --task jamming --name "Recorded interference study"
```

## Optional deep learning

Install `.[vision]`. On Windows, use a **short environment path** because this repository's long name can exceed filesystem path limits when installing PyTorch:

```powershell
python -m venv C:\gnss-env
C:\gnss-env\Scripts\python.exe -m pip install -e ".[vision]"
C:\gnss-env\Scripts\python.exe -m gnss_sentinel.cli train-images DATA_ROOT --output runtime/vision/run-001 --epochs 10 --pretrained
C:\gnss-env\Scripts\python.exe -m gnss_sentinel.cli predict-image runtime/vision/run-001/best.pt example.png
```

Choose a short directory you have permission to create. `--pretrained` downloads official torchvision weights on first use; omitting it trains from scratch. `DATA_ROOT` must contain `train`, `val`, `test`, each with identical class subdirectories. The output directory must not already exist.

This workflow uses a fixed class mapping, checks exact image duplicates across splits, selects checkpoints on validation macro F1, reloads the best checkpoint, and then evaluates the untouched test split. Related captures still need to be separated by the researcher; hash checks alone cannot detect near-duplicates. Image experiments are currently CLI artifacts rather than tabular dashboard registry entries.

## API and deployment

See [API examples](API.md). All generated runtime state defaults to `runtime/`. Override with `SENTINEL_DATA_DIR` or CLI `--data-dir` before the command. Set `SENTINEL_API_KEY` to require the `X-API-Key` header on every `/api/` endpoint. Enter the same key in dashboard workspace settings; it is kept in session storage.

```powershell
$env:SENTINEL_API_KEY = "replace-with-your-own-long-random-value"
docker compose up --build
```

Compose binds to the local machine and persists `/data` in a named volume. For remote use, configure TLS and access control in a reverse proxy. Never accept arbitrary serialized model uploads; the API loads only checksummed artifacts generated in its local registry.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src scripts
```

Optional vision smoke test: `python -m pytest tests/test_vision.py -q` in an environment with PyTorch. Test data is temporary and synthetic. See `docs/VERIFICATION.md` for checks actually performed on the development machine.

## Scale and current boundaries

This release is a substantial **single-node research platform**. It does not claim a measured multi-tenant production capacity. SQLite, one training worker, and local artifacts are deliberate starting constraints. Do not run multiple API worker processes against this embedded queue. The [architecture guide](ARCHITECTURE.md) describes the migration path to shared storage, PostgreSQL, external workers, and receiver ingestion.

There is no attached SDR, live RF monitoring, GNSS acquisition/tracking engine, real-time attack attribution, or field-validated safety guarantee. Offline fixtures are abstract signal patterns; a pulsed fixture is not a validated DME model. The deep-learning module and Docker configuration have separate verification status. A model trained on synthetic features needs retraining and external evaluation before use with recorded signals.

## Attribution

Original work and notebook links are retained in [the original README](ORIGINAL_README.md). The source repository did not include a license file when scanned; this expansion does not assign a new license to the original authors' material. Review upstream and dataset terms before redistribution. See [research references](RESEARCH.md).
