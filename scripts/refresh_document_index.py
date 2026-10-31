"""Refresh the active corpus index with the pinned local encoder, without downloads."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import uuid

import faiss
from embedding_client import VectorWorker
from retrieval_core import digest, normalize, validate_corpus, verify_index, write_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true', help='Replace active index after retaining a backup')
    args = parser.parse_args()
    active = ROOT / 'indexes/documents_v1'
    previous = verify_index(active)
    for filename, checksum in previous['model_files'].items():
        if digest(ROOT / filename) != checksum:
            raise ValueError('local_encoder_changed')
    chunks, sources = validate_corpus(ROOT)
    destination = ROOT / 'indexes' / ('documents_refresh_' + uuid.uuid4().hex)
    destination.mkdir()
    worker = None
    try:
        worker = VectorWorker('document', ROOT / previous['model_path'])
        vectors = normalize(worker.request({'texts': ['passage: ' + row['title'] + ' ' + row['text'] for row in chunks]}))
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        faiss.write_index(index, str(destination / 'vectors.faiss'))
        metadata = {**previous, 'version': 'documents-v2-case-memory', 'count': len(chunks), 'sources': len(sources),
                    'chunk_ids': [row['chunk_id'] for row in chunks],
                    'builder_sha256': digest(Path(__file__)),
                    'corpus_files': {f'data/knowledge/{name}': digest(ROOT / 'data/knowledge' / name)
                                     for name in ['chunks.jsonl', 'sources.jsonl', 'dependencies.json']},
                    'files': {'vectors.faiss': digest(destination / 'vectors.faiss')}}
        write_json(destination / 'manifest.json', metadata)
        verify_index(destination)
    finally:
        if worker:
            worker.close()
    backup = None
    if args.activate:
        backup = ROOT / 'artifacts/index_backups' / uuid.uuid4().hex / 'documents_v1'
        backup.parent.mkdir(parents=True)
        active.rename(backup)
        try:
            destination.rename(active)
        except BaseException:
            backup.rename(active)
            raise
    print(json.dumps({'count': len(chunks), 'version': metadata['version'], 'downloads': 0,
                      'active': args.activate, 'index': str((active if args.activate else destination).relative_to(ROOT)),
                      'backup': str(backup.relative_to(ROOT)) if backup else None}, ensure_ascii=False))


if __name__ == '__main__':
    main()
