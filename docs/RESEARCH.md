# Research and implementation references

Sources reviewed while extending the repository, 11 October 2026. External pages are references, not runtime dependencies. No third-party source code was copied into the platform.

1. **Image datasets for jammer classification in GNSS** — Morales Ferre, Lohan and De la Fuente. [Zenodo record 3783969](https://zenodo.org/records/3783969). Original notebooks download this archive; retain its official split for comparable experiments. Publisher-page retrieval timed out during this work, so file details and licensing should be checked at acquisition.
2. **Raw IQ dataset for GNSS GPS jamming signal classification** — Swinney and Woods. [Zenodo record 4629685](https://zenodo.org/records/4629685), DOI 10.5281/zenodo.4629685. This is a separate raw-IQ resource, not the image archive used by the notebooks. It informed the addition of raw complex-signal analysis and a manifest-based feature extraction tool.
3. **A DATASET for GPS Spoofing Detection on Unmanned Aerial System** — Ghilas Aissou. [Mendeley Data, version 1](https://data.mendeley.com/datasets/z7dj3yyzt8/1), DOI 10.17632/z7dj3yyzt8.1. Publisher lists CC BY 4.0. The platform retains the original notebook's thirteen receiver feature columns and provides CSV import; it does not redistribute the dataset.
4. **scikit-learn: Common pitfalls** — [Official guidance](https://scikit-learn.org/stable/common_pitfalls.html). Applied through train-only pipeline fitting and fixed evaluation partitions.
5. **scikit-learn: Cross-validation** — [Official guidance](https://scikit-learn.org/stable/modules/cross_validation.html). Applied through capture-group separation when session identifiers exist, and a clearly labeled random fallback otherwise.
6. **SciPy: ShortTimeFFT** — [Official API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.ShortTimeFFT.html). Used for centered, two-sided complex-signal time-frequency analysis.
7. **torchvision: ResNet18** — [Official API](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.resnet18.html). Used in the optional image workflow, with explicit normalization and saved class mappings.
8. **Original paper linked in the repository** — [arXiv 2501.02352](https://arxiv.org/abs/2501.02352). Retained as background attribution from the original README; its claims were not independently reproduced or used as new platform results.

## New engineering additions

The dashboard, API, persistent job/model registry, input checksums, incident lifecycle, drift monitor, confidence abstention, data contracts, deployment files and automated tests are new additions. They turn the original experiments into a reusable research workflow. PSI alert bands and abstention thresholds are explicitly heuristic; source references are not endorsements or field validation.
