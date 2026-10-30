"""Evaluate a frozen project-authored retrieval set without answer generation."""
import argparse
import json
from pathlib import Path
import time
import importlib.metadata
import csv

import numpy as np

from retrieval_core import DocumentRetriever,ImageRetriever,digest,read_jsonl,write_json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/evaluation/retrieval_v1')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('評估輸出已存在，請選擇新位置')
    cases=ROOT/'evaluation/retrieval_v1'
    frozen=json.loads((cases/'frozen.json').read_text())
    for name,expected in frozen['question_file_sha256'].items():
        if digest(cases/name)!=expected:
            raise ValueError('固定評估題已變動')
    search=DocumentRetriever(ROOT,ROOT/'indexes/documents_v1')
    rows=[]
    by_split={}
    for split in ['dev','heldout']:
        split_rows=[]
        for case in read_jsonl(cases/f'{split}.jsonl'):
            started=time.perf_counter()
            result=search.search(case['query'],5)
            elapsed=time.perf_counter()-started
            actual=[row['chunk_id'] for row in result['matches']]
            targets=set(case['relevant_chunks'])
            hit=targets & set(actual)
            ranks=[actual.index(identifier)+1 for identifier in hit]
            row={**case,'split':split,'returned_chunks':actual,'recall_at_5':len(hit)/len(targets),
                 'reciprocal_rank':1/min(ranks) if ranks else 0.0,'seconds':elapsed,
                 'citation_ids_valid':all(identifier in {r['chunk_id'] for r in search.rows} for identifier in actual)}
            split_rows.append(row)
            rows.append(row)
        by_split[split]={'questions':len(split_rows),
            'recall_at_5':float(np.mean([r['recall_at_5'] for r in split_rows])),
            'mrr_at_5':float(np.mean([r['reciprocal_rank'] for r in split_rows])),
            'citation_id_validity':float(np.mean([r['citation_ids_valid'] for r in split_rows])),
            'latency_p50_seconds':float(np.percentile([r['seconds'] for r in split_rows],50)),
            'latency_p95_seconds':float(np.percentile([r['seconds'] for r in split_rows],95))}
    image_search=ImageRetriever(ROOT,ROOT/'indexes/normal_images_v1')
    examples=[]
    for path in ['test/good/000.png','test/broken_large/000.png']:
        result=image_search.search(ROOT/'bottle'/path,3)
        examples.append({'query_path':path,**result})
    first=ROOT/'bottle'/image_search.rows[0]['path']
    self_query=image_search.search(first,3)
    reference_paths=[row['path'] for row in image_search.rows]
    excluded=set(image_search.checkpoint['split']['calibration']+image_search.checkpoint['split']['test'])
    summary={
        'stage':'retrieval-only, no LLM generation or Agent',
        'document_sources':len(search.sources),'document_chunks':len(search.rows),
        'image_reference_count':len(reference_paths),'image_feature_dimension':image_search.index.d,
        'image_reference_roles':['normal training only'],
        'image_no_calibration_or_test_leakage':not bool(set(reference_paths)&excluded),
        'image_self_match_excluded':all(r['path']!=image_search.rows[0]['path'] for r in self_query['matches']),
        'document_model_revision':search.meta['model_revision'],
        'corpus_files':search.meta['corpus_files'],
        'frozen_evaluation_files':frozen['question_file_sha256'],
        'metrics':by_split,
        'source_hashes':{name:digest(ROOT/'scripts'/name) for name in ['retrieval_core.py','build_retrieval_indexes.py','evaluate_retrieval.py']},
        'versions':{name:importlib.metadata.version(name) for name in ['sentence-transformers','transformers','faiss-cpu','torch']},
        'limitations':[
            '題目與相關段落由同一專題建立，屬小型作者自訂評估，尚待使用者與獨立評閱者審查。',
            '沒有量測圖片相似性的人工精確率，圖片測試只驗證索引來源、可執行性與自身排除。',
            '引用編號有效不代表內容支持主張，生成回答、拒答、工具代理與主張支持評估尚未實作。',
            '相似度分數不代表答案正確機率，缺少來源的問題也可能回傳不相關候選。',
        ],
    }
    args.output.mkdir(parents=True)
    write_json(args.output/'metrics.json',summary)
    write_json(args.output/'question_results.json',rows)
    write_json(args.output/'image_examples.json',examples)
    # Use no synthesis: this file is the actual returned evidence, ready for inspection.
    write_json(args.output/'document_example.json',search.search('異常分數可以當成瑕疵機率嗎',5))
    with (args.output/'question_results.csv').open('w',newline='') as output:
        writer=csv.DictWriter(output,fieldnames=['id','split','query','recall_at_5','reciprocal_rank','seconds'],lineterminator='\n')
        writer.writeheader()
        writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
