"""Exercise the real local analysis API, without calling Groq."""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from app.backend import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    directory = (args.output or ROOT / 'artifacts/backend_demo' / uuid.uuid4().hex).resolve()
    if directory.exists():
        parser.error('請指定尚未存在的輸出資料夾，保留先前紀錄')
    with TestClient(create_app(directory)) as client:
        case_response = client.post('/cases', json={'title': '瓶子外觀檢查 API 展示'})
        case = case_response.json()
        with (ROOT / 'bottle/test/broken_large/000.png').open('rb') as stream:
            uploaded = client.post(f"/cases/{case['id']}/images",
                                   files={'file': ('000.png', stream, 'image/png')}).json()
        payload = {'kind': 'analysis', 'image_id': uploaded['id'], 'request_key': 'demo-analysis-1'}
        first = client.post(f"/cases/{case['id']}/runs", json=payload).json()
        repeated = client.post(f"/cases/{case['id']}/runs", json=payload).json()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            run = client.get(f"/cases/{case['id']}/runs/{first['id']}").json()
            if run['status'] in ('succeeded', 'failed'):
                break
            time.sleep(.2)
        else:
            raise RuntimeError('analysis_deadline_exceeded')
        if run['status'] != 'succeeded':
            raise RuntimeError('real_analysis_failed')
        heatmap = client.get(f"/cases/{case['id']}/runs/{run['id']}/heatmap")
        if heatmap.status_code != 200:
            raise RuntimeError('heatmap_endpoint_failed')
        (directory / 'demo_heatmap.png').write_bytes(heatmap.content)
        summary = {'case_id': case['id'], 'run_id': run['id'], 'status': run['status'],
                   'source_image': 'bottle/test/broken_large/000.png',
                   'image_upload_http_status': 201, 'submission_http_status': 202,
                   'same_request_returns_same_run': first['id'] == repeated['id'],
                   'heatmap_http_status': heatmap.status_code, 'result': run['result'],
                   'external_llm_calls': 0, 'transport': 'in_process_asgi_testclient'}
    with TestClient(create_app(directory)) as restarted:
        saved = restarted.get(f"/cases/{case['id']}/runs/{run['id']}").json()
        summary['restart_preserves_result'] = saved['result'] == run['result']
    (directory / 'demo_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
