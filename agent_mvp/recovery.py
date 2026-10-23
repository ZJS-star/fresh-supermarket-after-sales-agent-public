"""Trusted host journal recovery for inputs recorded before a crash but not yet in the state snapshot."""
import argparse,hashlib,json,datetime as dt
from .runtime import Run,RUN_ROOT
from .media import parts

def recover_customer_journal(run):
 events=[json.loads(l) for l in (run.directory/'events.jsonl').read_text().splitlines()];customers=[e for e in events if e['role']=='customer'];missing=customers[len(run.state['customer_claims']):]
 for e in missing:
  event_time=e.get('scenario_time',run.state['current_time'])
  if dt.datetime.fromisoformat(event_time)>dt.datetime.fromisoformat(run.state['current_time']):
   run.state['current_time']=event_time;run.session.now=event_time;run.control.expire_appointments(event_time)
  text=e.get('response',{}).get('message') or e.get('text','');content=[{'type':'text','text':text}]
  for a in e.get('response',{}).get('attachments',[]):
   if any(m['media_id']==a['media_id'] for m in run.state['media']):continue
   files=list((run.directory/'submitted').glob(a['media_id']+'.*'))
   if len(files)!=1:raise ValueError('cannot safely recover submitted media handle')
   with run.session.db() as c:record=c.execute('SELECT body FROM submitted_media WHERE actor_id=? AND media_id=?',(run.session.actor,a['media_id'])).fetchone()
   if not record:raise ValueError('submission not in trusted registry')
   m=json.loads(record['body']);m.update(local_path=str(files[0].relative_to(run.directory)),sha256=hashlib.sha256(files[0].read_bytes()).hexdigest());p,_=parts(m,run.directory);run.state['media'].append(m);content+=p
  run.state['customer_claims'].append({'text':text,'source':'customer_journal_recovery','source_event_sequence':e['sequence']});run.state['messages'].append({'role':'user','content':content});run.log({'role':'host','action':'recovered_customer_event','source_sequence':e['sequence']})
 if missing:
  run.state['turn']=len(customers)
  with run.session.db() as c:current=c.execute('SELECT desired FROM customer_state WHERE actor_id=?',(run.session.actor,)).fetchone()
  if current:run.state['current_customer_intent']=current['desired']
  run.state['messages'].append({'role':'system','content':'宿主已恢复崩溃前实际收到的顾客消息。数据库可能已经撤销旧方案的同意，请读取真实方案状态。若旧版本失效，重新提案并获得新版本确认；不得沿用旧同意。'})
  run.state['status']='ready';run.snapshot_final();run.save()
 return len(missing)
if __name__=='__main__':
 import re
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--auto-rounds',type=int,default=0);args=p.parse_args()
 if not re.fullmatch(r'[a-f0-9]{32}',args.run_id):raise ValueError('invalid run id')
 run=Run(RUN_ROOT/args.run_id)
 try:
  restored=recover_customer_journal(run);print('Recovered actual customer journal events:',restored,flush=True)
  if args.auto_rounds:
   run.advance()
   for _ in range(args.auto_rounds):
    if run.state['status'] in ['pending_review','human_takeover','model_error','step_limit']:break
    run.simulate_reply()
  print(json.dumps({'run_id':run.run_id,'state':run.state['status'],'trace':str(run.export())},ensure_ascii=False),flush=True)
 finally:run.close()
