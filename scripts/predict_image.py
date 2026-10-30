"""Run one image through the saved baseline without training or recalibration."""
import argparse
import json
from pathlib import Path
from PIL import Image

from run_vision_baseline import load_checkpoint, predict
from vision_utils import overlay_heatmap, sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=Path("artifacts/vision_baseline_v1/patchcore_bottle.pt"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/prediction"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("輸出資料夾已存在，請指定新位置以保留先前結果")
    model, checkpoint = load_checkpoint(args.checkpoint)
    score, anomaly_map, seconds = predict(model, args.image, checkpoint["config"]["input_size"])
    args.output.mkdir(parents=True)
    with Image.open(args.image) as image:
        overlay_heatmap(image, anomaly_map, checkpoint["heatmap_upper"]).save(args.output / "heatmap.png")
    result = {"image": args.image.name, "input_sha256": sha256_file(args.image),
              "checkpoint_sha256": sha256_file(args.checkpoint), "score": score,
              "threshold": checkpoint["image_threshold"],
              "is_anomalous": score > checkpoint["image_threshold"],
              "seconds": seconds, "supported_category": "bottle",
              "note": "僅適用於 MVTec bottle 類似影像，未執行產品類別或真實產線適用性驗證，異常分數不是瑕疵機率。"}
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
