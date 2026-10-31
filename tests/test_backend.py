"""Offline API integration tests, no Groq requests or model downloads."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import shutil
import threading
import time
import unittest
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from app.backend import ROOT, MAX_UPLOAD, create_app
from app.case_store import Store


def fake_execution(root, directory, run, image):
    if run['question'] == 'rate-limit':
        return {'status': 'rate_limited', 'error': 'rate_limited', 'api_calls': 1}
    if run['question'] == 'fail':
        raise RuntimeError('gsk_fake_sensitive_value')
    if run['kind'] == 'analysis':
        return {'status': 'ok', 'score': 12.0, 'threshold': 10.0}
    return {'status': 'answered', 'answer': {'status': 'answered', 'claims': [
        {'text': '這是測試回答，來源為測試資料。', 'evidence_ids': ['doc:test']}],
        'limitations': ['離線測試，未呼叫模型。']},
        'citations': [{'id': 'doc:test', 'text': 'fixture'}]}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / 'artifacts/backend_tests' / uuid.uuid4().hex
        self.app = create_app(self.directory, fake_execution)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.case = self.client.post('/cases', json={'title': '瓶底檢查'}).json()['id']
        self.other = self.client.post('/cases', json={'title': '另一個案件'}).json()['id']

    def tearDown(self):
        self.client.__exit__(None, None, None)
        shutil.rmtree(self.directory, ignore_errors=True)

    def image(self, case=None, filename='bottle.png'):
        data = io.BytesIO()
        Image.new('RGB', (16, 16), 'white').save(data, 'PNG')
        return self.client.post(f'/cases/{case or self.case}/images',
                                files={'file': (filename, data.getvalue(), 'image/png')})

    def submit(self, **overrides):
        body = {'kind': 'agent', 'question': '請說明分數', 'request_key': uuid.uuid4().hex}
        body.update(overrides)
        return self.client.post(f'/cases/{self.case}/runs', json=body)

    def wait(self, run_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = self.client.get(f'/cases/{self.case}/runs/{run_id}').json()
            if run['status'] in ('succeeded', 'failed'):
                return run
            time.sleep(.01)
        self.fail('job_did_not_finish')

    def test_health_does_not_call_llm(self):
        self.assertEqual(self.client.get('/health').json()['llm_online_checked'], False)

    def test_case_validation_and_unknown_fields(self):
        for payload in ({'title': '   '}, {'title': 'a', 'path': '.env.local'}, {'title': 1}):
            self.assertEqual(self.client.post('/cases', json=payload).status_code, 422)

    def test_upload_normalizes_filename_and_reads_back(self):
        result = self.image(filename='../../.env.local').json()
        self.assertEqual(result['width'], 16)
        path = self.directory / 'images' / (result['id'] + '.png')
        self.assertTrue(path.is_file())
        self.assertNotIn('filename', result)
        response = self.client.get(f"/cases/{self.case}/images/{result['id']}")
        self.assertEqual(response.content, path.read_bytes())

    def test_invalid_image_and_format(self):
        response = self.client.post(f'/cases/{self.case}/images',
                                    files={'file': ('a.png', b'not image', 'image/png')})
        self.assertEqual(response.status_code, 415)
        raw = io.BytesIO()
        Image.new('RGB', (8, 8)).save(raw, 'GIF')
        response = self.client.post(f'/cases/{self.case}/images',
                                    files={'file': ('a.gif', raw.getvalue(), 'image/gif')})
        self.assertEqual(response.status_code, 415)

    def test_upload_size_limit(self):
        response = self.client.post(f'/cases/{self.case}/images',
                                    files={'file': ('a.png', b'x' * (MAX_UPLOAD + 1), 'image/png')})
        self.assertEqual(response.status_code, 413)

    def test_missing_case_does_not_save_image(self):
        self.assertEqual(self.image(case='unknown').status_code, 404)
        self.assertEqual(list((self.directory / 'images').iterdir()), [])

    def test_cross_case_image_is_rejected(self):
        image_id = self.image(case=self.other).json()['id']
        self.assertEqual(self.submit(kind='analysis', image_id=image_id).status_code, 404)
        self.assertEqual(self.client.get(f'/cases/{self.case}/images/{image_id}').status_code, 404)

    def test_analysis_requires_image_and_agent_requires_question(self):
        self.assertEqual(self.submit(kind='analysis').status_code, 422)
        self.assertEqual(self.submit(question='  ').status_code, 422)
        self.assertEqual(self.submit(kind='shell').status_code, 422)
        self.assertEqual(self.submit(path='.env.local').status_code, 422)

    def test_analysis_job_and_history(self):
        image_id = self.image().json()['id']
        response = self.submit(kind='analysis', image_id=image_id)
        self.assertEqual(response.status_code, 202)
        run = self.wait(response.json()['id'])
        self.assertEqual(run['status'], 'succeeded')
        self.assertEqual(run['result']['score'], 12)
        history = self.client.get(f'/cases/{self.case}/runs').json()
        self.assertEqual(len(history['items']), 1)
        self.assertIn('not_injected', history['memory_policy'])

    def test_idempotency_and_conflict(self):
        first = self.submit(request_key='same').json()
        second = self.submit(request_key='same').json()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.submit(request_key='same', question='changed').status_code, 409)
        self.assertEqual(len(self.app.state.store.list('runs', self.case)), 1)

    def test_concurrent_duplicate_creates_one_row(self):
        store = self.app.state.store
        def request(_):
            return store.submit(self.case, None, 'agent', 'q', 'concurrent', 'fingerprint')[0]['id']
        with ThreadPoolExecutor(max_workers=8) as pool:
            identifiers = list(pool.map(request, range(16)))
        self.assertEqual(len(set(identifiers)), 1)

    def test_failed_execution_redacts_exception(self):
        run = self.wait(self.submit(question='fail').json()['id'])
        self.assertEqual(run['error'], 'execution_failed')
        self.assertNotIn('gsk_', json.dumps(run))

    def test_provider_rate_limit_saved_without_resubmission(self):
        first = self.submit(question='rate-limit', request_key='limited').json()
        run = self.wait(first['id'])
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['error'], 'rate_limited')
        repeated = self.submit(question='rate-limit', request_key='limited').json()
        self.assertEqual(repeated['id'], first['id'])
        self.assertEqual(repeated['result']['api_calls'], 1)

    def test_cross_case_run_report_and_heatmap(self):
        run = self.wait(self.submit().json()['id'])
        for suffix in ('', '/heatmap'):
            self.assertEqual(self.client.get(f"/cases/{self.other}/runs/{run['id']}{suffix}").status_code, 404)
        response = self.client.post(f'/cases/{self.other}/reports', json={'run_id': run['id']})
        self.assertEqual(response.status_code, 404)

    def test_report_snapshot_versions_and_explicit_confirmation(self):
        run = self.wait(self.submit().json()['id'])
        response = self.client.post(f'/cases/{self.case}/reports', json={'run_id': run['id']})
        self.assertEqual(response.status_code, 201)
        report = response.json()
        self.assertIsNone(report['confirmed_at'])
        second = self.client.post(f'/cases/{self.case}/reports', json={'run_id': run['id']}).json()
        self.assertEqual(second['version'], report['version'] + 1)
        url = f"/cases/{self.case}/reports/{report['id']}/confirm"
        self.assertEqual(self.client.post(url, json={'accepted': False}).status_code, 422)
        confirmed = self.client.post(url, json={'accepted': True}).json()
        self.assertEqual(confirmed, self.client.post(url, json={'accepted': True}).json())
        self.assertEqual(confirmed['snapshot'], run['result'])
        self.assertEqual(self.client.post(f"/cases/{self.other}/reports/{report['id']}/confirm",
                                          json={'accepted': True}).status_code, 404)

    def test_unanswered_run_cannot_be_report(self):
        run = self.wait(self.submit(question='fail').json()['id'])
        self.assertEqual(self.client.post(f'/cases/{self.case}/reports',
                                          json={'run_id': run['id']}).status_code, 409)

    def test_restart_preserves_data_and_marks_interrupted_without_retry(self):
        directory = self.directory / 'restart'
        store = Store(directory / 'inspectrag.sqlite3')
        case = store.create_case('瓶底檢查')['id']
        pending, _ = store.submit(case, None, 'agent', 'q', 'interrupted', 'f')
        with TestClient(create_app(directory, fake_execution)) as restarted:
            self.assertEqual(restarted.get(f'/cases/{case}').json()['title'], '瓶底檢查')
            row = restarted.get(f"/cases/{case}/runs/{pending['id']}").json()
            self.assertEqual(row['error'], 'server_restarted')
            self.assertEqual(row['status'], 'failed')

    def test_second_server_cannot_recover_active_jobs(self):
        with self.assertRaisesRegex(RuntimeError, 'database_already_in_use'):
            with TestClient(create_app(self.directory, fake_execution)):
                pass

    def test_origin_and_host_rejection(self):
        self.assertEqual(self.client.post('/cases', json={'title': 'x'},
                                          headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/health', headers={'Host': 'evil.example'}).status_code, 403)

    def test_queue_capacity_and_full_queue_idempotency_conflict(self):
        blocked = threading.Event()
        directory = self.directory / 'queue'
        def slow(*args):
            blocked.wait(5)
            return {'status': 'ok'}
        with TestClient(create_app(directory, slow)) as client:
            case = client.post('/cases', json={'title': 'queue'}).json()['id']
            url = f'/cases/{case}/runs'
            body = {'kind': 'agent', 'question': 'q', 'request_key': '0'}
            try:
                first = client.post(url, json=body).json()
                for number in range(1, 4):
                    self.assertEqual(client.post(url, json={**body, 'request_key': str(number)}).status_code, 202)
                self.assertEqual(client.post(url, json={**body, 'request_key': '5'}).status_code, 429)
                self.assertEqual(client.post(url, json=body).json()['id'], first['id'])
                self.assertEqual(client.post(url, json={**body, 'question': 'changed'}).status_code, 409)
            finally:
                blocked.set()


if __name__ == '__main__':
    unittest.main()
