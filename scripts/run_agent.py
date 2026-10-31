"""Run the first Groq-backed inspection agent from the project root."""
import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.agent_runtime import AgentRunner
from app.groq_provider import GroqProvider,ProviderError,load_config
from app.inspection_tools import LocalTools


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question')
    parser.add_argument('--image',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    destination=(args.output or ROOT/'artifacts/agent_runs'/uuid.uuid4().hex[:12]).resolve()
    try:
        destination.relative_to(ROOT/'artifacts')
    except ValueError:
        parser.error('輸出需位於專案 artifacts/ 之下')
    if destination.exists():
        parser.error('輸出資料夾已存在，請指定新位置')
    tools=None
    provider=None
    try:
        config=load_config(ROOT)
        provider=GroqProvider(ROOT,config)
        tools=LocalTools(ROOT,destination,args.image)
        prompt=(ROOT/'prompts'/(config['prompt_version'].replace('-','_')+'.txt')).read_text()
        result=AgentRunner(provider,tools,config,prompt).run(args.question,bool(args.image))
        (destination/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        lines=['# 代理回答與工具紀錄','',f"執行狀態（Run Status），`{result['status']}`。",'']
        if result['answer']:
            for claim in result['answer']['claims']:
                lines.append('- '+claim['text']+' ['+', '.join(claim['evidence_ids'])+']')
            lines.extend(['','## 限制',''])
            lines.extend('- '+item for item in result['answer']['limitations'])
            if result['answer'].get('follow_up_question'):
                lines.extend(['','## 需要補充的資訊','',result['answer']['follow_up_question']])
        if result['error']:
            lines.append('執行遇到限制，錯誤碼為 `'+result['error']+'`。')
        lines.extend(['','## 資料來源',''])
        for citation in result['citations']:
            url=citation.get('source_url')
            reference=f"[{citation['title']}]({url})" if url else citation['title']
            lines.append('- `'+citation['id']+'`，'+reference+'。')
        lines.extend(['','## 工具執行順序',''])
        for entry in result['tool_trace']:
            lines.append(f"- 第 {entry['step']} 步，`{entry['tool']}` → `{entry['status']}`。")
        lines.extend(['','## 驗證範圍','',
                      '本版檢查引用編號與工具流程，回答內容仍需核對來源，語意支持度尚未自動驗證。'])
        (destination/'answer.md').write_text('\n'.join(lines)+'\n')
        print(json.dumps({'status':result['status'],'api_calls':result['api_calls'],
                          'tool_calls':result['tool_calls'],'error':result['error'],
                          'result_path':str(destination.relative_to(ROOT)/'result.json'),
                          'answer_path':str(destination.relative_to(ROOT)/'answer.md')},ensure_ascii=False,indent=2))
        return 0 if result['answer'] else 2
    except ProviderError as exc:
        print(json.dumps({'status':'provider_error','error':exc.code},ensure_ascii=False))
        return 2
    except (ValueError,FileNotFoundError):
        print(json.dumps({'status':'configuration_or_input_error','error':'check_input_and_local_setup'}))
        return 2
    finally:
        if tools:
            tools.close()
        if provider:
            provider.close()


if __name__=='__main__':
    raise SystemExit(main())
