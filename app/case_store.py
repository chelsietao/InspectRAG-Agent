"""SQLite persistence, with case-scoped lookups and immutable report snapshots."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError('unsupported_database_version')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
                    sha256 TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
                    image_id TEXT REFERENCES images(id), kind TEXT NOT NULL,
                    question TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','running','succeeded','failed')),
                    result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(case_id, request_key));
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), version INTEGER NOT NULL,
                    snapshot TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_at TEXT,
                    UNIQUE(case_id, version));
                CREATE INDEX IF NOT EXISTS images_case ON images(case_id);
                CREATE INDEX IF NOT EXISTS runs_case ON runs(case_id);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def list(self, table, case_id=None):
        assert table in ('cases', 'images', 'runs', 'reports')
        with self.connection() as db:
            rows = db.execute(f'SELECT * FROM {table}' + (' WHERE case_id=?' if case_id else '')
                              + ' ORDER BY created_at,id', (case_id,) if case_id else ()).fetchall()
        return [self.decode(row) for row in rows]

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError('not_found')
        data = dict(row)
        for key in ('result', 'snapshot'):
            if data.get(key) is not None:
                data[key] = json.loads(data[key])
        data.pop('fingerprint', None)
        return data

    def get(self, table, item_id, case_id=None):
        assert table in ('cases', 'images', 'runs', 'reports')
        with self.connection() as db:
            row = db.execute(f'SELECT * FROM {table} WHERE id=?'
                             + (' AND case_id=?' if case_id else ''),
                             (item_id, case_id) if case_id else (item_id,)).fetchone()
        return self.decode(row)

    def create_case(self, title):
        item_id = identifier()
        with self.connection() as db:
            db.execute('INSERT INTO cases VALUES (?,?,?)', (item_id, title, now()))
        return self.get('cases', item_id)

    def add_image(self, case_id, image_id, digest, width, height):
        with self.connection() as db:
            db.execute('INSERT INTO images VALUES (?,?,?,?,?,?)',
                       (image_id, case_id, digest, width, height, now()))
        return self.get('images', image_id, case_id)

    def submit(self, case_id, image_id, kind, question, request_key, fingerprint):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM runs WHERE case_id=? AND request_key=?',
                             (case_id, request_key)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise ValueError('idempotency_conflict')
                return self.decode(row), False
            item_id, timestamp = identifier(), now()
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       (item_id, case_id, image_id, kind, question, request_key, fingerprint,
                        'pending', None, None, timestamp, timestamp))
        return self.get('runs', item_id, case_id), True

    def update_run(self, item_id, status, result=None, error=None):
        with self.connection() as db:
            db.execute('UPDATE runs SET status=?,result=?,error=?,updated_at=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                        error, now(), item_id))

    def recover(self):
        with self.connection() as db:
            cursor = db.execute("UPDATE runs SET status='failed',error='server_restarted',updated_at=? "
                                "WHERE status IN ('pending','running')", (now(),))
            return cursor.rowcount

    def draft(self, case_id, run_id):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM runs WHERE id=? AND case_id=?', (run_id, case_id)).fetchone()
            run = self.decode(row)
            if run['status'] != 'succeeded' or not run['result'] or not run['result'].get('answer') or run['result'].get('status') != 'answered':
                raise ValueError('answered_run_required')
            version = db.execute('SELECT COALESCE(MAX(version),0)+1 FROM reports WHERE case_id=?',
                                 (case_id,)).fetchone()[0]
            item_id = identifier()
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                       (item_id, case_id, run_id, version,
                        json.dumps(run['result'], ensure_ascii=False), now(), None))
        return self.get('reports', item_id, case_id)

    def confirm(self, case_id, report_id):
        with self.connection() as db:
            cursor = db.execute('UPDATE reports SET confirmed_at=COALESCE(confirmed_at,?) '
                                'WHERE id=? AND case_id=?', (now(), report_id, case_id))
            if cursor.rowcount != 1:
                raise KeyError('not_found')
        return self.get('reports', report_id, case_id)
