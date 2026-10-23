"""Local FastAPI customer/staff MVP. Separate per-run capabilities; single uvicorn worker."""
import hmac,json,re,threading,uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,HTTPException,Header,UploadFile,File,Form
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field
from . import DATA
from .runtime import Run,RUN_ROOT
from .schemas import Body
from .media import ALLOWED,MAX_MEDIA_BYTES
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class NewRun(Strict):case_id:str
class Message(Strict):
 text:str=Field(min_length=1,max_length=10000)
 desired:Literal['refund','exchange','store_inspection','unknown']|None=None
 proposal_id:str|None=None
 agree:bool|None=None
 current_time:str|None=None
class StaffAction(Strict):
 action:Literal['confirm_stock','approve_refund','approve_exchange','confirm_inspection','takeover','cancel','close_manual','submit_review']
 proposal_id:str|None=None
class Modify(Strict):
 body:Body
 quantity:int=Field(0,ge=0)
 amount_cents:int=Field(0,ge=0)
class StaffMessage(Strict):text:str=Field(min_length=1,max_length=10000)

def create_app(run_root=RUN_ROOT,model_factory=None):
 registry={};lock=threading.RLock();run_root=Path(run_root)
 @asynccontextmanager
 async def lifespan(app):
  yield
  if hasattr(app.state,'demo_jobs'):app.state.demo_jobs.close()
  for run in registry.values():run.close()
 app=FastAPI(title='生鲜售后 Agent · 本地模拟',lifespan=lifespan)
 def get(run_id,authorization,staff=False):
  if not re.fullmatch(r'[a-f0-9]{32}',run_id):raise HTTPException(404,'run not found')
  with lock:
   if run_id not in registry:
    if not (run_root/run_id/'meta.json').is_file():raise HTTPException(404,'run not found')
    registry[run_id]=Run(run_root/run_id,model_factory() if model_factory else None)
   run=registry[run_id]
  token=(authorization or '').removeprefix('Bearer ');expected=run.meta['staff_token' if staff else 'customer_token']
  if not hmac.compare_digest(token,expected):raise HTTPException(403,'invalid role capability')
  return run
 @app.exception_handler(ValueError)
 async def value_error(request,exc):
  from fastapi.responses import JSONResponse
  return JSONResponse(status_code=422,content={'detail':str(exc)[:400]})
 @app.get('/health')
 def health():return {'ok':True,'simulation_only':True}
 @app.get('/dev-console')
 def customer_page():return FileResponse(Path(__file__).parent/'static/index.html')
 @app.get('/dev-staff')
 def staff_page():return FileResponse(Path(__file__).parent/'static/index.html')
 @app.get('/api/cases')
 def cases():return {'dev':json.loads((DATA/'splits/dev.json').read_text()),'smoke':json.loads((DATA/'splits/smoke.json').read_text())}
 @app.post('/api/runs')
 def new_run(data:NewRun):
  run=Run.create(data.case_id,run_root,model_factory() if model_factory else None)
  with lock:registry[run.run_id]=run
  return {'run_id':run.run_id,'customer_token':run.meta['customer_token'],'state':run.public()}
 @app.get('/api/runs/{run_id}')
 def state(run_id:str,authorization:str|None=Header(None)):return get(run_id,authorization).public()
 @app.post('/api/runs/{run_id}/advance')
 def advance(run_id:str,authorization:str|None=Header(None)):return get(run_id,authorization).advance()
 @app.post('/api/runs/{run_id}/messages')
 def message(run_id:str,data:Message,authorization:str|None=Header(None)):
  run=get(run_id,authorization);consent=None
  if data.proposal_id is not None and data.agree is not None:consent={'proposal_id':data.proposal_id,'agree':data.agree}
  return run.receive(data.text,desired=data.desired,consent=consent,current_time=data.current_time)
 @app.post('/api/runs/{run_id}/media')
 def upload(run_id:str,file:UploadFile=File(...),kind:Literal['image','receipt','video']=Form('image'),authorization:str|None=Header(None)):
  run=get(run_id,authorization);suffix=Path(file.filename or '').suffix.lower()
  if suffix not in ALLOWED:raise HTTPException(415,'supported: jpg/png/webp/mp4/mov')
  raw=file.file.read(MAX_MEDIA_BYTES+1)
  if len(raw)>MAX_MEDIA_BYTES:raise HTTPException(413,'25 MiB limit')
  staging=run.directory/'uploads';staging.mkdir(exist_ok=True);p=staging/(uuid.uuid4().hex+suffix);p.write_bytes(raw)
  try:return run.receive('补充材料',[{'path':str(p),'kind':'video' if suffix in ['.mp4','.mov'] else kind}])
  finally:p.unlink(missing_ok=True)
 @app.get('/api/runs/{run_id}/media/{media_id}')
 def media(run_id:str,media_id:str,authorization:str|None=Header(None)):
  # Either role can inspect only already-submitted media.
  try:run=get(run_id,authorization)
  except HTTPException as e:
   if e.status_code!=403:raise
   run=get(run_id,authorization,True)
  record=next((m for m in run.state['media'] if m['media_id']==media_id),None)
  if not record:raise HTTPException(404,'media not submitted')
  return FileResponse(run.directory/record['local_path'])
 @app.get('/api/runs/{run_id}/staff')
 def staff_state(run_id:str,authorization:str|None=Header(None)):return get(run_id,authorization,True).public(staff=True)
 @app.post('/api/runs/{run_id}/staff/actions')
 def staff_action(run_id:str,data:StaffAction,authorization:str|None=Header(None)):
  run=get(run_id,authorization,True);result=run.staff(data.action,data.proposal_id);return {'result':result,'state':run.public(True)}
 @app.post('/api/runs/{run_id}/staff/proposal')
 def staff_modify(run_id:str,data:Modify,authorization:str|None=Header(None)):
  run=get(run_id,authorization,True);run.staff_modify(data.body.model_dump(exclude_none=True),data.quantity,data.amount_cents);return run.public(True)
 @app.post('/api/runs/{run_id}/staff/messages')
 def staff_message(run_id:str,data:StaffMessage,authorization:str|None=Header(None)):
  run=get(run_id,authorization,True);run.staff_message(data.text);return run.public(True)
 @app.get('/api/runs/{run_id}/trace')
 def trace(run_id:str,authorization:str|None=Header(None)):
  run=get(run_id,authorization,True);return FileResponse(run.export(),filename='trace.jsonl',media_type='application/x-ndjson')
 from .demo.api import attach
 from .demo.space import ROOT as DEMO_ROOT
 attach(app,DEMO_ROOT if run_root==RUN_ROOT else run_root.parent/'demo_spaces',model_factory)
 return app
app=create_app()
