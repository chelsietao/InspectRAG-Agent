"""Use controlled synthetic files to exercise data-integrity failure paths."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "validate_data", Path(__file__).resolve().parents[1] / "scripts" / "validate_data.py"
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for index, group in enumerate(sorted(validator.GROUPS)):
            folder = self.root / group
            folder.mkdir(parents=True)
            is_mask = group.startswith("ground_truth/")
            name = "000_mask.png" if is_mask else "000.png"
            image = Image.new("L" if is_mask else "RGB", (8, 8),
                              0 if is_mask else (20 * index, 10, 50))
            if is_mask:
                image.putpixel((1, 1), 255)
            image.save(folder / name)
        for name in ("license.txt", "readme.txt"):
            (self.root / name).write_text("fixture", encoding="utf-8")

    def test_valid_data(self):
        report, records = validator.validate_dataset(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["inspection_images"], 5)
        self.assertEqual(report["masks"], 3)
        self.assertTrue(all(not Path(r["path"]).is_absolute() for r in records))

    def test_missing_mask(self):
        (self.root / "ground_truth/broken_large/000_mask.png").unlink()
        report, _ = validator.validate_dataset(self.root)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("缺少可讀取遮罩" in e for e in report["errors"]))

    def test_mismatched_mask_size(self):
        Image.new("L", (4, 4), 255).save(self.root / "ground_truth/broken_large/000_mask.png")
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(any("尺寸不符" in e for e in report["errors"]))

    def test_nonbinary_mask(self):
        Image.new("L", (8, 8), 127).save(self.root / "ground_truth/broken_large/000_mask.png")
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(any("非二元值" in e for e in report["errors"]))

    def test_empty_mask(self):
        Image.new("L", (8, 8), 0).save(self.root / "ground_truth/broken_large/000_mask.png")
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(any("沒有任何白色像素" in e for e in report["errors"]))

    def test_corrupt_png(self):
        (self.root / "test/good/000.png").write_bytes(b"broken")
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(any("圖片驗證失敗" in e for e in report["errors"]))

    def test_cross_split_duplicate(self):
        (self.root / "test/good/000.png").write_bytes(
            (self.root / "train/good/000.png").read_bytes())
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(report["cross_split_duplicate_groups"])
        self.assertEqual(report["status"], "failed")

    def test_orphan_mask(self):
        (self.root / "test/broken_large/000.png").rename(
            self.root / "test/broken_large/001.png")
        report, _ = validator.validate_dataset(self.root)
        self.assertTrue(any("沒有對應測試圖片" in e for e in report["errors"]))

    def test_deterministic_manifest(self):
        first, _ = validator.validate_dataset(self.root)
        second, _ = validator.validate_dataset(self.root)
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])

    def test_reports_written(self):
        report, records = validator.validate_dataset(self.root)
        output = self.root / "results"
        validator.write_outputs(output, report, records)
        self.assertEqual(len((output / "bottle_manifest.jsonl").read_text().splitlines()), 8)
        self.assertIn("passed", (output / "bottle_validation.md").read_text())


if __name__ == "__main__":
    unittest.main()
