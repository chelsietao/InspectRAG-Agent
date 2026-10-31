"""Dashboard API boundary tests, without model or provider calls."""
import hashlib
from pathlib import Path
import shutil
import unittest
import uuid

from fastapi.testclient import TestClient
from app.backend import ROOT, create_app


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / 'artifacts/dashboard_tests' / uuid.uuid4().hex
        self.app = create_app(self.directory, lambda *args: {'status': 'ok'})
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.case = self.client.post('/cases', json={'title': '介面測試'}).json()['id']
        self.other = self.client.post('/cases', json={'title': '另一案件'}).json()['id']

    def tearDown(self):
        self.client.__exit__(None, None, None)
        shutil.rmtree(self.directory, ignore_errors=True)

    def saved_run(self, matches, agent=False):
        store = self.app.state.store
        run, _ = store.submit(self.case, None, 'agent' if agent else 'references', '', uuid.uuid4().hex, 'f')
        evidence = {'id': 'references:selected-image', 'kind': 'image_references', 'matches': matches}
        result = {'citations': [evidence]} if agent else {'evidence': {evidence['id']: evidence}}
        store.update_run(run['id'], 'succeeded', result)
        return run['id']

    def reference(self, run_id, index=0, case=None):
        return self.client.get(f'/cases/{case or self.case}/runs/{run_id}/references/{index}')

    def valid_row(self):
        path = ROOT / 'bottle/train/good/196.png'
        if not path.is_file():
            self.skipTest('local bottle dataset not installed')
        return {'path': 'train/good/196.png', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_dashboard_and_asset_content_types(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="zh-Hant"', response.text)
        self.assertIn('/assets/app.js', response.text)
        self.assertIn('text/html', response.headers['content-type'])
        for name, kind in [('app.css', 'text/css'), ('app.js', 'text/javascript'), ('ui-core.mjs', 'text/javascript')]:
            response = self.client.get('/assets/' + name)
            self.assertEqual(response.status_code, 200)
            self.assertIn(kind, response.headers['content-type'])

    def test_asset_allowlist_does_not_expose_project_files(self):
        for name in ['.env.local', 'backend.py', 'case_store.py', 'index.html', 'requirements-backend.txt']:
            self.assertEqual(self.client.get('/assets/' + name).status_code, 404)

    def test_reference_is_served_from_saved_local_evidence(self):
        row = self.valid_row()
        response = self.reference(self.saved_run([row]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), row['sha256'])

    def test_agent_citations_can_supply_reference_images(self):
        self.assertEqual(self.reference(self.saved_run([self.valid_row()], agent=True)).status_code, 200)

    def test_reference_cannot_cross_cases(self):
        self.assertEqual(self.reference(self.saved_run([self.valid_row()]), case=self.other).status_code, 404)

    def test_reference_cannot_escape_normal_training_folder(self):
        for path in ['../../.env.local', 'test/broken_large/000.png', '/etc/passwd', 'train/good/../000.png']:
            run = self.saved_run([{'path': path, 'sha256': '0' * 64}])
            self.assertEqual(self.reference(run).status_code, 404)

    def test_reference_source_change_is_rejected(self):
        row = self.valid_row()
        row['sha256'] = '0' * 64
        self.assertEqual(self.reference(self.saved_run([row])).status_code, 409)

    def test_reference_index_bounds(self):
        run = self.saved_run([self.valid_row()])
        for index in [-1, 1, 3, 999]:
            self.assertEqual(self.reference(run, index).status_code, 404)
        self.assertEqual(self.reference(self.saved_run([])).status_code, 404)

    def test_reference_work_requires_selected_image(self):
        response = self.client.post(f'/cases/{self.case}/runs',
                                    json={'kind': 'references', 'request_key': 'reference-without-image'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'references_requires_image')

    def test_same_origin_allowed_and_other_local_port_rejected(self):
        self.assertEqual(self.client.get('/health', headers={'Origin': 'http://testserver'}).status_code, 200)
        self.assertEqual(self.client.get('/health', headers={'Origin': 'http://localhost:8001'}).status_code, 403)

    def test_fixed_sample_endpoint_and_no_arbitrary_sample_path(self):
        response = self.client.get('/demo/bottle.png')
        self.assertIn(response.status_code, (200, 404))
        if response.status_code == 200:
            self.assertEqual(response.content, (ROOT / 'bottle/test/broken_large/000.png').read_bytes())
        self.assertEqual(self.client.get('/demo/.env.local').status_code, 404)


if __name__ == '__main__':
    unittest.main()
