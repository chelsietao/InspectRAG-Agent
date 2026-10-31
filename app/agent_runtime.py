"""Bounded tool-calling loop with citation-ID checks, not a semantic fact checker."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
from pydantic import ValidationError

from app.agent_schemas import FinalAnswer,SCHEMAS,tool_definitions
from app.groq_provider import ProviderError


class AgentRunner:
    def __init__(self,provider,tools,config,prompt):
        self.provider=provider
        self.tools=tools
        self.config=config
        self.prompt=prompt
        self.started=False

    def run(self,question:str,image_available:bool=False):
        if not question.strip() or len(question)>2000:
            raise ValueError('問題需為 1 至 2,000 字')
        if self.started:
            raise ValueError('每個 AgentRunner 僅能執行一輪，請建立新的執行個體')
        self.started=True
        for name in ['evidence','seen_chunks','cache']:
            state=getattr(self.tools,name,None)
            if isinstance(state,dict):
                state.clear()
        messages=[{'role':'system','content':self.prompt},
                  {'role':'user','content':json.dumps({'question':question,
                    'available_image_id':'selected-image' if image_available else None},ensure_ascii=False)}]
        trace=[]
        api_usage=[]
        tool_count=0
        api_count=0
        correction_count=0
        started=time.perf_counter()
        definitions=tool_definitions()

        def finish(status,answer=None,error=None):
            citations=[]
            if answer:
                ids=sorted({identifier for claim in answer['claims'] for identifier in claim['evidence_ids']})
                citations=[self.tools.evidence[identifier] for identifier in ids]
            return {'status':status,'answer':answer,'error':error,'citations':citations,
                    'validation':{'citation_ids_valid':True if answer else None,
                                  'semantic_support':'not_automatically_verified'},
                    'provider':self.config['provider'],'model':self.config['model'],
                    'prompt_version':self.config['prompt_version'],
                    'prompt_sha256':hashlib.sha256(self.prompt.encode()).hexdigest(),
                    'created_at_utc':datetime.now(timezone.utc).isoformat(),
                    'api_calls':api_count,'tool_calls':tool_count,'usage':api_usage,
                    'seconds':time.perf_counter()-started,'tool_trace':trace,
                    'limitations':['引用檢查只驗證本輪來源編號，主張與證據的語意一致性仍需人工審閱。',
                                   '程式不會升級付費方案，但無法透過模型 API 驗證帳號的計費層級。']}

        while api_count<self.config['max_api_calls']:
            context_chars=len(json.dumps(messages,ensure_ascii=False))+len(json.dumps(definitions,ensure_ascii=False))
            if context_chars>self.config['max_context_characters']:
                return finish('stopped',error='context_budget_exceeded')
            try:
                api_count+=1
                response=self.provider.complete(messages,definitions)
            except ProviderError as exc:
                return finish('rate_limited' if exc.code=='rate_limited' else 'provider_error',error=exc.code)
            api_usage.append({'call':api_count,'usage':response.get('usage',{}),
                              'returned_model':response.get('model'),
                              'finish_reason':response.get('finish_reason'),
                              'context_characters':context_chars})
            message=response['message']
            calls=message.get('tool_calls') or []
            if not calls:
                correction_count+=1
                if correction_count>1:
                    return finish('validation_error',error='structured_answer_required')
                messages.append({'role':'assistant','content':message.get('content') or ''})
                messages.append({'role':'user','content':'請透過 submit_answer 提交有依據的結構化結果。'})
                continue
            messages.append({key:message[key] for key in ['role','content','tool_calls'] if key in message})
            for call in calls:
                if tool_count>=self.config['max_tool_calls']:
                    return finish('stopped',error='tool_budget_exceeded')
                tool_count+=1
                function=call.get('function',{})
                name=function.get('name','')
                entry={'step':tool_count,'tool':name if name in SCHEMAS else 'unknown_tool',
                       'status':'started','seconds':None}
                trace.append(entry)
                tool_started=time.perf_counter()
                try:
                    raw=function.get('arguments','{}')
                    if not isinstance(raw,str) or len(raw)>8000:
                        raise ValueError('invalid_arguments')
                    arguments=json.loads(raw)
                    if name not in SCHEMAS:
                        raise ValueError('unknown_tool')
                    parsed=SCHEMAS[name].model_validate(arguments).model_dump()
                    if name=='submit_answer':
                        known=self.tools.evidence
                        unknown={identifier for claim in parsed['claims'] for identifier in claim['evidence_ids'] if identifier not in known}
                        if unknown:
                            raise ValueError('citation_not_in_current_run')
                        if parsed['status']=='answered' and not parsed['claims']:
                            raise ValueError('answer_without_evidence')
                        entry.update(status='succeeded',seconds=time.perf_counter()-tool_started)
                        return finish(parsed['status'],answer=parsed)
                    payload=self.tools.execute(name,parsed)
                    entry['status']='succeeded' if payload.get('status')=='ok' else payload.get('status','error')
                    entry['arguments']=parsed
                except (ValueError,ValidationError,KeyError,TypeError):
                    payload={'status':'error','error':'invalid_tool_or_arguments_or_citation',
                             'message':'請檢查工具欄位，引用只能使用本輪取得的 evidence_id。'}
                    entry['status']='invalid'
                    if name=='submit_answer':
                        correction_count+=1
                        if correction_count>1:
                            entry['seconds']=time.perf_counter()-tool_started
                            return finish('validation_error',error='invalid_final_answer')
                except Exception:
                    payload={'status':'error','error':'local_tool_failed'}
                    entry['status']='failed'
                entry['seconds']=time.perf_counter()-tool_started
                messages.append({'role':'tool','tool_call_id':call['id'],
                                 'content':json.dumps(payload,ensure_ascii=False)})
        return finish('stopped',error='api_call_budget_exceeded')
