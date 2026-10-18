import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from gnss_sentinel.config import Settings
from gnss_sentinel.datasets import register, spoofing_fixture, validate_frame, SPOOF_FEATURES
from gnss_sentinel.store import Store
from gnss_sentinel.training import split_indices, train_dataset, predict


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    settings = Settings(data_dir=tmp_path_factory.mktemp("training"))
    settings.prepare()
    store = Store(settings.data_dir / "test.db")
    data = register(settings, store, spoofing_fixture(samples=800), "Test sessions", "spoofing", "synthetic")
    model = train_dataset(settings, store, data["id"])
    return settings, store, data, model


def test_groups_never_cross_evaluation_boundaries():
    frame = spoofing_fixture(samples=800)
    train, val, test, _ = split_indices(frame)
    groups = [set(frame.group.iloc[x]) for x in (train,val,test)]
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]
    assert len(set(train)|set(val)|set(test)) == len(frame)


def test_scaler_fits_only_training_partition(trained):
    settings, store, data, model = trained
    artifact = joblib.load(model["artifact_path"])
    splits = json.loads(Path(model["artifact_path"]).with_name("splits.json").read_text())
    frame = pd.read_csv(data["path"])
    expected = frame.iloc[splits["train"]][SPOOF_FEATURES].mean().to_numpy()
    np.testing.assert_allclose(artifact["pipeline"].steps[0][1].mean_, expected)


def test_prediction_and_reporting_survive_reload(trained):
    settings, store, data, model = trained
    fresh = Store(settings.data_dir / "test.db")
    row = spoofing_fixture(seed=55, samples=800).iloc[0][SPOOF_FEATURES].to_dict()
    result = predict(settings, fresh, model["id"], [row])
    assert result["provenance"] == "synthetic"
    p = result["predictions"][0]
    assert sum(p["probabilities"].values()) == pytest.approx(1)
    assert 0 <= p["confidence"] <= 1
    assert len(model["leaderboard"]) == 3
    assert sum(map(sum, model["metrics"]["confusion_matrix"])) == model["split_sizes"]["test"]


def test_extreme_out_of_distribution_input_abstains(trained):
    settings, store, _, model = trained
    row = spoofing_fixture(samples=800).iloc[0][SPOOF_FEATURES].to_dict()
    row["CN0"] = 10000
    assert predict(settings, store, model["id"], [row])["predictions"][0]["label"] == "uncertain"


def test_duplicate_features_rejected():
    frame = spoofing_fixture(samples=100)
    with pytest.raises(ValueError, match="duplicate"):
        validate_frame(pd.concat([frame,frame.iloc[:1]],ignore_index=True))


def test_missing_features_rejected():
    with pytest.raises(ValueError, match="CN0"):
        validate_frame(spoofing_fixture(samples=100).drop(columns="CN0"))


def test_insufficient_groups_rejected():
    frame = spoofing_fixture(samples=100)
    with pytest.raises(ValueError, match="six"):
        split_indices(frame)


def test_no_groups_uses_labeled_fallback():
    _,_,_,strategy = split_indices(spoofing_fixture(samples=100).drop(columns="group"))
    assert "independence unverified" in strategy


def test_changed_dataset_checksum_rejected(tmp_path):
    settings=Settings(data_dir=tmp_path); settings.prepare(); store=Store(tmp_path/"test.db")
    data=register(settings,store,spoofing_fixture(samples=800),"Checksummed","spoofing","synthetic")
    Path(data["path"]).write_text("tampered",encoding="utf-8")
    with pytest.raises(ValueError,match="checksum"):
        train_dataset(settings,store,data["id"])


def test_artifact_tampering_is_rejected(trained, tmp_path):
    settings, store, _, model = trained
    bad_file=settings.data_dir/"models"/"tampered.joblib"
    bad_file.write_bytes(b"not a trusted artifact")
    bad_model=store.add("models",{**model,"artifact_path":str(bad_file)})
    with pytest.raises(ValueError,match="checksum"):
        predict(settings,store,bad_model["id"],[{}])
