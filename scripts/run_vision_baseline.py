"""Build, calibrate and evaluate a CPU-friendly PatchCore baseline."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from sklearn.metrics import roc_auc_score, confusion_matrix
import torch
from torchvision import transforms

from vision_utils import normal_split, overlay_heatmap, sha256_file

CONFIG = {
    "backbone": "resnet18", "layers": ["layer2", "layer3"],
    "input_size": 128, "coreset_sampling_ratio": 0.01, "num_neighbors": 1,
    "calibration_count": 30, "seed": 42, "device": "cpu", "threads": 4,
    "image_threshold_rule": "max of held-out normal calibration image scores",
    "pixel_threshold": None,
    "heatmap_scale_rule": "maximum calibration anomaly-map value",
}


def transform(size: int):
    return transforms.Compose([
        transforms.Resize((size, size), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


def image_tensor(path: Path, size: int):
    with Image.open(path) as image:
        return transform(size)(image.convert("RGB")).unsqueeze(0)


def create_model(config: dict, pretrained: bool):
    from anomalib.models.image.patchcore.torch_model import PatchcoreModel
    return PatchcoreModel(layers=config["layers"], backbone=config["backbone"],
                          pre_trained=pretrained, num_neighbors=config["num_neighbors"])


def predict(model, path: Path, size: int):
    started = time.perf_counter()
    tensor = image_tensor(path, size)
    with torch.inference_mode():
        output = model(tensor)
    score = float(output.pred_score.reshape(-1)[0])
    anomaly_map = output.anomaly_map[0, 0].cpu().numpy().copy()
    if not np.isfinite(score) or not np.isfinite(anomaly_map).all():
        raise ValueError("模型回傳非有限分數或熱圖")
    return score, anomaly_map, time.perf_counter() - started


def load_checkpoint(path: Path):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    torch.set_num_threads(config["threads"])
    model = create_model(config, pretrained=False)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()
    return model, checkpoint


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(root: Path, output: Path, report_dir: Path):
    if output.exists() or report_dir.exists():
        raise ValueError("輸出資料夾已存在，請選新位置以保留先前實驗")
    manifest = root.parent / "data/manifests/bottle_manifest.jsonl"
    if not manifest.is_file():
        raise ValueError("請先執行資料驗證，缺少逐檔 manifest")
    manifest_records = [json.loads(line) for line in manifest.read_text().splitlines() if line]
    # Integrity is verified before using any images, including test labels.
    for row in manifest_records:
        if sha256_file(root / row["path"]) != row["sha256"]:
            raise ValueError(f"圖片已變動，請重新驗證：{row['path']}")
    expected_pngs = {row["path"] for row in manifest_records}
    actual_pngs = {p.relative_to(root).as_posix() for p in root.rglob("*.png")}
    if expected_pngs != actual_pngs:
        raise ValueError("檔案清單已變動，請重新驗證")
    train, calibration = normal_split(list((root / "train/good").glob("*.png")),
                                      CONFIG["calibration_count"], CONFIG["seed"])
    output.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (output / "heatmaps").mkdir()
    split_record = {"seed": CONFIG["seed"], "training": [p.relative_to(root).as_posix() for p in train],
                    "calibration": [p.relative_to(root).as_posix() for p in calibration],
                    "test": [p.relative_to(root).as_posix() for p in sorted((root / "test").rglob("*.png"))]}
    save_json(report_dir / "split.json", split_record)
    save_json(report_dir / "config.json", CONFIG)
    torch.manual_seed(CONFIG["seed"])
    np.random.seed(CONFIG["seed"])
    torch.set_num_threads(CONFIG["threads"])
    print("Loading public pretrained ResNet18 weights", flush=True)
    model = create_model(CONFIG, pretrained=True)
    model.train()
    model.feature_extractor.eval()
    started = time.perf_counter()
    with torch.inference_mode():
        for index, path in enumerate(train):
            model(image_tensor(path, CONFIG["input_size"]))
            if (index + 1) % 30 == 0:
                print(f"Normal feature extraction {index + 1}/{len(train)}", flush=True)
        print("Selecting normal coreset", flush=True)
        model.subsample_embedding(CONFIG["coreset_sampling_ratio"])
    model.eval()
    fit_seconds = time.perf_counter() - started
    print(f"Normal bank ready: {tuple(model.memory_bank.shape)}", flush=True)
    calibration_rows = []
    calibration_maps = []
    for path in calibration:
        score, amap, elapsed = predict(model, path, CONFIG["input_size"])
        calibration_rows.append({"path": path.relative_to(root).as_posix(),
                                 "score": score, "seconds": elapsed})
        calibration_maps.append(amap)
    threshold = max(r["score"] for r in calibration_rows)
    heatmap_upper = max(float(np.max(a)) for a in calibration_maps)
    # Freeze thresholds and checkpoint before reading any test masks or scores.
    checkpoint = {"config": CONFIG, "state_dict": model.state_dict(),
                  "image_threshold": threshold, "heatmap_upper": heatmap_upper,
                  "training_manifest_sha256": sha256_file(manifest),
                  "split": split_record}
    checkpoint_path = output / "patchcore_bottle.pt"
    torch.save(checkpoint, checkpoint_path)
    save_json(report_dir / "calibration.json", {
        "threshold": threshold, "heatmap_upper": heatmap_upper,
        "rule": CONFIG["image_threshold_rule"], "rows": calibration_rows,
        "note": "30 個正常校準樣本的最大值，不代表未來資料的假陽性率保證。",
    })
    print("Calibration fixed. Evaluating untouched test split", flush=True)
    rows, all_masks, all_maps, examples = [], [], [], []
    example_groups = set()
    for path in sorted((root / "test").rglob("*.png")):
        score, amap, elapsed = predict(model, path, CONFIG["input_size"])
        label = int(path.parent.name != "good")
        row = {"path": path.relative_to(root).as_posix(), "defect_type": path.parent.name,
               "label": label, "score": score, "threshold": threshold,
               "prediction": int(score > threshold), "seconds": elapsed}
        rows.append(row)
        if label:
            mask_path = root / "ground_truth" / path.parent.name / f"{path.stem}_mask.png"
            with Image.open(mask_path) as mask:
                mask_array = np.asarray(mask.convert("L").resize(
                    (CONFIG["input_size"], CONFIG["input_size"]), Image.Resampling.NEAREST)) > 0
        else:
            mask_array = np.zeros_like(amap, dtype=bool)
        all_masks.append(mask_array.ravel())
        all_maps.append(amap.ravel())
        np.savez_compressed(output / "heatmaps" / f"{path.parent.name}_{path.stem}.npz",
                            anomaly_map=amap)
        if path.parent.name not in example_groups:
            example_groups.add(path.parent.name)
            with Image.open(path) as image:
                original = image.convert("RGB").copy()
            overlay = overlay_heatmap(original, amap, heatmap_upper)
            overlay.save(output / "heatmaps" / f"{path.parent.name}_{path.stem}_overlay.png")
            examples.append((row, original, overlay))
        if len(rows) % 20 == 0:
            print(f"Test evaluation {len(rows)}/83", flush=True)
    with (report_dir / "predictions.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    labels = [row["label"] for row in rows]
    scores = [row["score"] for row in rows]
    preds = [row["prediction"] for row in rows]
    tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        commit = "unknown"
    metrics = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit_at_run": commit,
        "script_sha256": sha256_file(Path(__file__)),
        "utils_sha256": sha256_file(Path(__file__).with_name("vision_utils.py")),
        "data_manifest_sha256": sha256_file(manifest),
        "config": CONFIG, "train_images": len(train), "calibration_images": len(calibration),
        "test_images": len(rows), "memory_bank_shape": list(model.memory_bank.shape),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "image_auroc": float(roc_auc_score(labels, scores)),
        "pixel_auroc_128": float(roc_auc_score(np.concatenate(all_masks), np.concatenate(all_maps))),
        "pixel_evaluation_resolution": [128, 128], "image_threshold": threshold,
        "test_confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "normal_test_false_positive_rate": float(fp / (tn + fp)),
        "anomaly_test_recall": float(tp / (tp + fn)),
        "fit_seconds_excluding_weight_load": fit_seconds,
        "inference_p50_seconds": float(np.percentile([r["seconds"] for r in rows], 50)),
        "inference_p95_seconds": float(np.percentile([r["seconds"] for r in rows], 95)),
        "latency_scope": "warm CPU inference including image decode and preprocessing, excluding checkpoint load and saving",
        "platform": platform.platform(), "machine": platform.machine(),
        "versions": {name: importlib.metadata.version(name) for name in
                     ["anomalib", "torch", "torchvision", "timm", "numpy", "scikit-learn", "Pillow"]},
    }
    save_json(report_dir / "metrics.json", metrics)
    figure, axes = plt.subplots(len(examples), 2, figsize=(8, 4 * len(examples)))
    for index, (row, original, overlay) in enumerate(examples):
        axes[index, 0].imshow(original)
        axes[index, 0].set_title(row["defect_type"] + " / " + Path(row["path"]).name)
        axes[index, 1].imshow(overlay)
        axes[index, 1].set_title(f"score={row['score']:.3f}, threshold={threshold:.3f}")
        for axis in axes[index]:
            axis.axis("off")
    figure.suptitle("PatchCore bottle baseline | shared calibration heat scale | illustrative examples")
    figure.tight_layout()
    figure.savefig(output / "heatmap_examples.png", dpi=120)
    plt.close(figure)
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("bottle"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/vision_baseline_v1"))
    parser.add_argument("--report-dir", type=Path, default=Path("docs/evaluation/vision_baseline_v1"))
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve(), args.report_dir.resolve())
