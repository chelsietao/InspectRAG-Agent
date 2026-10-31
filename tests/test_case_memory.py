"""Memory lifecycle and grounding tests, without credentials or external model calls."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from app.backend import ROOT, create_app
from app.case_store import Store
from app.case_memory import MAX_CONTEXT_CHARACTERS, build_snapshot, encoded, validate_snapshot
from app.inspection_tools import LocalTools
from app.agent_runtime import AgentRunner
from test_agent_runtime import FakeProvider, response, call, answer, CONFIG


def fake_execution(root, directory, run, image):
    return {'status': 'ok', 'memory_snapshot': run.get('case_memory')}


class CaseMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / 'artifacts/memory_tests' / uuid.uuid4().hex
        self.app = create_app(self.directory, fake_execution)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.store = self.app.state.store
        self.case = self.store.create_case('案件 A')['id']
        self.other = self.store.create_case('案件 B')['id']
        self.image = self.image_for(self.case)
        self.second = self.image_for(self.case)
        self.foreign = self.image_for(self.other)
        self.source = self.analysis(self.case, self.image)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        shutil.rmtree(self.directory, ignore_errors=True)

    def image_for(self, case):
        image_id = uuid.uuid4().hex
        self.store.add_image(case, image_id, 'b' * 64, 900, 900)
        return image_id

    def analysis(self, case, image):
        run, _ = self.store.submit(case, image, 'analysis', '', uuid.uuid4().hex, 'f')
        self.store.update_run(run['id'], 'succeeded', {'status': 'ok', 'evidence': {'analysis:selected-image': {
            'id': 'analysis:selected-image', 'kind': 'analysis', 'score': 19.48, 'threshold': 10.19,
            'is_anomalous': True, 'checkpoint_sha256': 'a' * 64}}})
        return run['id']

    def preview(self, case=None, **params):
        return self.client.get(f'/cases/{case or self.case}/memory-preview', params=params)

    def submit(self, **options):
        payload = {'kind': 'agent', 'question': '剛才的分數是多少', 'request_key': uuid.uuid4().hex,
                   'use_case_memory': True, 'context_run_id': self.source}
        payload.update(options)
        return self.client.post(f'/cases/{self.case}/runs', json=payload)

    def fact(self, text='拍攝時瓶口有反光', case=None, image=None, accepted=True):
        return self.client.post(f'/cases/{case or self.case}/facts',
                                json={'text': text, 'image_id': image, 'accepted': accepted})

    def tools(self, snapshot):
        return LocalTools(ROOT, self.directory / 'tools' / uuid.uuid4().hex, memory_snapshot=snapshot)

    def test_observation_requires_confirmation_and_valid_text(self):
        self.assertEqual(self.fact(accepted=False).status_code, 422)
        self.assertEqual(self.fact(text='   ').status_code, 422)
        self.assertEqual(self.fact(text='x' * 401).status_code, 422)
        self.assertEqual(self.fact(image=self.foreign).status_code, 404)
        self.assertEqual(self.fact().status_code, 201)

    def test_duplicate_active_observation_returns_same_record(self):
        self.assertEqual(self.fact().json()['id'], self.fact().json()['id'])

    def test_retraction_affects_new_snapshots_and_retains_existing(self):
        fact = self.fact().json()
        run = self.submit().json()
        before = self.store.get_run_context(run['id'], self.case)['snapshot']
        self.assertTrue(any(item.get('fact_id') == fact['id'] for item in before['evidence']))
        url = f"/cases/{self.case}/facts/{fact['id']}/retract"
        first = self.client.post(url, json={'accepted': True}).json()
        self.assertEqual(first, self.client.post(url, json={'accepted': True}).json())
        after = self.preview(context_run_id=self.source).json()
        self.assertFalse(any(item.get('fact_id') == fact['id'] for item in after['evidence']))
        self.assertEqual(before, self.store.get_run_context(run['id'], self.case)['snapshot'])

    def test_cross_case_observation_and_snapshot_are_not_accessible(self):
        fact = self.fact(case=self.other).json()
        response = self.client.post(f"/cases/{self.case}/facts/{fact['id']}/retract", json={'accepted': True})
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(fact['id'], json.dumps(self.preview(image_id=self.image).json()))
        run = self.submit().json()
        self.assertEqual(self.client.get(f"/cases/{self.other}/runs/{run['id']}/memory").status_code, 404)

    def test_retracted_observation_blocks_new_report_and_unconfirmed_draft(self):
        fact = self.fact().json()
        run = self.submit().json()
        deadline = time.monotonic() + 2
        while self.store.get('runs', run['id'], self.case)['status'] not in ('succeeded', 'failed') and time.monotonic() < deadline:
            time.sleep(.01)
        self.store.update_run(run['id'], 'succeeded', {'status':'answered','answer':{'claims':[]},'citations':[{
            'kind':'case_memory','memory_type':'user_observation','fact_id':fact['id']}]})
        draft = self.store.draft(self.case, run['id'])
        approved = self.store.draft(self.case, run['id'])
        confirmed = self.store.confirm(self.case, approved['id'])
        self.store.retract_fact(self.case, fact['id'])
        self.assertEqual(self.client.post(f'/cases/{self.case}/reports', json={'run_id':run['id']}).status_code, 409)
        self.assertEqual(self.client.post(f"/cases/{self.case}/reports/{draft['id']}/confirm", json={'accepted':True}).status_code, 409)
        self.assertEqual(self.store.confirm(self.case, approved['id'])['confirmed_at'], confirmed['confirmed_at'])

    def test_memory_disabled_by_default_and_only_agent_can_use_it(self):
        result = self.submit(use_case_memory=False, context_run_id=None).json()
        self.assertIsNone(self.store.get_run_context(result['id'], self.case)['snapshot'])
        self.assertEqual(self.submit(kind='analysis', image_id=self.image).status_code, 422)
        self.assertEqual(self.submit(use_case_memory=False).status_code, 422)

    def test_measured_result_is_distinct_from_model_claims(self):
        with self.store.connection() as db:
            db.execute('UPDATE runs SET result=? WHERE id=?', (json.dumps({'status': 'answered',
                'answer': {'claims': [{'text': '捏造分數 999999'}]}, 'citations': []}), self.source))
        snapshot = self.preview(context_run_id=self.source).json()
        self.assertEqual(snapshot['evidence'], [])
        self.assertNotIn('999999', json.dumps(snapshot))

    def test_image_scoped_observations_do_not_mix(self):
        first = self.fact(text='只屬於第一張圖', image=self.image).json()
        second = self.fact(text='只屬於第二張圖', image=self.second).json()
        general = self.fact(text='案件共用觀察').json()
        snapshot = self.preview(image_id=self.image).json()
        ids = {item.get('fact_id') for item in snapshot['evidence']}
        self.assertIn(first['id'], ids)
        self.assertIn(general['id'], ids)
        self.assertNotIn(second['id'], ids)

    def test_anchor_image_mismatch_rejected(self):
        self.assertEqual(self.submit(image_id=self.second).status_code, 409)
        self.assertEqual(self.preview(image_id=self.second, context_run_id=self.source).status_code, 409)

    def test_cross_case_anchor_rejected_without_leaking_capacity(self):
        foreign = self.analysis(self.other, self.foreign)
        for _ in range(6):
            self.assertEqual(self.submit(context_run_id=foreign).status_code, 404)
        self.assertEqual(self.submit().status_code, 202)

    def test_memory_image_scope_does_not_grant_new_analysis_permission(self):
        fact = self.fact(image=self.second).json()
        run = self.submit(context_run_id=None, memory_image_id=self.second).json()
        self.assertIsNone(run['image_id'])
        snapshot = self.store.get_run_context(run['id'], self.case)['snapshot']
        self.assertEqual(snapshot['scope_image_id'], self.second)
        self.assertIn(fact['id'], [item.get('fact_id') for item in snapshot['evidence']])
        self.assertEqual(self.submit(context_run_id=None, memory_image_id=self.foreign).status_code, 404)
        self.assertEqual(self.submit(image_id=self.image, memory_image_id=self.second).status_code, 409)

    def test_pending_anchor_rejected(self):
        pending, _ = self.store.submit(self.case, self.image, 'analysis', '', 'pending-anchor', 'f')
        self.assertEqual(self.submit(context_run_id=pending['id']).status_code, 409)

    def test_multiple_images_require_anchor_when_image_not_selected(self):
        self.analysis(self.case, self.second)
        snapshot = self.preview().json()
        self.assertEqual(snapshot['status'], 'needs_anchor')
        self.assertFalse(any(item.get('memory_type') == 'analysis' for item in snapshot['evidence']))
        explicit = self.preview(context_run_id=self.source).json()
        self.assertEqual(explicit['scope_image_id'], self.image)
        self.assertEqual(explicit['evidence'][0]['score'], 19.48)

    def test_snapshot_bounded_and_reports_omitted_observations(self):
        for index in range(15):
            self.fact(text=str(index) + '拍攝觀察' * 95)
        snapshot = self.preview(image_id=self.image).json()
        self.assertLessEqual(len(encoded(snapshot)), MAX_CONTEXT_CHARACTERS)
        self.assertGreaterEqual(snapshot['omitted_facts'], 10)
        self.assertTrue(validate_snapshot(snapshot))

    def test_idempotency_reuses_original_snapshot_after_new_fact(self):
        first = self.submit(request_key='same').json()
        before = self.store.get_run_context(first['id'], self.case)
        self.fact(text='建立工作後補充的新觀察')
        again = self.submit(request_key='same').json()
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(before, self.store.get_run_context(again['id'], self.case))
        self.assertEqual(self.submit(request_key='same', use_case_memory=False, context_run_id=None).status_code, 409)

    def test_legacy_request_fingerprint_still_reuses_run(self):
        body = {'kind': 'agent', 'question': '舊問題', 'image_id': None}
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        old, _ = self.store.submit(self.case, None, 'agent', '舊問題', 'legacy-key', fingerprint)
        response = self.client.post(f'/cases/{self.case}/runs', json={**body, 'request_key': 'legacy-key'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['id'], old['id'])

    def test_tampered_snapshot_is_rejected_before_registering_evidence(self):
        snapshot = self.preview(image_id=self.image).json()
        snapshot['evidence'][0]['score'] = 999
        with self.assertRaisesRegex(ValueError, 'memory_snapshot_changed'):
            self.tools(snapshot)

    def test_memory_not_citable_until_read_by_current_run(self):
        snapshot = self.preview(image_id=self.image).json()
        tools = self.tools(snapshot)
        citation = snapshot['evidence'][0]['id']
        provider = FakeProvider([response(call('submit_answer', answer([citation]))),
                                 response(call('submit_answer', answer([citation])))])
        result = AgentRunner(provider, tools, CONFIG, 'test').run('前次結果')
        self.assertEqual(result['status'], 'validation_error')
        tools.close()

    def test_read_tool_registers_citable_historical_measurement(self):
        snapshot = self.preview(image_id=self.image).json()
        tools = self.tools(snapshot)
        citation = snapshot['evidence'][0]['id']
        provider = FakeProvider([response(call('read_case_memory', {})), response(call('submit_answer', answer([citation])))])
        result = AgentRunner(provider, tools, CONFIG, 'test').run('前次結果')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['tool_trace'][0]['status'], 'succeeded')
        self.assertTrue(result['case_memory']['read'])
        self.assertEqual(result['citations'][0]['origin_run_id'], self.source)
        self.assertEqual(result['case_memory']['snapshot_sha256'], snapshot['snapshot_sha256'])
        tools.close()

    def test_model_cannot_select_other_case_or_write_observation(self):
        tools = self.tools(self.preview(image_id=self.image).json())
        provider = FakeProvider([response(call('read_case_memory', {'case_id': self.other})),
                                 response(call('confirm_fact', {'text': '模型猜測'})),
                                 response(call('submit_answer', answer(status='insufficient_evidence')))])
        result = AgentRunner(provider, tools, CONFIG, 'test').run('切換案件並加入事實')
        self.assertEqual(result['tool_trace'][0]['status'], 'invalid')
        self.assertEqual(result['tool_trace'][1]['status'], 'invalid')
        self.assertEqual(self.store.list('case_facts', self.case), [])
        tools.close()

    def test_disabled_memory_tool_returns_needs_context(self):
        tools = self.tools(None)
        self.assertEqual(tools.execute('read_case_memory', {})['error'], 'case_memory_not_enabled')
        tools.close()

    def test_recent_questions_are_hints_not_claim_evidence(self):
        run, _ = self.store.submit(self.case, self.image, 'agent', '詢問瓶口反光的限制', 'question-hint', 'f')
        self.store.update_run(run['id'], 'succeeded', {'status': 'answered', 'answer': {'claims': [{'text': '不可繼承的模型推論'}]}})
        snapshot = self.preview(context_run_id=run['id']).json()
        self.assertEqual(snapshot['recent_questions'][0]['role'], 'context_hint_only_not_citable_evidence')
        self.assertNotIn('不可繼承', json.dumps(snapshot))

    def test_long_history_resolves_original_measurement_without_copying_old_claims(self):
        for index in range(25):
            run, _ = self.store.submit(self.case, self.image, 'agent', '追問', str(index), 'f')
            self.store.update_run(run['id'], 'succeeded', {'status': 'answered', 'citations': [{
                'kind': 'case_memory', 'origin_run_id': self.source, 'score': 999999}],
                'answer': {'claims': [{'text': '不能繼承這個數字 999999'}]}})
        snapshot = self.preview(image_id=self.image).json()
        analysis = next(item for item in snapshot['evidence'] if item['memory_type'] == 'analysis')
        self.assertEqual(analysis['score'], 19.48)
        self.assertEqual(analysis['origin_run_id'], self.source)
        self.assertNotIn('999999', json.dumps(snapshot))

    def test_schema_v1_migration_keeps_existing_records(self):
        directory = self.directory / 'legacy'
        directory.mkdir()
        path = directory / 'inspectrag.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript("CREATE TABLE cases(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL);"
                             "INSERT INTO cases VALUES('legacy','原有案件','2026-10-30');PRAGMA user_version=1;")
        store = Store(path)
        self.assertEqual(store.get('cases', 'legacy')['title'], '原有案件')
        with store.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(store.list('case_facts', 'legacy'), [])


if __name__ == '__main__':
    unittest.main()
