import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .signals import SIGNAL_CLASSES, IQ_FEATURES, synthesize, features

SPOOF_FEATURES = ["PRN", "DO", "PD", "RX", "TOW", "CP", "EC", "LC", "PC", "PIP", "PQP", "TCD", "CN0"]
SPOOF_CLASSES = ["authentic", "simplistic", "intermediate", "sophisticated"]


def validate_frame(frame, task="spoofing", require_labels=True):
    expected = SPOOF_FEATURES if task == "spoofing" else IQ_FEATURES
    missing = set(expected) - set(frame.columns)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    if frame.empty:
        raise ValueError("Dataset is empty.")
    frame = frame.copy()
    for name in expected:
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    if not np.isfinite(frame[expected].to_numpy(dtype=float)).all():
        raise ValueError("Features must be finite numbers; remove missing or infinite values.")
    if np.max(np.abs(frame[expected].to_numpy(dtype=float))) > 1e15:
        raise ValueError("Feature values exceed the supported numeric range.")
    if require_labels:
        if "label" not in frame and "Output" in frame:
            frame["label"] = frame["Output"]
        if "label" not in frame:
            raise ValueError("Training data requires a label or Output column.")
        if frame.label.isna().any():
            raise ValueError("Labels must not be empty.")
        frame["label"] = frame.label.astype(str).str.strip()
        if frame.label.eq("").any() or frame.label.str.len().max() > 80:
            raise ValueError("Labels must contain 1–80 characters.")
        if not 2 <= frame.label.nunique() <= 20:
            raise ValueError("Training data must contain 2–20 classes.")
        if frame.label.value_counts().min() < 10:
            raise ValueError("Each class needs at least 10 samples.")
        duplicates = frame.duplicated(subset=expected, keep=False)
        if duplicates.any():
            raise ValueError(f"Found {int(duplicates.sum())} rows with duplicate features. Deduplicate before registration to avoid split leakage.")
    if "group" in frame:
        if frame.group.isna().any() or frame.group.astype(str).str.strip().eq("").any():
            raise ValueError("Group identifiers must not be empty.")
        frame["group"] = frame.group.astype(str)
    return frame


def register(settings, store, frame, name, task, provenance, source="User import"):
    frame = validate_frame(frame, task)
    raw = frame.to_csv(index=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    path = settings.data_dir / "datasets" / f"{digest}.csv"
    path.write_bytes(raw)
    return store.add("datasets", {"name": name, "task": task, "provenance": provenance, "source": source,
        "sha256": digest, "path": str(path), "rows": len(frame), "features": SPOOF_FEATURES if task == "spoofing" else IQ_FEATURES,
        "classes": frame.label.value_counts().sort_index().to_dict(), "has_groups": "group" in frame,
        "groups": int(frame.group.nunique()) if "group" in frame else 0})


def import_csv(settings, store, raw, name, provenance="uploaded", task="spoofing"):
    if len(raw) > settings.max_upload_bytes:
        raise ValueError("CSV exceeds the 20 MB upload limit. Use the local CLI for larger files.")
    frame = pd.read_csv(io.BytesIO(raw), nrows=settings.max_rows+1)
    if len(frame) > settings.max_rows:
        raise ValueError(f"CSV exceeds {settings.max_rows} rows. Use the local CLI.")
    return register(settings, store, frame, name, task, provenance)


def spoofing_fixture(seed=42, samples=1200):
    rng = np.random.default_rng(seed)
    records = []
    for index in range(samples):
        label = index % 4
        row = [rng.integers(1, 33), rng.normal(-400, 950), rng.normal(2.1e7, 8e5),
               rng.uniform(0, 3600), rng.uniform(100000, 103600), rng.normal(1e6, 1e5),
               rng.normal(1, .12), rng.normal(1, .12), rng.normal(1.3, .15),
               rng.normal(1, .13), rng.normal(0, .1), rng.normal(0, .05), rng.normal(43, 3)]
        if label == 1:
            row[6] += .6; row[7] -= .3; row[12] += 9
        elif label == 2:
            row[9] += .45; row[10] += .5; row[11] += .2
        elif label == 3:
            row[6] += .15; row[7] -= .15; row[10] += .2; row[11] += .1; row[12] += 3
        records.append(dict(zip(SPOOF_FEATURES, row)) | {"label": SPOOF_CLASSES[label], "group": f"session-{index//40:03d}"})
    return pd.DataFrame(records)


def iq_fixture(seed=42, per_class=100):
    records = []
    rng = np.random.default_rng(seed)
    for kind in SIGNAL_CLASSES:
        for index in range(per_class):
            x = synthesize(kind, rng.uniform(-5, 20), seed + index + SIGNAL_CLASSES.index(kind)*10000)
            records.append(features(x) | {"label": kind, "group": f"capture-{index//10:03d}"})
    return pd.DataFrame(records)


def catalog():
    return json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
