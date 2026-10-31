"""Check credentials without printing them, optionally query model availability."""
import argparse
from pathlib import Path
import sys
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.groq_provider import GroqProvider,ProviderError,load_config,load_key


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online',action='store_true')
    args=parser.parse_args()
    provider=None
    try:
        load_key(ROOT)
        result={'credential_present':True}
        if args.online:
            config=load_config(ROOT)
            provider=GroqProvider(ROOT,config)
            try:
                models=provider.client.models.list()
            except Exception:
                raise ProviderError('model_availability_check_failed') from None
            available=any(model.id==config['model'] for model in models.data)
            result.update(model=config['model'],model_available=available,
                          billing_tier_verified=False,
                          note='模型清單 API 不提供帳號計費方案的驗證結果。')
            if not available:
                print(json.dumps(result,ensure_ascii=False))
                return 2
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except ProviderError as exc:
        print(json.dumps({'status':'configuration_error','error':exc.code}))
        return 2
    finally:
        if provider:
            provider.close()


if __name__=='__main__':
    raise SystemExit(main())
