"""Train-only preprocessing, validation-based selection, one final test evaluation."""
import hashlib
import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .datasets import SPOOF_FEATURES, validate_frame
from .signals import IQ_FEATURES
from .monitoring import reference_histograms


def split_indices(frame, seed=42):
    indices = np.arange(len(frame))
    labels = frame.label
    if "group" in frame:
        if frame.group.nunique() < 6:
            raise ValueError("Grouped evaluation needs at least six independent sessions.")
        train, rest = next(GroupShuffleSplit(n_splits=1, test_size=.3, random_state=seed).split(indices, labels, frame.group))
        val_local, test_local = next(GroupShuffleSplit(n_splits=1, test_size=.5, random_state=seed).split(rest, labels.iloc[rest], frame.group.iloc[rest]))
        val, test = rest[val_local], rest[test_local]
        strategy = "grouped 70/15/15 (approximate by groups)"
    else:
        train, rest = train_test_split(indices, test_size=.3, stratify=labels, random_state=seed)
        val, test = train_test_split(rest, test_size=.5, stratify=labels.iloc[rest], random_state=seed)
        strategy = "stratified random 70/15/15; session independence unverified"
    classes = set(labels)
    for name, subset in [("train", train), ("validation", val), ("test", test)]:
        if set(labels.iloc[subset]) != classes:
            raise ValueError(f"The {name} split is missing classes. Supply more independent groups containing every class.")
    return train, val, test, strategy


def metrics(y, pred, classes):
    return {"accuracy": float(accuracy_score(y, pred)), "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
            "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
            "confusion_matrix": confusion_matrix(y, pred, labels=classes).tolist(),
            "classification_report": classification_report(y, pred, labels=classes, output_dict=True, zero_division=0)}


