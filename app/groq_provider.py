"""Fixed-endpoint Groq transport with redacted errors and no retries."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re


class ProviderError(RuntimeError):
    def __init__(self,code,status=None):
        self.code=code
        self.status=status
        super().__init__(code)


def load_key(root:Path):
    value=os.environ.get('GROQ_API_KEY','').strip()
    if not value:
        path=root/'.env.local'
        if path.is_file() and not path.is_symlink():
            for line in path.read_text().splitlines():
                match=re.match(r'^\s*GROQ_API_KEY\s*=\s*(.*?)\s*$',line)
                if match:
                    value=match.group(1).strip().strip('\"\'')
    if not value or not value.startswith('gsk_') or any(c.isspace() for c in value):
        raise ProviderError('credential_not_configured')
    return value


def load_config(root:Path):
    config=json.loads((root/'configs/agent.json').read_text())
    if config['provider']!='groq' or config['plan_expectation']!='free':
        raise ProviderError('unsupported_provider_or_plan')
    # Explicitly pin one documented Free Plan model, never auto-fallback.
    if config['model']!='qwen/qwen3.8-27b' or config['allowed_models']!=['qwen/qwen3.8-27b']:
        raise ProviderError('model_not_allowlisted')
    if not (1<=config['max_api_calls']<=5 and 1<=config['max_tool_calls']<=8):
        raise ProviderError('invalid_call_budget')
    if config['sdk_retries']!=0:
        raise ProviderError('automatic_retries_disabled')
    return config


class GroqProvider:
    def __init__(self,root:Path,config:dict):
        from groq import Groq
        self.config=config
        self.client=Groq(api_key=load_key(root),base_url='https://api.groq.com',
                         timeout=config['timeout_seconds'],max_retries=0)

    def complete(self,messages,tools):
        import groq
        try:
            response=self.client.chat.completions.create(
                model=self.config['model'],messages=messages,tools=tools,
                tool_choice='required',parallel_tool_calls=True,
                temperature=self.config['temperature'],
                max_completion_tokens=self.config['max_completion_tokens'])
        except groq.RateLimitError:
            raise ProviderError('rate_limited',429) from None
        except groq.AuthenticationError:
            raise ProviderError('authentication_failed',401) from None
        except groq.PermissionDeniedError:
            raise ProviderError('permission_denied',403) from None
        except groq.APITimeoutError:
            raise ProviderError('provider_timeout') from None
        except groq.APIConnectionError:
            raise ProviderError('provider_connection_error') from None
        except groq.APIStatusError as exc:
            raise ProviderError('provider_request_failed',exc.status_code) from None
        message=response.choices[0].message
        return {'message':message.model_dump(exclude_none=True),
                'usage':response.usage.model_dump() if response.usage else {},
                'model':response.model,'finish_reason':response.choices[0].finish_reason}

    def close(self):
        self.client.close()
