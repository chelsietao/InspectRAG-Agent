"""Local integration checks against a built checkpoint, skipped when unavailable."""
import csv
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
CHECKPOINT = ROOT / 'artifacts/vision_baseline_v1/patchcore_bottle.pt'


@unittest.skipUnless(CHECKPOINT.is_file(), 'Build the local vision checkpoint first')
class CheckpointIntegrationTests(unittest.TestCase):
    def test_reloaded_checkpoint_reproduces_scores_and_splits(self):
        from run_vision_baseline import load_checkpoint, predict
        from vision_utils import sha256_file
        model, checkpoint = load_checkpoint(CHECKPOINT)
        manifest = ROOT / 'data/manifests/bottle_manifest.jsonl'
        self.assertEqual(checkpoint['training_manifest_sha256'], sha256_file(manifest))
        split = checkpoint['split']
        self.assertFalse(set(split['training']) & set(split['calibration']))
        self.assertTrue(all(p.startswith('train/good/') for p in split['training'] + split['calibration']))
        self.assertEqual((len(split['training']),len(split['calibration']),len(split['test'])), (179,30,83))
        reports = ROOT / 'docs/evaluation/vision_baseline_v1'
        with (reports / 'predictions.csv').open() as source:
            rows = {r['path']:r for r in csv.DictReader(source)}
        for relative in ['test/good/000.png','test/broken_large/000.png']:
            score, amap, _ = predict(model, ROOT / 'bottle' / relative, checkpoint['config']['input_size'])
            self.assertAlmostEqual(score, float(rows[relative]['score']), places=5)
            self.assertEqual(amap.shape, (128,128))
        metrics = json.loads((reports/'metrics.json').read_text())
        self.assertEqual(sum(metrics['test_confusion'].values()),83)
        self.assertEqual(metrics['checkpoint_sha256'],sha256_file(CHECKPOINT))


if __name__ == '__main__':
    unittest.main()