def train_dataset(settings, store, dataset_id, seed=42, job_id=None):
    started = time.perf_counter()
    dataset = store.get("datasets", dataset_id)
    raw = Path(dataset["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != dataset["sha256"]:
        raise ValueError("Dataset checksum changed after registration.")
    frame = validate_frame(pd.read_csv(dataset["path"]), dataset["task"])
    feature_names = dataset["features"]
    x, y = frame[feature_names], frame.label
    train, val, test, strategy = split_indices(frame, seed)
    candidates = {
        "Random forest": make_pipeline(StandardScaler(), RandomForestClassifier(n_estimators=140, min_samples_leaf=2, class_weight="balanced", n_jobs=2, random_state=seed)),
        "Extra trees": make_pipeline(StandardScaler(), ExtraTreesClassifier(n_estimators=140, min_samples_leaf=2, class_weight="balanced", n_jobs=2, random_state=seed)),
        "Logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1500, class_weight="balanced", random_state=seed)),
    }
    leaderboard = []
    best, best_score, best_name = None, -1, ""
    for position, (name, model) in enumerate(candidates.items()):
        if job_id:
            store.update("jobs", job_id, {"stage": f"Training {name}", "progress": 15 + position*25})
        model.fit(x.iloc[train], y.iloc[train])
        pred = model.predict(x.iloc[val])
        score = float(f1_score(y.iloc[val], pred, average="macro", zero_division=0))
        leaderboard.append({"algorithm": name, "validation_macro_f1": score, "validation_accuracy": float(accuracy_score(y.iloc[val], pred))})
        if score > best_score:
            best, best_score, best_name = model, score, name
    classes = list(map(str, best.classes_))
    report = metrics(y.iloc[test], best.predict(x.iloc[test]), classes)
    # Normal reference is learned exclusively from the training partition.
    normal = y.iloc[train].isin(["authentic", "clean", "0", "0.0"]).to_numpy()
    anomaly = None
    if normal.sum() >= 20:
        anomaly = make_pipeline(StandardScaler(), IsolationForest(n_estimators=100, contamination=.05, random_state=seed, n_jobs=2))
        anomaly.fit(x.iloc[train].iloc[np.flatnonzero(normal)])
    medians = x.iloc[train].median().to_numpy()
    spread = np.maximum(x.iloc[train].std().to_numpy(), 1e-8)
    classifier = best.steps[-1][1]
    importance = getattr(classifier, "feature_importances_", None)
    if importance is None:
        importance = np.mean(np.abs(classifier.coef_), axis=0)
    importance = importance / (np.sum(importance) + 1e-12)
    splits = {"train": train.tolist(), "validation": val.tolist(), "test": test.tolist()}
    metadata = {"name": f"{dataset['task'].title()} · {best_name}", "task": dataset["task"], "algorithm": best_name,
        "dataset_id": dataset_id, "dataset_name": dataset["name"], "dataset_sha256": dataset["sha256"],
        "provenance": dataset["provenance"], "source": dataset["source"], "classes": classes,
        "features": feature_names, "seed": seed, "split_strategy": strategy,
        "split_sizes": {key: len(value) for key, value in splits.items()}, "metrics": report,
        "leaderboard": leaderboard, "anomaly_available": anomaly is not None,
        "feature_importance": dict(zip(feature_names, map(float, importance))),
        "duration_seconds": round(time.perf_counter()-started, 2), "sklearn_version": sklearn.__version__,
        "notes": ["Model selected by validation macro F1; test set evaluated only after selection.",
                  "Prediction probabilities are uncalibrated model scores.",
                  "Synthetic scores demonstrate the software, not field performance." if dataset["provenance"] == "synthetic" else "External field validation remains necessary."]}
    # Publish the registry entry only after the complete artifact exists.
    import uuid
    artifact_id = uuid.uuid4().hex
    folder = settings.data_dir / "models" / artifact_id
    folder.mkdir()
    artifact_path = folder / "pipeline.joblib"
    joblib.dump({"pipeline": best, "anomaly": anomaly, "median": medians, "spread": spread, "features": feature_names,
                 "drift_reference": reference_histograms(x.iloc[train], feature_names)}, artifact_path)
    (folder / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (folder / "report.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["artifact_path"] = str(artifact_path)
    metadata["artifact_sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    metadata["report_path"] = str(folder / "report.json")
    return store.add("models", metadata)


def load_artifact(settings, store, model_id):
    model = store.get("models", model_id)
    artifact_path = Path(model["artifact_path"]).resolve()
    if not artifact_path.is_relative_to((settings.data_dir / "models").resolve()):
        raise ValueError("Model artifact is outside the trusted local registry.")
    if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != model["artifact_sha256"]:
        raise ValueError("Model checksum mismatch.")
    # Only artifacts generated locally are accepted; there is no pickle upload endpoint.
    artifact = joblib.load(artifact_path)
    return model, artifact


def predict(settings, store, model_id, rows):
    model, artifact = load_artifact(settings, store, model_id)
    frame = validate_frame(pd.DataFrame(rows), model["task"], require_labels=False)[model["features"]]
    probabilities = artifact["pipeline"].predict_proba(frame)
    anomaly_scores = artifact["anomaly"].decision_function(frame) if artifact["anomaly"] is not None else None
    output = []
    for index, probability in enumerate(probabilities):
        winner = int(np.argmax(probability))
        z = np.abs((frame.iloc[index].to_numpy() - artifact["median"])/artifact["spread"])
        reasons = [{"feature": model["features"][int(j)], "deviation_std": round(float(z[j]), 2)} for j in np.argsort(z)[-3:][::-1]]
        confidence = float(probability[winner])
        outside = bool(np.max(z) > 8)
        output.append({"label": model["classes"][winner] if confidence >= .55 and not outside else "uncertain",
            "top_class": model["classes"][winner], "confidence": confidence,
            "probabilities": dict(zip(model["classes"], map(float, probability))),
            "outside_training_range": outside, "deviations": reasons,
            "anomaly": bool(anomaly_scores[index] < 0) if anomaly_scores is not None else None,
            "anomaly_score": float(anomaly_scores[index]) if anomaly_scores is not None else None})
    return {"model_id": model_id, "task": model["task"], "provenance": model["provenance"], "predictions": output}
