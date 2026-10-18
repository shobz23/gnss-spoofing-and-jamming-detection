import numpy as np
import pytest
from gnss_sentinel.signals import SIGNAL_CLASSES, IQ_FEATURES, analyze, features, synthesize


@pytest.mark.parametrize("kind", SIGNAL_CLASSES)
def test_signal_analysis_has_finite_features_and_aligned_axes(kind):
    x = synthesize(kind, seed=23)
    result = analyze(x)
    assert list(result["features"]) == IQ_FEATURES
    assert np.isfinite(list(result["features"].values())).all()
    assert len(result["spectrogram_db"]) == len(result["time_ms"])
    assert len(result["spectrogram_db"][0]) == len(result["frequency_khz"])


def test_narrowband_is_more_spectrally_concentrated_than_noise():
    clean = features(synthesize("clean"))
    tone = features(synthesize("narrowband", snr_db=25))
    assert tone["spectral_entropy"] < clean["spectral_entropy"]
    assert tone["peak_fraction"] > clean["peak_fraction"]


@pytest.mark.parametrize("bad", [np.zeros(1024), np.ones(10), np.full(1024, np.nan)])
def test_invalid_recordings_rejected(bad):
    with pytest.raises(ValueError):
        analyze(bad)


def test_signal_fixtures_reproducible():
    assert np.array_equal(synthesize("chirp", seed=9), synthesize("chirp", seed=9))
