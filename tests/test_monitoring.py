import pandas as pd
import numpy as np
import pytest
from gnss_sentinel.monitoring import reference_histograms, population_stability


def test_drift_separates_stationary_and_shifted_distributions():
    rng=np.random.default_rng(42)
    baseline=pd.DataFrame({"x":rng.normal(size=5000)})
    reference=reference_histograms(baseline,["x"])
    stable=population_stability(reference,pd.DataFrame({"x":rng.normal(size=1000)}))
    shifted=population_stability(reference,pd.DataFrame({"x":rng.normal(5,1,size=1000)}))
    assert stable["features"][0]["level"] == "low"
    assert shifted["features"][0]["level"] == "high"


def test_drift_requires_sufficient_observations():
    with pytest.raises(ValueError,match="50"):
        population_stability({},pd.DataFrame({"x":[1,2]}))
