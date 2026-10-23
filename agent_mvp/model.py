"""Configurable OpenAI-compatible image+function-calling adapter. No implicit mock fallback."""
import os,time,re
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from dotenv import load_dotenv
from . import PROJECT
class ModelNotConfigured(RuntimeError):pass
class ModelFailure(RuntimeError):pass
@dataclass
class Config:
 base_url:str='https://api.openai.com/v1'
 model:str=''
 api_key:str=''
 timeout:float=90
 max_tokens:int=2000
 token_limit_field:str='max_completion_tokens'
 enable_thinking:bool|None=None
 @classmethod
 def load(cls):
  load_dotenv(PROJECT/'.env',override=False)
  thinking=os.getenv('MODEL_ENABLE_THINKING','').strip().lower()
  if thinking not in ['', 'true','false']:raise ModelFailure('MODEL_ENABLE_THINKING must be blank, true or false')
  return cls(os.getenv('MODEL_BASE_URL','https://api.openai.com/v1'),os.getenv('MODEL_NAME',''),os.getenv('MODEL_API_KEY',''),float(os.getenv('MODEL_TIMEOUT_SECONDS','90')),int(os.getenv('MODEL_MAX_TOKENS','2000')),os.getenv('MODEL_TOKEN_LIMIT_FIELD','max_completion_tokens'),None if not thinking else thinking=='true')
class VisionModel:
 kind='live_model'
 def __init__(self,config=None,transport=None):self.config=config or Config.load();self.transport=transport;self.kind='offline_http_contract' if transport is not None else 'live_model'
 @property
 def configured(self):return bool(self.config.model and self.config.api_key)
 def complete(self,messages,tools):
  cfg=self.config
  if not self.configured:raise ModelNotConfigured('Set MODEL_NAME, MODEL_API_KEY and MODEL_BASE_URL in local .env; live validation not performed.')
  if cfg.token_limit_field not in ['max_tokens','max_completion_tokens']:raise ModelFailure('unsupported token limit field')
  parsed=urlparse(cfg.base_url)
  if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ['localhost','127.0.0.1','::1']):raise ModelFailure('HTTPS required except local loopback')
  payload={'model':cfg.model,'messages':messages,'tools':tools,'tool_choice':'auto',cfg.token_limit_field:cfg.max_tokens};start=time.monotonic()
  if cfg.enable_thinking is not None:payload['enable_thinking']=cfg.enable_thinking
  try:
   with httpx.Client(timeout=cfg.timeout,transport=self.transport,follow_redirects=False) as client:
    response=client.post(cfg.base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg.api_key},json=payload)
   if response.status_code!=200:
    try:err=response.json().get('error',{});detail=str(err.get('message',err.get('code','provider error')))
    except (ValueError,AttributeError):detail='non-JSON provider error'
    detail=detail.replace(cfg.api_key,'[REDACTED]');detail=re.sub(r'sk-[A-Za-z0-9_-]{12,}','[REDACTED]',detail)
    raise ModelFailure('Model HTTP '+str(response.status_code)+': '+detail[:500])
   data=response.json();message=data['choices'][0]['message']
   if not isinstance(message,dict) or message.get('role')!='assistant':raise ValueError('invalid assistant response')
   return {'message':{k:message[k] for k in ['role','content','tool_calls'] if k in message},'usage':data.get('usage'),'duration_seconds':time.monotonic()-start,'model':data.get('model',cfg.model),'request_id':response.headers.get('x-request-id'),'kind':self.kind}
  except (httpx.HTTPError,KeyError,ValueError,TypeError,IndexError,AttributeError) as e:raise ModelFailure('Model transport/schema failure: '+type(e).__name__) from None
