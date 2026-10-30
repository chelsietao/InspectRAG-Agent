"""Retrieval-only building blocks, with local indexes and explicit provenance."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import faiss
import numpy as np
from PIL import Image
from collections import Counter
import math
from embedding_client import VectorWorker

faiss.omp_set_num_threads(1)


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def normalize(vectors):
    values = np.ascontiguousarray(vectors,dtype=np.float32)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("向量必須是有限數值的二維陣列")
    lengths = np.linalg.norm(values,axis=1,keepdims=True)
    if np.any(lengths == 0):
        raise ValueError("不能使用零向量")
    return np.ascontiguousarray(values/lengths,dtype=np.float32)


def rgb_pixel_hash(path: Path):
    with Image.open(path) as image:
        image=image.convert("RGB")
        return hashlib.sha256(f"RGB:{image.width}:{image.height}:".encode()+image.tobytes()).hexdigest()


def reciprocal_rank_fusion(rankings, k=60):
    scores={}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking,1):
            scores[identifier]=scores.get(identifier,0.0)+1/(k+rank)
    return sorted(scores, key=lambda value:(-scores[value],value))


def validate_corpus(root: Path):
    folder=root/'data/knowledge'
    chunks=read_jsonl(folder/'chunks.jsonl')
    sources=read_jsonl(folder/'sources.jsonl')
    source_ids={row['source_id'] for row in sources}
    if len(source_ids)!=len(sources):
        raise ValueError('重複來源 ID')
    if len({r['chunk_id'] for r in chunks})!=len(chunks):
        raise ValueError('重複段落 ID')
    for row in chunks:
        if row['source_id'] not in source_ids or not row['text'].strip():
            raise ValueError('缺少來源或段落內容')
        if hashlib.sha256(row['text'].encode()).hexdigest()!=row['text_sha256']:
            raise ValueError('段落雜湊不符，需重新整理知識庫')
        if not row['source_url'].startswith('https://'):
            raise ValueError('來源需使用 HTTPS 網址')
    for relative,expected in json.loads((folder/'dependencies.json').read_text()).items():
        if digest(root/relative)!=expected:
            raise ValueError(f'來源文件已變動，需重新整理知識庫：{relative}')
    return chunks,sources


def verify_index(directory: Path):
    meta=json.loads((directory/'manifest.json').read_text())
    for filename,expected in meta['files'].items():
        if Path(filename).name!=filename or digest(directory/filename)!=expected:
            raise ValueError(f'索引內容或 metadata 已變動：{filename}')
    return meta


def lexical_scores(texts,query):
    def grams(text):
        value=text.lower()
        return Counter(value[i:i+n] for n in (2,3,4) for i in range(len(value)-n+1))
    documents=[grams(text) for text in texts]
    question=grams(query)
    frequencies=Counter(term for document in documents for term in document)
    idf={term:math.log((1+len(documents))/(1+count))+1 for term,count in frequencies.items()}
    def weight(counter):
        return {term:(1+math.log(count))*idf[term] for term,count in counter.items() if term in idf}
    q=weight(question)
    qnorm=math.sqrt(sum(v*v for v in q.values()))
    values=[]
    for counter in documents:
        d=weight(counter)
        dnorm=math.sqrt(sum(v*v for v in d.values()))
        dot=sum(value*d.get(term,0) for term,value in q.items())
        values.append(dot/(qnorm*dnorm) if qnorm and dnorm else 0.0)
    return np.asarray(values,dtype=np.float32)


class ImageRetriever:
    def __init__(self,root:Path,directory:Path):
        self.root=root
        self.meta=verify_index(directory)
        if digest(root/self.meta['checkpoint_path'])!=self.meta['checkpoint_sha256']:
            raise ValueError('模型檢查點已變動，需重建索引')
        self.rows=read_jsonl(directory/'records.jsonl')
        if not self.rows or any(not r['path'].startswith('train/good/') for r in self.rows):
            raise ValueError('參考庫含非正常訓練資料')
        self.index=faiss.read_index(str(directory/'vectors.faiss'))
        if self.index.ntotal!=len(self.rows):
            raise ValueError('索引筆數與圖片清單不符')
        self.worker=VectorWorker('image',root/self.meta['checkpoint_path'])
        self.checkpoint=self.worker.info

    def search(self,image:Path,k:int=3):
        if not 1<=k<=20:
            raise ValueError('候選數需介於 1 與 20')
        query_hash=rgb_pixel_hash(image)
        vector=normalize(self.worker.request({'path':str(image.resolve())}))
        similarities,indices=self.index.search(vector,self.index.ntotal)
        result=[]
        for similarity,index in zip(similarities[0],indices[0]):
            row=self.rows[int(index)]
            if row['pixel_sha256']==query_hash:
                continue
            path=self.root/'bottle'/row['path']
            if digest(path)!=row['sha256']:
                raise ValueError('參考圖片已變動，需重新驗證與建庫')
            result.append({**row,'cosine_similarity':float(similarity)})
            if len(result)==k:
                break
        return {'query_image':image.name,'index_version':self.meta['version'],
                'matches':result,'note':'結果是外觀相似的正常參考圖，未判定瑕疵類型、根因或允收狀態。'}


class DocumentRetriever:
    def __init__(self,root:Path,directory:Path):
        self.root=root
        self.meta=verify_index(directory)
        for relative,expected in self.meta['corpus_files'].items():
            if digest(root/relative)!=expected:
                raise ValueError('知識庫內容已變動，需重建索引')
        self.rows,self.sources=validate_corpus(root)
        self.index=faiss.read_index(str(directory/'vectors.faiss'))
        if self.index.ntotal!=len(self.rows) or [r['chunk_id'] for r in self.rows]!=self.meta['chunk_ids']:
            raise ValueError('段落次序與索引不符')
        for relative,expected in self.meta.get('model_files',{}).items():
            if digest(root/relative)!=expected:
                raise ValueError('文字模型檔案已變動')
        self.worker=VectorWorker('document',root/self.meta['model_path'])
        self.texts=[r['title']+' '+r['text'] for r in self.rows]

    def search(self,query:str,k:int=5):
        if not isinstance(query,str) or not query.strip() or len(query)>2000:
            raise ValueError('問題需為 1 至 2,000 字的文字')
        if not 1<=k<=20:
            raise ValueError('候選數需介於 1 與 20')
        query_vector=normalize(self.worker.request({'texts':['query: '+query]}))
        dense_scores,dense_ids=self.index.search(query_vector,len(self.rows))
        dense_order=[int(i) for i in dense_ids[0]]
        dense_by_id={int(i):float(s) for i,s in zip(dense_ids[0],dense_scores[0])}
        keyword_scores=lexical_scores(self.texts,query)
        lexical_order=[int(i) for i in np.argsort(-keyword_scores,kind='stable') if keyword_scores[i]>0]
        merged=reciprocal_rank_fusion([dense_order,lexical_order])[:k]
        matches=[]
        sources={r['source_id']:r for r in self.sources}
        for i in merged:
            matches.append({**self.rows[i],'dense_similarity':dense_by_id[i],
                            'lexical_similarity':float(keyword_scores[i]),
                            'source_title':sources[self.rows[i]['source_id']]['title'],
                            'review_status':sources[self.rows[i]['source_id']]['review_status']})
        return {'query':query,'status':'retrieved_candidates','index_version':self.meta['version'],
                'matches':matches,'note':'這是檢索候選，並非已驗證的答案。相似度不代表證據足夠，生成、拒答與主張支持判斷尚未實作。'}
