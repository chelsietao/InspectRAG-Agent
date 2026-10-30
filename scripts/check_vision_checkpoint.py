"""Validate the saved vision checkpoint in a Torch-only subprocess."""
import csv
import json
from pathlib import Path

from run_vision_baseline import load_checkpoint,predict
from vision_utils import sha256_file

ROOT=Path(__file__).resolve().parents[1]


def main():
    path=ROOT/'artifacts/vision_baseline_v1/patchcore_bottle.pt'
    model,checkpoint=load_checkpoint(path)
    assert checkpoint['training_manifest_sha256']==sha256_file(ROOT/'data/manifests/bottle_manifest.jsonl')
    split=checkpoint['split']
    assert not set(split['training'])&set(split['calibration'])
    assert all(p.startswith('train/good/') for p in split['training']+split['calibration'])
    assert (len(split['training']),len(split['calibration']),len(split['test']))==(179,30,83)
    reports=ROOT/'docs/evaluation/vision_baseline_v1'
    with (reports/'predictions.csv').open() as source:
        rows={r['path']:r for r in csv.DictReader(source)}
    for relative in ['test/good/000.png','test/broken_large/000.png']:
        score,amap,_=predict(model,ROOT/'bottle'/relative,checkpoint['config']['input_size'])
        assert abs(score-float(rows[relative]['score']))<1e-5
        assert amap.shape==(128,128)
    metrics=json.loads((reports/'metrics.json').read_text())
    assert sum(metrics['test_confusion'].values())==83
    assert metrics['checkpoint_sha256']==sha256_file(path)
    print('Checkpoint reload, scores and split integrity passed')


if __name__=='__main__':
    main()
