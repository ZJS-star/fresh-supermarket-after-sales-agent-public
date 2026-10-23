"""python -m agent_mvp.cli --help"""
import argparse,json,re
from pathlib import Path
from .runtime import Run,RUN_ROOT
from .model import Config,VisionModel

def load_run(run_id):
 if not re.fullmatch(r'[a-f0-9]{32}',run_id):raise ValueError('invalid run_id')
 return Run(RUN_ROOT/run_id)
def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 start=sub.add_parser('run');start.add_argument('--case',required=True);start.add_argument('--auto',action='store_true');start.add_argument('--rounds',type=int,default=12);start.add_argument('--allow-test',action='store_true')
 resume=sub.add_parser('resume');resume.add_argument('--run-id',required=True);resume.add_argument('--auto',action='store_true');resume.add_argument('--rounds',type=int,default=12)
 export=sub.add_parser('export');export.add_argument('--run-id',required=True);export.add_argument('--output',type=Path)
 show=sub.add_parser('show');show.add_argument('--run-id',required=True)
 staff=sub.add_parser('staff');staff.add_argument('--run-id',required=True);staff.add_argument('--action',required=True,choices=['confirm_stock','approve_refund','approve_exchange','confirm_inspection','takeover','cancel','close_manual','submit_review']);staff.add_argument('--name',default='CLI_STAFF')
 access=sub.add_parser('access');access.add_argument('--run-id',required=True);access.add_argument('--role',choices=['customer','staff'],required=True)
 sub.add_parser('config-check');args=p.parse_args()
 if args.command=='config-check':
  cfg=Config.load();print(json.dumps({'configured':VisionModel(cfg).configured,'model':cfg.model or None,'endpoint_configured':bool(cfg.base_url),'real_model_validation':'not_performed_by_config_check'},ensure_ascii=False));return
 run=Run.create(args.case,allow_test=args.allow_test) if args.command=='run' else load_run(args.run_id)
 try:
  if args.command=='access':print(run.meta[args.role+'_token']);return
  if args.command=='export':print(run.export(args.output));return
  if args.command=='show':print(json.dumps(run.public(staff=True),ensure_ascii=False,indent=2));return
  if args.command=='staff':print(json.dumps(run.staff(args.action,staff=args.name),ensure_ascii=False));run.export();return
  result=run.advance();print('RUN_ID:',run.run_id)
  for _ in range(args.rounds):
   print(json.dumps(run.public(),ensure_ascii=False,indent=2))
   if run.state['handoff'] or run.state['status'] in ['pending_review','model_unconfigured','model_error','step_limit','refunded_simulated','exchanged_simulated','closed_manual','inspection_confirmed']:break
   if args.auto:result=run.simulate_reply();continue
   print('输入回复；/media 文件路径 补材料；/agree 或 /decline 确认当前方案；/pause 保存退出；/takeover 店员接管。')
   try:text=input('顾客> ').strip()
   except EOFError:break
   if text=='/pause':break
   if text=='/takeover':run.staff('takeover');break
   if text.startswith('/time '):run.receive('按新的模拟时间继续',current_time=text[6:].strip());continue
   if text.startswith('/media '):run.receive('补充材料',[{'path':text[7:].strip()}]);continue
   consent=None
   if text in ['/agree','/decline']:
    if not run.state['proposal_id']:print('当前无方案');continue
    consent={'proposal_id':run.state['proposal_id'],'agree':text=='/agree'}
   run.receive(text,consent=consent)
  print('轨迹:',run.export())
 finally:run.close()
if __name__=='__main__':main()
