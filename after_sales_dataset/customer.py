"""Fact-constrained customer, durable state and version-specific consent. Never imports oracle."""
import copy,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class CustomerReplay:
 def __init__(self,case_id,root=ROOT,state_path=None):
  if not re.fullmatch(r'C\d{4}',case_id):raise ValueError('invalid case id')
  self.root=Path(root);self.case_id=case_id;self.state_path=Path(state_path) if state_path else None
  self.data=json.loads((self.root/'customer_private'/f'{case_id}.json').read_text());initial=json.loads((self.root/'agent_visible'/f'{case_id}.json').read_text())
  self.state=copy.deepcopy(self.data['facts']);self.state['current_time']=initial['current_time'];self.turn=0;self.asked=[];self.sent={x['media_id'] for x in initial['attachments']};self.events_sent=set();self.proposal=None;self.consents={}
  if self.state_path and self.state_path.exists():self.load(self.state_path)
 def save(self,path=None):
  path=Path(path or self.state_path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'case_id':self.case_id,'state':self.state,'turn':self.turn,'asked':self.asked,'sent':sorted(self.sent),'events_sent':sorted(self.events_sent),'proposal':self.proposal,'consents':self.consents},ensure_ascii=False,indent=2));tmp.replace(path)
 def load(self,path):
  d=json.loads(Path(path).read_text())
  if d['case_id']!=self.case_id:raise ValueError('customer state belongs to another case')
  self.state=d['state'];self.turn=d['turn'];self.asked=d['asked'];self.sent=set(d['sent']);self.events_sent=set(d['events_sent']);self.proposal=d['proposal'];self.consents=d['consents']
 def offer(self,proposal):
  if not proposal.get('proposal_id') or proposal.get('plan') not in ['refund_proposal','exchange_proposal','store_inspection']:raise ValueError('explicit proposal_id and plan required')
  if self.proposal and self.proposal!=proposal:self.consents.clear()
  self.proposal=copy.deepcopy(proposal)
 def reply(self,question,proposal=None):
  self.turn+=1;events=[];media=[]
  if proposal:self.offer(proposal)
  def add_media(items):
   for a in items:
    if a['media_id'] not in self.sent:media.append(a);self.sent.add(a['media_id'])
  for idx,e in enumerate(self.data.get('events',[])):
   if self.turn>=e['after_turn'] and idx not in self.events_sent:
    self.events_sent.add(idx);events.append(copy.deepcopy(e));self.state.update(e.get('updates',{}))
    if 'advance_to' in e:
     self.state['current_time']=e['advance_to']
     import datetime as dt
     if self.proposal and self.proposal.get('terms',{}).get('appointment_time') and dt.datetime.fromisoformat(self.proposal['terms']['appointment_time'])<dt.datetime.fromisoformat(e['advance_to']):self.proposal=None;self.consents.clear()
     if self.state.get('visit_time') not in [None,'unknown'] and dt.datetime.fromisoformat(self.state['visit_time'])<dt.datetime.fromisoformat(e['advance_to']):self.state['visit_time']='unknown'
    if e.get('updates'):self.consents.clear();self.proposal=None
    add_media(e.get('attachments',[]))
  matches=[t for t in self.data['triggers'] if any(k.lower() in question.lower() for k in t['keywords']) and (t['intent']!='unavailable' or (any(k in question for k in ['您能','你能','能否','是否愿意','是否可以','能不能']) and any(k in question for k in ['提供','补充','补材料','拍摄'])))];text=[];intents=[];repeat=0
  for t in matches:
   intent=t['intent'];repeat+=intent in self.asked;self.asked.append(intent);intents.append(intent)
   if intent=='preference' and not proposal and any(x in question for x in ['到店检查','门店查验','店内检查','store_inspection']) and any(x in question for x in ['同意','接受','倾向','愿意','选择']) and 'store_inspection' in self.state['acceptable_alternatives']:text.append('我可以考虑到店检查。请先给出具体待审方案和安排，再由我确认；这还不是对具体退款金额的同意。')
   elif intent=='preference' and not proposal and any(x in question for x in ['转人工','人工接管']) and 'human_takeover' in self.state['acceptable_alternatives']:text.append('我接受人工协助，请汇总现有材料建好工单后交店员核实。')
   elif intent=='preference':text.append({'refund':'希望先评估退款；这不是同意具体金额。','exchange':'希望换货；缺货可考虑其他方案，请先给出具体内容。','store_inspection':'我现在希望先到店检查，退款和换货需要重新商量。'}.get(self.state['desired'],'还需协商具体方案。'))
   elif intent=='visit':text.append('之前的到店时间已过，需要重新约时间。' if self.state['visit_time']=='unknown' else '方便到店时间：'+self.state['visit_time'])
   else:text.append(t['answer'])
   add_media(t.get('attachments',[]))
  consent=None
  if proposal and self.proposal and any(k in question for k in ['同意','确认方案','接受','可以按','agree','confirm']):
   plan=self.proposal['plan'];wanted={'refund':'refund_proposal','exchange':'exchange_proposal','store_inspection':'store_inspection'}[self.state['desired']];allowed=plan==wanted or plan=='store_inspection' or (plan=='refund_proposal' and 'refund_proposal_with_consent' in self.state['acceptable_alternatives'])
   if allowed:self.state['desired']={'refund_proposal':'refund','exchange_proposal':'exchange','store_inspection':'store_inspection'}[plan]
   consent={'proposal_id':self.proposal['proposal_id'],'agree':allowed,'proposal':copy.deepcopy(self.proposal)};self.consents[self.proposal['proposal_id']]=consent;text.append('同意这项待店员审核的具体方案。' if allowed else '不同意这项方案，请按我现在的诉求修改。');intents.append('proposal_consent')
  if not text:text=[self.data['fallback']]
  text.extend(e['message'] for e in events)
  result={'message':' '.join(text),'attachments':media,'turn':self.turn,'matched_intents':intents,'repeat_count':repeat,'events':events,'consent':consent,'current_time':self.state['current_time']}
  if self.state_path:self.save()
  return result
if __name__=='__main__':
 import sys
 sim=CustomerReplay(sys.argv[1])
 for q in sys.stdin:print(json.dumps(sim.reply(q.strip()),ensure_ascii=False),flush=True)
