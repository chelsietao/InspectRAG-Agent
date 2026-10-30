"""Build separate normal-image and source-linked document indexes."""
import argparse
import json
from pathlib import Path
import importlib.metadata

import faiss
from huggingface_hub import HfApi
import numpy as np
from embedding_client import VectorWorker

from retrieval_core import digest,normalize,read_jsonl,validate_corpus,write_json

ROOT=Path(__file__).resolve().parents[1]


def seal(directory,meta):
    meta['files']={p.name:digest(p) for p in directory.iterdir() if p.is_file() and p.name!='manifest.json'}
    meta['builder_sha256']=digest(Path(__file__))
    meta['retrieval_core_sha256']=digest(Path(__file__).with_name('retrieval_core.py'))
    meta['versions']={name:importlib.metadata.version(name) for name in
                      ['faiss-cpu','sentence-transformers','transformers','torch','numpy']}
    write_json(directory/'manifest.json',meta)


def build_images():
    directory=ROOT/'indexes/normal_images_v1'
    if directory.exists():
        raise ValueError('圖片索引已存在，請先保留舊結果再指定新版本')
    checkpoint_path=ROOT/'artifacts/vision_baseline_v1/patchcore_bottle.pt'
    worker=VectorWorker('image',checkpoint_path)
    checkpoint=worker.info
    source_manifest=ROOT/'data/manifests/bottle_manifest.jsonl'
    if digest(source_manifest)!=checkpoint['training_manifest_sha256']:
        raise ValueError('資料清單與模型來源不一致')
    paths=checkpoint['split']['training']
    excluded=set(checkpoint['split']['calibration']+checkpoint['split']['test'])
    if set(paths)&excluded or any(not p.startswith('train/good/') for p in paths):
        raise ValueError('索引來源切分不符合規則')
    by_path={r['path']:r for r in read_jsonl(source_manifest)}
    rows=[]
    vectors=[]
    for relative in paths:
        row=by_path[relative]
        path=ROOT/'bottle'/relative
        if digest(path)!=row['sha256']:
            raise ValueError('來源圖片已變動')
        vectors.append(normalize(worker.request({'path':str(path)})))
        rows.append({key:row[key] for key in ['path','sha256','pixel_sha256']})
    worker.close()
    array=np.concatenate(vectors)
    index=faiss.IndexFlatIP(array.shape[1])
    index.add(array)
    directory.mkdir(parents=True)
    faiss.write_index(index,str(directory/'vectors.faiss'))
    (directory/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    seal(directory,{'version':'normal-images-v1','kind':'image','count':len(rows),
                    'dimension':array.shape[1],'checkpoint_path':str(checkpoint_path.relative_to(ROOT)),
                    'checkpoint_sha256':digest(checkpoint_path),'data_manifest_sha256':digest(source_manifest),
                    'feature':'layer2/layer3 average-pool 4x4, concat, L2 normalize',
                    'metric':'cosine via normalized inner product','excluded_roles':['calibration','test']})
    print(f'Image index ready: {len(rows)} normal training images',flush=True)


def build_documents():
    directory=ROOT/'indexes/documents_v1'
    if directory.exists():
        raise ValueError('文件索引已存在，請保留舊版本後再建新索引')
    chunks,sources=validate_corpus(ROOT)
    name='intfloat/multilingual-e5-small'
    revision=HfApi().model_info(name).sha
    print(f'Downloading public multilingual encoder at revision {revision}',flush=True)
    model_path=ROOT/'models/multilingual-e5-small'
    if model_path.exists():
        raise ValueError('本機文字模型資料夾已存在，請保留並確認版本後再重建')
    worker=VectorWorker('document',model_path,download_model=name,revision=revision)
    vectors=normalize(worker.request({'texts':['passage: '+r['title']+' '+r['text'] for r in chunks]}))
    worker.close()
    index=faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    directory.mkdir(parents=True)
    faiss.write_index(index,str(directory/'vectors.faiss'))
    meta={'version':'documents-v1','kind':'document','count':len(chunks),'sources':len(sources),
          'dimension':vectors.shape[1],'model_name':name,'model_revision':revision,
          'model_path':str(model_path.relative_to(ROOT)),'max_seq_length':512,
          'metric':'cosine via normalized inner product','fusion':'reciprocal rank fusion k=60',
          'chunk_ids':[r['chunk_id'] for r in chunks],
          'model_files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(model_path.rglob('*')) if p.is_file()},
          'corpus_files':{f'data/knowledge/{name}':digest(ROOT/'data/knowledge'/name)
                          for name in ['chunks.jsonl','sources.jsonl','dependencies.json']}}
    seal(directory,meta)
    print(f'Document index ready: {len(chunks)} chunks, {len(sources)} sources',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=['image','document','all'],default='all')
    args=parser.parse_args()
    if args.kind in ['image','all']:
        build_images()
    if args.kind in ['document','all']:
        build_documents()
