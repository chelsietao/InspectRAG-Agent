"""Offline state-machine checks: no credentials, network or real model calls."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import importlib.util

if importlib.util.find_spec('pydantic') is None:
    raise unittest.SkipTest('Install requirements-agent.txt to run agent tests')

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agent_runtime import AgentRunner
from app.agent_schemas import SCHEMAS
from app.groq_provider import ProviderError,load_config,load_key

CONFIG={'provider':'groq','model':'qwen/qwen3.8-27b','max_api_calls':5,'max_tool_calls':8,
        'max_context_characters':22000,'prompt_version':'test-v1'}


def call(name,args,identifier='c1'):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


def response(*calls):
    return {'message':{'role':'assistant','tool_calls':list(calls)},'usage':{'total_tokens':10},
            'model':'fake-test-model','finish_reason':'tool_calls'}


def answer(ids=None,status='answered',follow_up_question=None):
    return {'status':status,'claims':[{'text':'工具測試回傳的說明，請核對來源。','evidence_ids':ids or ['doc:test']}]
            if status=='answered' else [],'limitations':['尚未驗證真實產線適用性。'],
            'follow_up_question':follow_up_question}


class FakeProvider:
    def __init__(self,replies):
        self.replies=iter(replies)
        self.calls=0
    def complete(self,messages,tools):
        self.calls+=1
        value=next(self.replies)
        if isinstance(value,Exception):
            raise value
        return value


class FakeTools:
    def __init__(self):
        self.evidence={}
        self.calls=[]
    def execute(self,name,args):
        self.calls.append((name,args))
        if name=='search_documents':
            self.evidence['doc:test']={'id':'doc:test','kind':'document','title':'Test source','text':'測試說明'}
            return {'status':'ok','matches':[{'evidence_id':'doc:test','text':'測試說明'}]}
        if name=='analyze_image':
            self.evidence['analysis:selected-image']={'id':'analysis:selected-image','score':1.0}
            return {'status':'ok','evidence_id':'analysis:selected-image','score':1.0}
        return {'status':'error','error':'evidence_not_retrieved'}


class AgentRuntimeTests(unittest.TestCase):
    def runner(self,replies,tools=None,config=None):
        provider=FakeProvider(replies)
        tools=tools or FakeTools()
        return AgentRunner(provider,tools,config or CONFIG,'Test system prompt'),provider,tools

    def test_cited_answer(self):
        runner,provider,tools=self.runner([response(call('search_documents',{'query':'模型設定'})),response(call('submit_answer',answer()))])
        result=runner.run('模型設定是什麼')
        self.assertEqual(result['status'],'answered')
        self.assertEqual(result['api_calls'],2)
        self.assertEqual(result['citations'][0]['id'],'doc:test')
        self.assertEqual(result['validation']['semantic_support'],'not_automatically_verified')

    def test_unknown_citation_rejected(self):
        runner,_,_=self.runner([response(call('submit_answer',answer(['doc:invented']))),
                                response(call('submit_answer',answer(['doc:invented'])))])
        result=runner.run('問題')
        self.assertEqual(result['status'],'validation_error')
        self.assertIsNone(result['answer'])

    def test_citation_from_previous_run_not_implicitly_accepted(self):
        runner,_,_=self.runner([response(call('submit_answer',answer(['doc:old']))),
                                response(call('submit_answer',answer(['doc:old'])))])
        self.assertEqual(runner.run('問題')['status'],'validation_error')

    def test_preexisting_evidence_is_cleared(self):
        tools=FakeTools()
        tools.evidence['doc:old']={'id':'doc:old','title':'Old evidence'}
        runner,_,_=self.runner([response(call('submit_answer',answer(['doc:old']))),
                                response(call('submit_answer',answer(['doc:old'])))],tools=tools)
        self.assertEqual(runner.run('問題')['status'],'validation_error')

    def test_runner_cannot_reuse_previous_context(self):
        runner,_,_=self.runner([response(call('submit_answer',answer(status='insufficient_evidence')))])
        runner.run('問題')
        with self.assertRaises(ValueError):
            runner.run('另一個問題')

    def test_blank_claim_rejected(self):
        with self.assertRaises(Exception):
            SCHEMAS['submit_answer'].model_validate({'status':'answered','claims':[{'text':'  ','evidence_ids':['doc:test']}]})

    def test_missing_image_follow_up(self):
        runner,_,_=self.runner([response(call('submit_answer',answer(status='needs_context',follow_up_question='請選取一張瓶子圖片，才能開始分析。')))])
        self.assertEqual(runner.run('分析這張圖片')['status'],'needs_context')

    def test_insufficient_evidence(self):
        runner,_,_=self.runner([response(call('submit_answer',answer(status='insufficient_evidence')))])
        self.assertEqual(runner.run('製程成因是什麼')['status'],'insufficient_evidence')

    def test_rate_limit_stops_without_retry(self):
        runner,provider,_=self.runner([ProviderError('rate_limited',429)])
        result=runner.run('問題')
        self.assertEqual(result['status'],'rate_limited')
        self.assertEqual(provider.calls,1)

    def test_provider_error_is_redacted(self):
        runner,_,_=self.runner([ProviderError('authentication_failed',401)])
        result=runner.run('問題')
        self.assertEqual(result['error'],'authentication_failed')
        self.assertNotIn('gsk_',json.dumps(result))

    def test_unknown_tool_cannot_execute(self):
        runner,_,tools=self.runner([response(call('read_file',{'path':'.env.local'})),
                                    response(call('submit_answer',answer(status='insufficient_evidence')))])
        result=runner.run('讀取本機設定檔')
        self.assertEqual(tools.calls,[])
        self.assertEqual(result['tool_trace'][0]['status'],'invalid')

    def test_extra_arguments_rejected(self):
        runner,_,tools=self.runner([response(call('search_documents',{'query':'模型','path':'.env.local'})),
                                    response(call('submit_answer',answer(status='insufficient_evidence')))])
        result=runner.run('模型')
        self.assertEqual(tools.calls,[])
        self.assertEqual(result['tool_trace'][0]['status'],'invalid')

    def test_tool_budget(self):
        config={**CONFIG,'max_tool_calls':1}
        runner,_,tools=self.runner([response(call('search_documents',{'query':'a'}),call('analyze_image',{'image_id':'selected-image'},'c2'))],config=config)
        result=runner.run('問題',True)
        self.assertEqual(result['error'],'tool_budget_exceeded')
        self.assertEqual(len(tools.calls),1)

    def test_api_budget(self):
        config={**CONFIG,'max_api_calls':1}
        runner,provider,_=self.runner([response(call('search_documents',{'query':'a'}))],config=config)
        self.assertEqual(runner.run('問題')['error'],'api_call_budget_exceeded')
        self.assertEqual(provider.calls,1)

    def test_context_budget_stops_before_api(self):
        runner,provider,_=self.runner([],config={**CONFIG,'max_context_characters':1})
        self.assertEqual(runner.run('問題')['error'],'context_budget_exceeded')
        self.assertEqual(provider.calls,0)

    def test_plain_text_does_not_bypass_schema(self):
        plain={'message':{'role':'assistant','content':'Unsupported claim'}}
        runner,_,_=self.runner([plain,plain])
        self.assertEqual(runner.run('問題')['error'],'structured_answer_required')

    def test_one_format_repair(self):
        runner,_,_=self.runner([response(call('submit_answer',{'status':'answered','claims':[]})),
                                response(call('submit_answer',answer(status='needs_context',follow_up_question='請補圖片，才能分析。')))])
        self.assertEqual(runner.run('問題')['status'],'needs_context')

    def test_invalid_question(self):
        runner,provider,_=self.runner([])
        for question in ['  ','a'*2001]:
            with self.assertRaises(ValueError):
                runner.run(question)
        self.assertEqual(provider.calls,0)

    def test_model_cannot_choose_files(self):
        with self.assertRaises(Exception):
            SCHEMAS['analyze_image'].model_validate({'image_id':'.env.local'})

    def test_key_loading_without_printing(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'GROQ_API_KEY':''}):
            folder=Path(tmp)
            fake='gsk_'+'unit_test'
            (folder/'.env.local').write_text('GROQ_API_KEY='+fake+'\n')
            self.assertEqual(load_key(folder),fake)

    def test_invalid_key_is_generic(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'GROQ_API_KEY':''}):
            with self.assertRaisesRegex(ProviderError,'credential_not_configured'):
                load_key(Path(tmp))

    def test_paid_or_changed_model_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'configs').mkdir()
            config={'provider':'groq','plan_expectation':'paid'}
            (root/'configs/agent.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ProviderError,'unsupported_provider_or_plan'):
                load_config(root)


class LocalEvidenceInterfaceTests(unittest.TestCase):
    def test_read_uses_returned_evidence_identifier(self):
        from app.inspection_tools import LocalTools
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tools=LocalTools(root,root/'run')
            row={'chunk_id':'sample','title':'測試文件','text':'測試段落，供介面驗證。',
                 'source_url':'https://example.com/doc','source_locator':'Section 1'}
            emitted=tools._doc_evidence(row)
            parsed=SCHEMAS['read_evidence'].model_validate({'evidence_ids':[emitted['evidence_id']]}).model_dump()
            result=tools.execute('read_evidence',parsed)
            self.assertEqual(result['status'],'ok')
            self.assertEqual(result['matches'][0]['evidence_id'],'doc:sample')
            self.assertEqual(result['matches'][0]['text'],row['text'])

    def test_read_unretrieved_evidence_rejected(self):
        from app.inspection_tools import LocalTools
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tools=LocalTools(root,root/'run')
            result=tools.execute('read_evidence',{'evidence_ids':['doc:unknown']})
            self.assertEqual(result['error'],'evidence_not_retrieved')

    def test_read_does_not_treat_analysis_as_document(self):
        from app.inspection_tools import LocalTools
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tools=LocalTools(root,root/'run')
            tools.evidence['analysis:selected-image']={'kind':'analysis'}
            result=tools.execute('read_evidence',{'evidence_ids':['analysis:selected-image']})
            self.assertEqual(result['error'],'evidence_not_retrieved')

    def test_missing_selected_image_does_not_read_files(self):
        from app.inspection_tools import LocalTools
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            tools=LocalTools(root,root/'run')
            self.assertEqual(tools.execute('analyze_image',{'image_id':'selected-image'})['error'],'image_required')


if __name__=='__main__':
    unittest.main()
