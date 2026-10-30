"""Validate MVTec AD bottle without modifying source data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from PIL import Image

DEFECTS = {"broken_large", "broken_small", "contamination"}
GROUPS = {"train/good", "test/good"} | {
    f"{split}/{defect}" for split in ("test", "ground_truth") for defect in DEFECTS
}


def inspect_png(path: Path, relative: str) -> dict:
    """Check PNG integrity, decode pixels and record reproducible fingerprints."""
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError("副檔名為 PNG，但檔案格式不符")
        image.verify()
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        mode = image.mode
        pixels = image.tobytes()
        pixel_hash = hashlib.sha256(
            f"{mode}:{width}:{height}:".encode() + pixels
        ).hexdigest()
        record = {
            "path": relative,
            "group": str(Path(relative).parent),
            "width": width,
            "height": height,
            "mode": mode,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pixel_sha256": pixel_hash,
        }
        if relative.startswith("ground_truth/"):
            if mode not in ("1", "L"):
                raise ValueError(f"遮罩需要單通道，實際為 {mode}")
            gray = image.convert("L")
            histogram = gray.histogram()
            values = [value for value, count in enumerate(histogram) if count]
            if not set(values) <= {0, 255}:
                raise ValueError(f"遮罩含非二元值：{values[:10]}")
            if histogram[255] == 0:
                raise ValueError("瑕疵遮罩沒有任何白色像素")
            record["positive_pixels"] = histogram[255]
        return record


def validate_dataset(root: Path) -> tuple[dict, list[dict]]:
    errors: list[str] = []
    records: list[dict] = []
    if not root.is_dir():
        raise ValueError(f"找不到資料夾：{root}")
    for group in sorted(GROUPS):
        folder = root / group
        if not folder.is_dir() or not any(folder.glob("*.png")):
            errors.append(f"缺少必要圖片資料夾或內容為空：{group}")
    for name in ("license.txt", "readme.txt"):
        if not (root / name).is_file():
            errors.append(f"缺少來源文件：{name}")
    for path in sorted(root.rglob("*.png")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"不接受符號連結：{relative}")
            continue
        if path.parent.relative_to(root).as_posix() not in GROUPS:
            errors.append(f"未知資料分組：{relative}")
        try:
            records.append(inspect_png(path, relative))
        except Exception as exc:
            errors.append(f"圖片驗證失敗：{relative}：{exc}")
    by_path = {record["path"]: record for record in records}
    for record in records:
        parts = Path(record["path"]).parts
        if parts[0] == "test" and parts[1] in DEFECTS:
            expected = f"ground_truth/{parts[1]}/{Path(parts[2]).stem}_mask.png"
            mask = by_path.get(expected)
            if mask is None:
                errors.append(f"缺少可讀取遮罩：{record['path']} → {expected}")
            elif (mask["width"], mask["height"]) != (record["width"], record["height"]):
                errors.append(f"圖片與遮罩尺寸不符：{record['path']}")
            record["mask_path"] = expected
        elif parts[0] == "ground_truth":
            stem = Path(parts[2]).stem
            expected = f"test/{parts[1]}/{stem.removesuffix('_mask')}.png"
            if not stem.endswith("_mask") or expected not in by_path:
                errors.append(f"遮罩沒有對應測試圖片：{record['path']}")
    fingerprints: dict[str, list[str]] = defaultdict(list)
    for record in records:
        if not record["path"].startswith("ground_truth/"):
            fingerprints[record["pixel_sha256"]].append(record["path"])
    duplicates = [paths for paths in fingerprints.values() if len(paths) > 1]
    cross_split = [paths for paths in duplicates if
                   any(p.startswith("train/") for p in paths) and
                   any(p.startswith("test/") for p in paths)]
    if cross_split:
        errors.append(f"發現訓練與測試像素內容重複：{cross_split}")
    groups = dict(sorted(Counter(record["group"] for record in records).items()))
    manifest_hash = hashlib.sha256(json.dumps(
        records, sort_keys=True, ensure_ascii=False
    ).encode()).hexdigest()
    report = {
        "dataset": "MVTec AD bottle", "status": "passed" if not errors else "failed",
        "manifest_sha256": manifest_hash,
        "counts_by_group": groups,
        "inspection_images": sum(count for group, count in groups.items()
                                 if not group.startswith("ground_truth/")),
        "masks": sum(count for group, count in groups.items()
                     if group.startswith("ground_truth/")),
        "image_sizes": sorted({f"{r['width']}x{r['height']}" for r in records}),
        "modes": dict(Counter(r["mode"] for r in records)),
        "duplicate_image_groups": duplicates,
        "cross_split_duplicate_groups": cross_split,
        "errors": errors,
        "limitations": [
            "雜湊檢查只能找出相同像素，無法排除近似圖片或同一物件的不同拍攝。",
            "檔案可讀與標註對應不代表已驗證標註的語意正確性。",
            "本階段尚未建立模型、校準切分或執行模型評估。",
        ],
    }
    return report, records


def write_outputs(output: Path, report: dict, records: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "bottle_manifest.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records),
        encoding="utf-8",
    )
    (output / "bottle_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# 瓶子資料檢查報告", "", "本報告由資料驗證程式產生，僅描述目前檔案檢查結果。", "",
             f"- 驗證狀態（Validation Status），`{report['status']}`。",
             f"- 檢驗圖片（Inspection Images），{report['inspection_images']} 張。",
             f"- 瑕疵遮罩（Ground-truth Masks），{report['masks']} 張。",
             f"- 圖片尺寸（Image Size），{', '.join(report['image_sizes'])}。", "",
             "| 資料分組 | 檔案數 |", "|---|---:|"]
    lines += [f"| `{group}` | {count} |" for group, count in report["counts_by_group"].items()]
    lines += ["", "## 資料限制", ""] + [f"- {item}" for item in report["limitations"]]
    lines += ["", "## 發現的錯誤", ""]
    lines += [f"- {error}" for error in report["errors"]] or ["未發現檔案結構、解碼、遮罩或跨切分完全重複的錯誤，近似重複仍需要另作檢查。"]
    (output / "bottle_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("bottle"))
    parser.add_argument("--output", type=Path, default=Path("data/manifests"))
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if output == root or root in output.parents:
        parser.error("輸出位置必須在原始資料夾之外")
    try:
        report, records = validate_dataset(root)
    except ValueError as exc:
        parser.error(str(exc))
    write_outputs(output, report, records)
    print(json.dumps({key: report[key] for key in
                      ("status", "inspection_images", "masks", "counts_by_group", "errors")},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
