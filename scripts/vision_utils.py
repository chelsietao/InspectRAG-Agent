"""Deterministic splits and fixed-scale visualisation for the vision baseline."""
from __future__ import annotations
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image


def normal_split(paths: list[Path], count: int = 30, seed: int = 42):
    paths = sorted(paths)
    if count < 1 or count >= len(paths):
        raise ValueError("校準資料數需介於 1 與正常圖片數減 1 之間")
    order = np.random.default_rng(seed).permutation(len(paths))
    calibration = sorted(paths[i] for i in order[:count])
    training = sorted(paths[i] for i in order[count:])
    return training, calibration


def overlay_heatmap(image: Image.Image, anomaly_map: np.ndarray, upper: float):
    if upper <= 0 or not np.isfinite(upper):
        raise ValueError("熱圖顯示上限必須是有限正數")
    array = np.asarray(anomaly_map, dtype=np.float32)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError("異常圖必須是有限數值的二維陣列")
    # Resize the numerical map before applying a shared display scale.
    values = np.asarray(Image.fromarray(array).resize(image.size, Image.Resampling.BILINEAR))
    strength = np.clip(values / upper, 0, 1)[..., None]
    original = np.asarray(image.convert("RGB"), dtype=np.float32)
    red = np.zeros_like(original)
    red[..., 0] = 255
    result = original * (1 - 0.55 * strength) + red * (0.55 * strength)
    return Image.fromarray(result.clip(0, 255).astype(np.uint8))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
