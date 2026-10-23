"""Real-model dev validation runner. Missing configuration never falls back to fixtures."""
import argparse,concurrent.futures,json
from pathlib import Path
from . import DATA
from .model import VisionModel
from .runtime import Run

def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=DATA/'splits/live_validation_dev.json');p.add_argument('--limit',type=int,default=8);p.add_argument('--max-rounds',type=int,default=8);p.add_argument('--workers',type=int,choices=[1,2,3],default=1);p.add_argument('--output',type=Path,default=DATA/'reports/live_model_validation.json');args=p.parse_args();model=VisionModel();cases=json.loads(args.manifest.read_text())['cases'][:args.limit];report={'kind':'real_model_validation','model':model.config.model or None,'endpoint':model.config.base_url,'status':'not_run','reason':None,'cases':[],'semantic_review':'pending','success_rate':None}
 def write():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 if not model.configured:
  report['reason']='MODEL_NAME/MODEL_API_KEY missing; no requests sent';report['planned_cases']=cases;write();print(json.dumps({'status':report['status'],'reason':report['reason']},ensure_ascii=False));return
 def execute(entry):
  run=Run.create(entry['case_id'],model=VisionModel())
  try:
   run.advance()
   for _ in range(args.max_rounds):
    if run.state['status'] in ['pending_review','human_takeover','model_error','model_unconfigured','step_limit']:break
    run.simulate_reply()
   trace=run.export();return {**entry,'run_id':run.run_id,'state':run.state['status'],'model_attempts':run.state.get('model_attempts',0),'successful_model_responses':run.state['model_calls'],'runtime_seconds':run.state['model_seconds'],'model_usage':run.state['model_usage'] or None,'failure_reason':run.state.get('last_error'),'trace':str(trace.relative_to(DATA))}
  except Exception as exc:
   run.state['status']='host_error';run.state['last_error']=type(exc).__name__+': '+str(exc)[:300];run.log({'role':'host','action':'host_error','error':run.state['last_error']});trace=run.export();return {**entry,'run_id':run.run_id,'state':'host_error','model_attempts':run.state.get('model_attempts',0),'successful_model_responses':run.state['model_calls'],'runtime_seconds':run.state['model_seconds'],'model_usage':run.state['model_usage'] or None,'failure_reason':run.state['last_error'],'trace':str(trace.relative_to(DATA))}
  finally:run.close()
 report['status']='running';write()
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(execute,e):e for e in cases}
  for future in concurrent.futures.as_completed(futures):
   entry=futures[future]
   try:result=future.result()
   except Exception as exc:result={**entry,'state':'host_error','failure_reason':type(exc).__name__+': '+str(exc)[:300]}
   report['cases'].append(result);write();print(json.dumps({k:v for k,v in result.items() if k not in ['model_usage','trace']},ensure_ascii=False),flush=True)
 report['status']='captured_pending_deterministic_and_human_review';report['cases'].sort(key=lambda c:c['case_id']);write();print(json.dumps({'status':report['status'],'captured_cases':len(report['cases']),'output':str(args.output)},ensure_ascii=False))
if __name__=='__main__':main()
