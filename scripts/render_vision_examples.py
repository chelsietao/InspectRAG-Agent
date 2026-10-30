"""Render score maps on a calibration-only fixed scale without changing predictions."""
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def main():
    root = Path("bottle")
    artifacts = Path("artifacts/vision_baseline_v1")
    report = Path("docs/evaluation/vision_baseline_v1")
    calibration = json.loads((report / "calibration.json").read_text())
    # Display-only choice, with no effect on model scores or decision thresholds.
    upper = calibration["heatmap_upper"] * 2
    with (report / "predictions.csv").open() as source:
        rows = list(csv.DictReader(source))
    selected = []
    for category in ["good", "broken_large", "broken_small", "contamination"]:
        selected.append(next(row for row in rows if row["defect_type"] == category))
    figure, axes = plt.subplots(len(selected), 3, figsize=(10, 12))
    for index, row in enumerate(selected):
        path = root / row["path"]
        with Image.open(path) as image:
            axes[index, 0].imshow(image)
        axes[index, 0].set_title(row["defect_type"] + "/" + path.name)
        if row["defect_type"] == "good":
            mask = np.zeros((900, 900), dtype=np.uint8)
        else:
            with Image.open(root / "ground_truth" / path.parent.name / f"{path.stem}_mask.png") as image:
                mask = np.asarray(image)
        axes[index, 1].imshow(mask, cmap="gray", vmin=0, vmax=255)
        axes[index, 1].set_title("Ground truth (evaluation only)")
        amap = np.load(artifacts / "heatmaps" / f"{path.parent.name}_{path.stem}.npz")["anomaly_map"]
        plotted = axes[index, 2].imshow(amap, cmap="inferno", vmin=0, vmax=upper,
                                        extent=(0, 900, 900, 0))
        axes[index, 2].set_title(f"Raw score map / image score {float(row['score']):.2f}")
        for axis in axes[index]:
            axis.axis("off")
    figure.subplots_adjust(left=0.02, right=0.91, top=0.92, bottom=0.02, hspace=0.18, wspace=0.05)
    color_axis = figure.add_axes([0.93, 0.15, 0.015, 0.65])
    figure.colorbar(plotted, cax=color_axis, label="Local anomaly score (shared scale)")
    figure.suptitle("PatchCore bottle baseline: original / ground truth / score map\n"
                   "First file per category, illustrative only. Masks are never model inputs.", fontsize=12)
    figure.savefig(artifacts / "heatmap_examples.png", dpi=140, bbox_inches="tight", pad_inches=0.15)
    plt.close(figure)
    print("Updated examples using a fixed calibration-derived display scale")


if __name__ == "__main__":
    main()
