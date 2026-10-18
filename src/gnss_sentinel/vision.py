"""Optional ResNet18 training and inference with explicit, immutable image splits."""
import hashlib
import json
import random
from pathlib import Path

import numpy as np


def train_images(root, output, epochs=10, batch_size=32, seed=42, pretrained=False):
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from torchvision import transforms
    from torchvision.datasets import ImageFolder
    from torchvision.models import ResNet18_Weights, resnet18
    from sklearn.metrics import classification_report, confusion_matrix, f1_score, accuracy_score

    root, output = Path(root), Path(output)
    if epochs < 1 or not 1 <= batch_size <= 256:
        raise ValueError("epochs must be positive; batch size must be 1–256.")
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    transform = transforms.Compose([transforms.Resize((128, 128)), transforms.ToTensor(),
        transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    data = {split: ImageFolder(root / split, transform=transform) for split in ("train", "val", "test")}
    classes = data["train"].classes
    if len(classes) < 2 or any(ds.class_to_idx != data["train"].class_to_idx for ds in data.values()):
        raise ValueError("Train, val and test must have the same two or more class folders.")
    # Reject exact duplicates across partitions before training.
    seen, manifest = {}, []
    for split, ds in data.items():
        for filename, label in ds.samples:
            sha = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
            if sha in seen and seen[sha] != split:
                raise ValueError(f"Duplicate image crosses {seen[sha]}/{split} partitions: {filename}")
            seen[sha] = split
            manifest.append({"path": str(Path(filename).relative_to(root)), "split": split, "label": classes[label], "sha256": sha})
    output.mkdir(parents=True, exist_ok=False)
    generator = torch.Generator().manual_seed(seed)
    loaders = {s: DataLoader(ds, batch_size=batch_size, shuffle=s=="train", num_workers=0, generator=generator) for s, ds in data.items()}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = resnet18(weights=ResNet18_Weights.DEFAULT if pretrained else None)
    model.fc = nn.Linear(model.fc.in_features, len(classes))
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    history, best = [], -1

    @torch.inference_mode()
    def evaluate(loader):
        model.eval()
        actual, predicted = [], []
        for images, labels in loader:
            logits = model(images.to(device))
            actual.extend(labels.tolist()); predicted.extend(logits.argmax(1).cpu().tolist())
        return actual, predicted

    for epoch in range(epochs):
        model.train()
        total_loss, count = 0, 0
        for images, labels in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(images.to(device)), labels.to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item()*len(labels); count += len(labels)
        actual, predicted = evaluate(loaders["val"])
        score = float(f1_score(actual, predicted, average="macro", zero_division=0))
        history.append({"epoch": epoch+1, "train_loss": total_loss/count, "validation_macro_f1": score})
        print(json.dumps(history[-1]), flush=True)
        if score > best:
            best = score
            torch.save({"state_dict": model.state_dict(), "classes": classes}, output / "best.pt")
    checkpoint = torch.load(output / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    actual, predicted = evaluate(loaders["test"])
    report = {"architecture": "resnet18", "pretrained": pretrained, "seed": seed,
        "classes": classes, "split_sizes": {s: len(d) for s,d in data.items()}, "history": history,
        "test_accuracy": float(accuracy_score(actual, predicted)),
        "test_macro_f1": float(f1_score(actual, predicted, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(actual, predicted, labels=list(range(len(classes)))).tolist(),
        "classification_report": classification_report(actual, predicted, labels=list(range(len(classes))), target_names=classes, output_dict=True, zero_division=0),
        "normalization": "ImageNet mean/std", "resize": [128,128], "device": str(device),
        "limitations": "Content hashes detect exact duplicates only. Keep all related captures within one split."}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return report


def predict_image(checkpoint_path, image_path):
    import torch
    from torch import nn
    from torchvision import transforms
    from torchvision.models import resnet18
    from PIL import Image
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = resnet18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, len(checkpoint["classes"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    transform = transforms.Compose([transforms.Resize((128,128)), transforms.ToTensor(),
        transforms.Normalize([.485,.456,.406],[.229,.224,.225])])
    with Image.open(image_path) as image:
        x = transform(image.convert("RGB")).unsqueeze(0)
    with torch.inference_mode():
        probabilities = model(x).softmax(1)[0].tolist()
    return {"label": checkpoint["classes"][int(np.argmax(probabilities))],
            "probabilities": dict(zip(checkpoint["classes"], probabilities)), "score_type": "uncalibrated softmax"}
