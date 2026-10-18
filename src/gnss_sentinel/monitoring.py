"""Batch drift diagnostics relative to a model's training-only reference."""
import numpy as np


def reference_histograms(frame, features):
    reference = {}
    for name in features:
        x = frame[name].to_numpy(dtype=float)
        inner = np.unique(np.quantile(x, np.linspace(0, 1, 11)[1:-1]))
        bins = np.r_[-np.inf, inner, np.inf]
        counts, _ = np.histogram(x, bins=bins)
        reference[name] = {"inner_edges": inner.tolist(), "proportions": (counts/counts.sum()).tolist(),
                           "mean": float(x.mean()), "std": float(x.std())}
    return reference


def population_stability(reference, frame):
    if len(frame) < 50:
        raise ValueError("Drift analysis requires at least 50 observations.")
    result = []
    for name, baseline in reference.items():
        x = frame[name].to_numpy(dtype=float)
        if not np.isfinite(x).all():
            raise ValueError("Drift observations must be finite.")
        counts, _ = np.histogram(x, bins=np.r_[-np.inf, baseline["inner_edges"], np.inf])
        actual = (counts+.5)/(counts.sum()+.5*len(counts))
        expected = np.asarray(baseline["proportions"])
        expected = np.maximum(expected, 1e-6); expected /= expected.sum()
        psi = float(np.sum((actual-expected)*np.log(actual/expected)))
        result.append({"feature": name, "psi": psi,
                       "mean_shift_std": float((x.mean()-baseline["mean"])/max(baseline["std"],1e-8)),
                       "level": "high" if psi >= .25 else "moderate" if psi >= .1 else "low"})
    result.sort(key=lambda row: row["psi"], reverse=True)
    return {"rows": len(frame), "features": result, "flagged_features": sum(r["level"] != "low" for r in result),
            "note": "PSI thresholds (0.10/0.25) are configurable research heuristics in code, not calibrated attack decisions. Distribution shift can have benign causes."}
