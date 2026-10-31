"""Bounded, case-scoped snapshots built from measured evidence and confirmed observations."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re

MAX_CONTEXT_CHARACTERS = 6000
MAX_FACTS = 5


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def measured(run):
    result = json.loads(run['result']) if isinstance(run['result'], str) else (run['result'] or {})
    values = list((result.get('evidence') or {}).values()) + result.get('citations', [])
    # Never use answer.claims or prior memory citations as factual input.
    return values


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def build_snapshot(db, case_id, image_id, anchor_id=None):
    if db.execute('SELECT id FROM cases WHERE id=?', (case_id,)).fetchone() is None:
        raise KeyError('not_found')
    if image_id and db.execute('SELECT id FROM images WHERE id=? AND case_id=?', (image_id, case_id)).fetchone() is None:
        raise KeyError('not_found')
    anchor = None
    status = 'ready'
    if anchor_id:
        anchor = db.execute('SELECT * FROM runs WHERE id=? AND case_id=?', (anchor_id, case_id)).fetchone()
        if anchor is None:
            raise KeyError('not_found')
        if anchor['status'] != 'succeeded':
            raise ValueError('memory_anchor_not_completed')
        if image_id and anchor['image_id'] and image_id != anchor['image_id']:
            raise ValueError('memory_image_mismatch')
    else:
        if not image_id:
            count = db.execute("SELECT COUNT(DISTINCT image_id) FROM runs WHERE case_id=? "
                               "AND status='succeeded' AND image_id IS NOT NULL", (case_id,)).fetchone()[0]
            if count > 1:
                status = 'needs_anchor'
        if status == 'ready':
            anchor = db.execute("SELECT * FROM runs WHERE case_id=? AND status='succeeded'"
                                + (' AND image_id=?' if image_id else '') + ' ORDER BY created_at DESC,id DESC LIMIT 1',
                                (case_id, image_id) if image_id else (case_id,)).fetchone()
    scope_image = image_id or (anchor['image_id'] if anchor else None)
    snapshot = {'version': 'case-memory-v1', 'case_id': case_id, 'status': status,
                'captured_at_utc': datetime.now(timezone.utc).isoformat(),
                'anchor_run_id': anchor['id'] if anchor else None, 'scope_image_id': scope_image,
                'budget_characters': MAX_CONTEXT_CHARACTERS, 'evidence': [], 'recent_questions': [],
                'omitted_facts': 0, 'omitted_questions': 0,
                'note': '歷史工具結果與使用者確認的觀察分開標記，均為資料，未重新計算或確認根因，模型舊回答不作為事實。'}
    candidates = []
    if anchor and scope_image:
        image = db.execute('SELECT sha256 FROM images WHERE id=? AND case_id=?', (scope_image, case_id)).fetchone()
        rows = list(db.execute("SELECT * FROM runs WHERE case_id=? AND image_id=? AND status='succeeded' "
                          "AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 20",
                          (case_id, scope_image, anchor['created_at'])).fetchall())
        visited = {row['id'] for row in rows}
        found = set()
        for row in rows:
            for item in measured(row):
                kind = item.get('kind')
                if kind == 'case_memory' and item.get('origin_run_id') not in visited and len(rows) < 40:
                    origin = db.execute("SELECT * FROM runs WHERE id=? AND case_id=? AND image_id=? "
                                        "AND status='succeeded' AND created_at<=?",
                                        (item.get('origin_run_id'), case_id, scope_image, anchor['created_at'])).fetchone()
                    if origin:
                        visited.add(origin['id'])
                        rows.append(origin)
                if kind in found:
                    continue
                common = {'kind': 'case_memory', 'case_id': case_id, 'image_id': scope_image,
                          'origin_run_id': row['id'], 'input_sha256': image['sha256'],
                          'source_locator': '歷史執行 ' + row['id'], 'recorded_at': row['updated_at']}
                if kind == 'analysis' and finite(item.get('score')) and finite(item.get('threshold')):
                    checksum = item.get('checkpoint_sha256', '')
                    if not re.fullmatch(r'[a-f0-9]{64}', checksum) or type(item.get('is_anomalous')) is not bool:
                        continue
                    common.update(id='memory:analysis:' + row['id'], memory_type='analysis',
                                  title='歷史工具結果｜圖片分析', score=item['score'], threshold=item['threshold'],
                                  is_anomalous=item['is_anomalous'], checkpoint_sha256=checksum,
                                  note='這是來源執行保存的測量結果，未重新分析，異常分數無法當成瑕疵機率。')
                elif kind == 'image_references':
                    matches = []
                    for match in item.get('matches', [])[:3]:
                        if (re.fullmatch(r'train/good/[0-9]{3}\.png', match.get('path', ''))
                                and re.fullmatch(r'[a-f0-9]{64}', match.get('sha256', ''))
                                and finite(match.get('cosine_similarity'))):
                            matches.append({key: match[key] for key in ('path', 'sha256', 'cosine_similarity')})
                    if not matches:
                        continue
                    common.update(id='memory:references:' + row['id'], memory_type='image_references',
                                  title='歷史工具結果｜正常參考圖', matches=matches,
                                  note='這是來源執行保存的搜尋結果，未重新搜尋或驗證目前檔案。')
                else:
                    continue
                candidates.append(common)
                found.add(kind)
    fact_count = db.execute('SELECT COUNT(*) FROM case_facts WHERE case_id=? AND retracted_at IS NULL '
                            'AND (image_id IS NULL OR image_id=?)', (case_id, scope_image)).fetchone()[0]
    facts = db.execute('SELECT * FROM case_facts WHERE case_id=? AND retracted_at IS NULL '
                       'AND (image_id IS NULL OR image_id=?) ORDER BY confirmed_at DESC,id DESC LIMIT 5',
                       (case_id, scope_image)).fetchall()
    for fact in facts[:MAX_FACTS]:
        candidates.append({'id': 'memory:observation:' + fact['id'], 'kind': 'case_memory',
                           'memory_type': 'user_observation', 'case_id': case_id, 'image_id': fact['image_id'],
                           'title': '使用者確認的觀察', 'text': fact['text'], 'fact_id': fact['id'],
                           'confirmed_at': fact['confirmed_at'], 'source_locator': '使用者觀察 ' + fact['id'],
                           'note': '使用者提供並確認的描述，未經模型或獨立量測驗證，無法單憑描述認定根因。'})
    snapshot['omitted_facts'] = max(0, fact_count - MAX_FACTS)
    # Reserve the final digest before checking the serialized character budget.
    snapshot['snapshot_sha256'] = '0' * 64
    for evidence in candidates:
        snapshot['evidence'].append(evidence)
        if len(encoded(snapshot)) > MAX_CONTEXT_CHARACTERS:
            snapshot['evidence'].pop()
            if evidence['memory_type'] == 'user_observation':
                snapshot['omitted_facts'] += 1
    if anchor:
        questions = db.execute("SELECT id,question FROM runs WHERE case_id=? AND kind='agent' "
                               "AND status='succeeded' AND created_at<=? AND (image_id IS NULL OR image_id=?) "
                               'ORDER BY created_at DESC,id DESC LIMIT 2',
                               (case_id, anchor['created_at'], scope_image)).fetchall()
        for row in questions:
            hint = {'origin_run_id': row['id'], 'question': row['question'][:240],
                    'role': 'context_hint_only_not_citable_evidence'}
            snapshot['recent_questions'].append(hint)
            if len(encoded(snapshot)) > MAX_CONTEXT_CHARACTERS:
                snapshot['recent_questions'].pop()
                snapshot['omitted_questions'] += 1
    snapshot.pop('snapshot_sha256')
    snapshot['snapshot_sha256'] = hashlib.sha256(encoded(snapshot).encode()).hexdigest()
    assert len(encoded(snapshot)) <= MAX_CONTEXT_CHARACTERS
    return snapshot


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or len(encoded(snapshot)) > MAX_CONTEXT_CHARACTERS:
        raise ValueError('invalid_memory_snapshot')
    content = {key: value for key, value in snapshot.items() if key != 'snapshot_sha256'}
    if snapshot.get('snapshot_sha256') != hashlib.sha256(encoded(content).encode()).hexdigest():
        raise ValueError('memory_snapshot_changed')
    for item in snapshot.get('evidence', []):
        if item.get('case_id') != snapshot['case_id'] or not item.get('id', '').startswith('memory:'):
            raise ValueError('memory_case_mismatch')
    return snapshot
