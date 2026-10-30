"""Run the existing checkpoint checks outside the FAISS test process."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
CHECKPOINT=ROOT/'artifacts/vision_baseline_v1/patchcore_bottle.pt'


@unittest.skipUnless(CHECKPOINT.is_file(),'Build the local vision checkpoint first')
class CheckpointIntegrationTests(unittest.TestCase):
    def test_reloaded_checkpoint_reproduces_scores_and_splits(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/check_vision_checkpoint.py')],
                              cwd=ROOT,text=True,capture_output=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Checkpoint reload, scores and split integrity passed',result.stdout)


if __name__=='__main__':
    unittest.main()
