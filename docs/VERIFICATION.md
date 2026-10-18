# Verification record

Development date: 11 October 2026 (Asia/Calcutta).

## Executed successfully

- **30 tests passed** in the full suite, including the opt-in ResNet18 smoke test. Runtime: 28.57 seconds on the development machine.
- DSP tests covered all six synthetic signal classes, finite feature values, aligned spectrogram axes, invalid recordings and reproducibility.
- Evaluation tests confirmed disjoint groups, training-only scaler statistics, prediction after artifact reload, out-of-range abstention, duplicate rejection and dataset/model tamper detection.
- End-to-end API tests covered CSV import, background training, prediction, incident creation and resolution, CSV export, JSON report download, and both drift APIs.
- Access tests checked API keys, cross-origin write rejection and missing/invalid inputs.
- The vision smoke test trained ResNet18 on temporary random images for one epoch, saved/reloaded the selected checkpoint, predicted an image, and rejected cross-split duplicates. This validates the workflow, not image-classification quality.
- Both demonstration tasks completed real training. Synthetic spoofing test macro F1: approximately **0.9798**. Synthetic jamming-feature test macro F1: approximately **0.9917**. These are generated-fixture results, not real-world benchmarks.
- Python compilation passed for `src` and `scripts`.
- JavaScript syntax check passed with Node `--check`.
- `git diff --check` passed.
- The API server started successfully on `http://127.0.0.1:8765`.

## Limits of verification

- Browser automation was denied permission to access the local URL. No browser visual inspection or interactive browser test is claimed.
- Docker was not available in the development shell. Dockerfile/Compose are supplied but were not built or run here.
- Public datasets were researched and documented, but not downloaded or used to train these demonstration models.
- No physical GNSS receiver, SDR, real-time feed, GPU training, external load test, or field trial was performed.
- The local dependency set produced one non-failing Starlette deprecation warning about its test client's httpx backend.
- CI configuration is included; a hosted CI run was not triggered.

## Local environments

The repository's `.venv` supports the core platform. A PyTorch installation attempt there encountered Windows path-length limits. A complete environment with the optional vision packages was successfully installed at:

```text
C:\Users\HP\Documents\Codex\gnss-sentinel-env
```

The full 30-test run and final preview server used that shorter environment. No global Windows long-path setting was changed.

To rerun all tests from the project directory:

```powershell
$env:SENTINEL_TEST_VISION = '1'
& 'C:\Users\HP\Documents\Codex\gnss-sentinel-env\Scripts\python.exe' -m pytest -q
```

Keep this verification record distinct from future benchmark reports on recorded datasets.
