import argparse
import json
from pathlib import Path

import pandas as pd

from .config import Settings
from .datasets import register, spoofing_fixture, iq_fixture, catalog
from .store import Store
from .training import train_dataset


def main():
    parser = argparse.ArgumentParser(description="GNSS Sentinel research platform")
    parser.add_argument("--data-dir", type=Path, help="Runtime registry and artifact directory")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve dashboard and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    demo = commands.add_parser("demo", help="Create synthetic datasets and train actual models")
    demo.add_argument("--seed", type=int, default=42)
    imp = commands.add_parser("import", help="Register a labeled CSV without browser upload size limits")
    imp.add_argument("path", type=Path)
    imp.add_argument("--task", choices=["spoofing", "jamming"], default="spoofing")
    imp.add_argument("--name", required=True)
    imp.add_argument("--source", default="Local CSV import")
    train = commands.add_parser("train", help="Train and evaluate tabular classifiers")
    train.add_argument("dataset_id")
    train.add_argument("--seed", type=int, default=42)
    commands.add_parser("catalog", help="List source datasets and integration notes")
    vision = commands.add_parser("train-images", help="Train optional ResNet18 on train/val/test class folders")
    vision.add_argument("root", type=Path)
    vision.add_argument("--output", type=Path, required=True)
    vision.add_argument("--epochs", type=int, default=10)
    vision.add_argument("--batch-size", type=int, default=32)
    vision.add_argument("--seed", type=int, default=42)
    vision.add_argument("--pretrained", action="store_true")
    image = commands.add_parser("predict-image", help="Classify an image using a trusted local checkpoint")
    image.add_argument("checkpoint", type=Path)
    image.add_argument("image", type=Path)
    args = parser.parse_args()
    settings = Settings()
    if args.data_dir:
        settings.data_dir = args.data_dir.resolve()
    settings.prepare()
    store = Store(settings.data_dir / "sentinel.db")
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        if args.host not in {"127.0.0.1", "localhost", "::1"} and not settings.api_key:
            parser.error("Set SENTINEL_API_KEY before binding to a network interface.")
        uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)
    elif args.command == "catalog":
        print(json.dumps(catalog(), indent=2))
    elif args.command == "import":
        row = register(settings, store, pd.read_csv(args.path), args.name, args.task, "uploaded", args.source)
        print(json.dumps({"dataset_id": row["id"], "rows": row["rows"], "sha256": row["sha256"]}, indent=2))
    elif args.command == "train":
        model = train_dataset(settings, store, args.dataset_id, args.seed)
        print(json.dumps({"model_id": model["id"], "metrics": model["metrics"]}, indent=2))
    elif args.command == "demo":
        for task, factory in [("spoofing", spoofing_fixture), ("jamming", iq_fixture)]:
            existing = next((d for d in store.list("datasets", 10000) if d["task"] == task and d["source"] == "Sentinel deterministic fixture v1"), None)
            dataset = existing or register(settings, store, factory(args.seed), "Synthetic "+task+" examples", task, "synthetic", "Sentinel deterministic fixture v1")
            model = train_dataset(settings, store, dataset["id"], args.seed)
            print(json.dumps({"task": task, "dataset_id": dataset["id"], "model_id": model["id"], "synthetic_test_macro_f1": model["metrics"]["macro_f1"]}), flush=True)
        print("Synthetic demonstration complete. These scores are not field benchmarks.")
    elif args.command == "train-images":
        from .vision import train_images
        report = train_images(args.root, args.output, args.epochs, args.batch_size, args.seed, args.pretrained)
        print(json.dumps(report, indent=2))
    elif args.command == "predict-image":
        from .vision import predict_image
        print(json.dumps(predict_image(args.checkpoint, args.image), indent=2))


if __name__ == "__main__":
    main()
