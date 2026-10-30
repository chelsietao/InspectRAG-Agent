import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

if importlib.util.find_spec('faiss') is None:
    raise unittest.SkipTest('Install requirements-retrieval.txt to run retrieval tests')

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from retrieval_core import normalize,reciprocal_rank_fusion,rgb_pixel_hash,validate_corpus,verify_index


class RetrievalCoreTests(unittest.TestCase):
    def test_normalization(self):
        np.testing.assert_allclose(normalize([[3,4]]),[[0.6,0.8]],atol=1e-6)

    def test_invalid_vectors(self):
        for value in [[[0,0]],[[np.nan,1]],[1,2]]:
            with self.assertRaises(ValueError):
                normalize(value)

    def test_rank_fusion(self):
        self.assertEqual(reciprocal_rank_fusion([[1,2,3],[2,1,3]]),[1,2,3])
        self.assertEqual(reciprocal_rank_fusion([[2,1],[2,3]])[0],2)

    def test_pixel_hash_independent_of_png_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            first,second=Path(tmp)/'a.png',Path(tmp)/'b.png'
            image=Image.new('RGB',(8,8),(10,20,30))
            image.save(first,compress_level=0)
            image.save(second,compress_level=9)
            self.assertNotEqual(first.read_bytes(),second.read_bytes())
            self.assertEqual(rgb_pixel_hash(first),rgb_pixel_hash(second))

    def test_index_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'records.jsonl').write_text('original')
            checksum=hashlib.sha256(b'original').hexdigest()
            (folder/'manifest.json').write_text(json.dumps({'files':{'records.jsonl':checksum}}))
            verify_index(folder)
            (folder/'records.jsonl').write_text('changed')
            with self.assertRaises(ValueError):
                verify_index(folder)

    def test_corpus_integrity_and_eval_isolation(self):
        if not (ROOT/'data/knowledge/chunks.jsonl').exists():
            self.skipTest('Build the source-linked corpus first')
        rows,sources=validate_corpus(ROOT)
        self.assertGreaterEqual(len(rows),30)
        self.assertGreaterEqual(len(sources),5)
        allowed={'external_summary','project_summary'}
        self.assertTrue(all(row['type'] in allowed for row in sources))
        self.assertTrue(all('predictions.csv' not in row['source_url'] for row in rows))
        self.assertTrue(all('/evaluation/retrieval' not in row['source_url'] for row in rows))


@unittest.skipUnless((ROOT/'indexes/normal_images_v1/manifest.json').exists(),'Build image index first')
class ImageRetrievalIntegrationTests(unittest.TestCase):
    def test_train_only_excludes_self_and_reencoded_copy(self):
        from retrieval_core import ImageRetriever
        search=ImageRetriever(ROOT,ROOT/'indexes/normal_images_v1')
        first=ROOT/'bottle'/search.rows[0]['path']
        results=search.search(first,3)['matches']
        self.assertEqual(len(results),3)
        self.assertTrue(all(row['path'].startswith('train/good/') for row in results))
        self.assertTrue(all(row['path']!=search.rows[0]['path'] for row in results))
        with tempfile.TemporaryDirectory() as tmp:
            copy=Path(tmp)/'copy.png'
            with Image.open(first) as image:
                image.save(copy,compress_level=0)
            other=search.search(copy,3)['matches']
            self.assertEqual([r['path'] for r in results],[r['path'] for r in other])
        with self.assertRaises(ValueError):
            search.search(first,0)


@unittest.skipUnless((ROOT/'indexes/documents_v1/manifest.json').exists(),'Build document index first')
class DocumentRetrievalIntegrationTests(unittest.TestCase):
    def test_sources_and_invalid_query(self):
        from retrieval_core import DocumentRetriever
        search=DocumentRetriever(ROOT,ROOT/'indexes/documents_v1')
        result=search.search('異常分數是機率嗎',5)
        self.assertEqual(result['status'],'retrieved_candidates')
        self.assertEqual(len(result['matches']),5)
        self.assertIn('config-no-probability',[r['chunk_id'] for r in result['matches']])
        self.assertTrue(all(r['source_url'].startswith('https://') for r in result['matches']))
        with self.assertRaises(ValueError):
            search.search('   ')
        with self.assertRaises(ValueError):
            search.search('a'*2001)


if __name__=='__main__':
    unittest.main()
