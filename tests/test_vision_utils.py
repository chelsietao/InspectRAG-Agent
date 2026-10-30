import sys
from pathlib import Path
import unittest
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from vision_utils import normal_split, overlay_heatmap


class VisionUtilityTests(unittest.TestCase):
    def test_split_disjoint_reproducible_and_training_only(self):
        paths = [Path(f'train/good/{i:03}.png') for i in range(209)]
        train, calibration = normal_split(paths)
        self.assertEqual((len(train), len(calibration)), (179, 30))
        self.assertFalse(set(train) & set(calibration))
        self.assertEqual(set(train) | set(calibration), set(paths))
        self.assertEqual((train, calibration), normal_split(list(reversed(paths))))

    def test_invalid_split_rejected(self):
        with self.assertRaises(ValueError):
            normal_split([Path('one.png')], count=1)

    def test_shared_heat_scale_and_original_dimensions(self):
        image = Image.new('RGB', (900, 900), (40, 80, 120))
        small = np.full((8, 8), 0.1, dtype=np.float32)
        large = np.full((8, 8), 0.9, dtype=np.float32)
        low = overlay_heatmap(image, small, upper=1.0)
        high = overlay_heatmap(image, large, upper=1.0)
        self.assertEqual(high.size, image.size)
        self.assertGreater(np.asarray(high)[0, 0, 0], np.asarray(low)[0, 0, 0])

    def test_invalid_map_rejected(self):
        with self.assertRaises(ValueError):
            overlay_heatmap(Image.new('RGB', (8, 8)), np.array([[np.nan]]), 1.0)

    def test_zero_map_preserves_image(self):
        image = Image.new('RGB', (16, 16), (40, 80, 120))
        result = overlay_heatmap(image, np.zeros((8, 8), dtype=np.float32), 1.0)
        np.testing.assert_array_equal(np.asarray(image), np.asarray(result))


if __name__ == '__main__':
    unittest.main()
