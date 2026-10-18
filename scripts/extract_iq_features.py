"""Build a labeled jamming feature dataset from an explicit recording manifest.

Manifest CSV: path,label,group,sample_rate. Paths resolve relative to manifest.
Each recording is a CSV with I,Q columns. One capture becomes one row.
"""
import argparse
from pathlib import Path
import pandas as pd
from gnss_sentinel.signals import features


def extract(manifest_path, output):
    manifest_path = Path(manifest_path).resolve()
    manifest = pd.read_csv(manifest_path)
    required = {"path", "label", "group", "sample_rate"}
    if not required.issubset(manifest.columns) or manifest[list(required)].isna().any().any():
        raise ValueError("Manifest requires nonempty path,label,group,sample_rate columns.")
    rows=[]
    for item in manifest.itertuples():
        recording = (manifest_path.parent / item.path).resolve()
        frame = pd.read_csv(recording)
        if not {"I","Q"}.issubset(frame.columns):
            raise ValueError(f"Missing I,Q columns: {recording}")
        iq = frame.I.to_numpy(dtype=float) + 1j*frame.Q.to_numpy(dtype=float)
        rows.append(features(iq, float(item.sample_rate)) | {"label": item.label, "group": item.group})
    pd.DataFrame(rows).to_csv(output, index=False)
    return len(rows)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    print(f"Extracted {extract(args.manifest,args.output)} recordings.")
