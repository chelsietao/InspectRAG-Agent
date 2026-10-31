"""Local inspection tools, lazily loaded and restricted to selected input and corpus."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'scripts') not in sys.path:
    sys.path.insert(0,str(ROOT/'scripts'))


class LocalTools:
    def __init__(self,root:Path,output:Path,image:Path|None=None):
        self.root=root
        self.output=output
        self.image=image.resolve() if image else None
        self.documents=None
        self.references=None
        self.evidence={}
        self.seen_chunks={}
        self.cache={}
        self.output.mkdir(parents=True,exist_ok=False)
        if self.image:
            from PIL import Image
            if not self.image.is_file() or self.image.stat().st_size>20*1024*1024:
                raise ValueError('image_missing_or_too_large')
            with Image.open(self.image) as source:
                source.verify()

    def _doc_evidence(self,row):
        identifier='doc:'+row['chunk_id']
        self.evidence[identifier]={'id':identifier,'kind':'document','title':row['title'],
            'source_url':row['source_url'],'source_locator':row['source_locator'],
            'text':row['text'],'review_status':row.get('review_status','assistant_source_checked_pending_user_review')}
        return {'evidence_id':identifier,'title':row['title'],'text':row['text'],
                'source_url':row['source_url']}

    def execute(self,name,args):
        key=json.dumps([name,args],sort_keys=True,ensure_ascii=False)
        if key in self.cache:
            return {**self.cache[key],'cached':True}
        if name in ['analyze_image','search_reference_images'] and not self.image:
            return {'status':'needs_context','error':'image_required','message':'請先選取要分析的圖片。'}
        if name=='search_documents':
            if self.documents is None:
                from retrieval_core import DocumentRetriever
                self.documents=DocumentRetriever(self.root,self.root/'indexes/documents_v1')
            result=self.documents.search(args['query'],args['k'])
            matches=[]
            for row in result['matches']:
                self.seen_chunks[row['chunk_id']]=row
                matches.append(self._doc_evidence(row))
            payload={'status':'ok','matches':matches,'note':'候選段落需核對是否支持問題，來源摘要尚待使用者審閱。'}
        elif name=='read_evidence':
            if any(identifier not in self.evidence or self.evidence[identifier]['kind']!='document'
                   for identifier in args['evidence_ids']):
                return {'status':'error','error':'evidence_not_retrieved'}
            payload={'status':'ok','matches':[{'evidence_id':identifier,
                     'title':self.evidence[identifier]['title'],'text':self.evidence[identifier]['text'],
                     'source_url':self.evidence[identifier]['source_url']}
                     for identifier in args['evidence_ids']]}
        elif name=='search_reference_images':
            if self.references is None:
                from retrieval_core import ImageRetriever
                self.references=ImageRetriever(self.root,self.root/'indexes/normal_images_v1')
            result=self.references.search(self.image,args['k'])
            identifier='references:selected-image'
            payload={'status':'ok','evidence_id':identifier,'matches':result['matches'],
                     'note':result['note']}
            self.evidence[identifier]={'id':identifier,'kind':'image_references','title':'本次正常參考圖搜尋',
                                       'matches':result['matches'],'note':result['note']}
        elif name=='analyze_image':
            destination=self.output/'analysis'
            completed=subprocess.run([sys.executable,str(self.root/'scripts/predict_image.py'),
                str(self.image),'--output',str(destination)],cwd=self.root,capture_output=True,text=True,timeout=90)
            if completed.returncode!=0:
                return {'status':'error','error':'analysis_failed'}
            result=json.loads((destination/'result.json').read_text())
            identifier='analysis:selected-image'
            payload={'status':'ok','evidence_id':identifier,'score':result['score'],
                     'threshold':result['threshold'],'is_anomalous':result['is_anomalous'],
                     'checkpoint_sha256':result['checkpoint_sha256'],'supported_category':'bottle',
                     'note':result['note']}
            self.evidence[identifier]={'id':identifier,'kind':'analysis','title':'本次圖片分析',
                                       **{k:v for k,v in payload.items() if k not in ['status','evidence_id']},
                                       'heatmap_path':str(destination.relative_to(self.root)/'heatmap.png')}
        else:
            return {'status':'error','error':'unknown_tool'}
        self.cache[key]=payload
        return payload

    def close(self):
        for service in [self.documents,self.references]:
            if service:
                service.worker.close()
