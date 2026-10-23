"""Trusted local business broker. Never mount runtime/oracle/customer_private into Agent sandbox."""
import datetime as dt,hashlib,json,sqlite3
from pathlib import Path
from controls import setup, canonical, meaningful
ROOT=Path(__file__).resolve().parent
class ToolError(ValueError): pass
class ToolSession:
 def __init__(self,token,root=ROOT):
  self.root=Path(root)
  matches=[(cid,p) for cid,p in json.loads((self.root/'runtime/permissions.json').read_text()).items() if __import__('hmac').compare_digest(p['token'],token)]
  if len(matches)!=1:raise ToolError('invalid session credential')
  self.case_id,self.scope=matches[0];self.actor=self.scope['actor_id'];self.business_actor=self.scope.get('business_actor',self.actor);self.now=self.scope['now']
  with self.db() as c: setup(c)
 def db(self):
  c=sqlite3.connect(self.root/'runtime/business.sqlite3',timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
 def _order(self,c,order_id,require_synced=True):
  if order_id not in self.scope['orders']:raise ToolError('outside identity scope')
  o=c.execute('SELECT * FROM orders WHERE order_id=? AND actor_id=? AND store_id=?',(order_id,self.business_actor,self.scope['store_id'])).fetchone()
  if not o:raise ToolError('not found')
  if require_synced and not o['synced']:raise ToolError('not_yet_synced: manual verification required')
  return dict(o)
 def _item(self,c,item_id):
  i=c.execute('SELECT * FROM order_items WHERE item_id=?',(item_id,)).fetchone()
  if not i:raise ToolError('item not found')
  self._order(c,i['order_id']);return dict(i)
 def query_orders(self,purchased_date=None,category=None,paid_cents=None,receipt_ref=None):
  with self.db() as c:
   rows=c.execute('SELECT * FROM orders WHERE actor_id=? AND store_id=? ORDER BY purchased_at LIMIT 50',(self.business_actor,self.scope['store_id'])).fetchall();out=[];lag=False
   for row in rows:
    o=dict(row)
    if o['order_id'] not in self.scope['orders']:continue
    if not o['synced']:lag=True;continue
    if purchased_date and not o['purchased_at'].startswith(purchased_date):continue
    if paid_cents is not None and o['paid_cents']!=paid_cents:continue
    if receipt_ref and o['receipt_ref']!=receipt_ref:continue
    products=[dict(r) for r in c.execute('SELECT p.name,p.category,p.spec,i.unit,i.quantity FROM order_items i JOIN products p USING(sku) WHERE i.order_id=?',(o['order_id'],))]
    if category and not any(p['category']==category for p in products):continue
    out.append({k:o[k] for k in ['order_id','purchased_at','paid_cents','payment_method','receipt_ref']}|{'products':products})
   return {'candidates':out,'sync_status':'pending' if lag else 'available','ownership_verified':False,'fact_source':'synthetic_pos_seeded_business_state'}
 def get_order(self,order_id):
  with self.db() as c:return {'order':self._order(c,order_id),'items':[dict(r) for r in c.execute('SELECT i.*,p.name,p.spec FROM order_items i JOIN products p USING(sku) WHERE order_id=?',(order_id,))],'verification':'POS事实来自模拟业务设定；匹配顾客凭证仍需独立核对'}
 def _ledger(self,c,item_id,exclude_ticket=None):
  i=self._item(c,item_id)
  rows=c.execute("SELECT * FROM after_sales WHERE item_id=?",(item_id,)).fetchall()
  fq=sum(r['refunded_quantity'] for r in rows if r['status']=='refunded');fc=sum(r['refunded_cents'] for r in rows if r['status']=='refunded');eq=sum(r['refunded_quantity'] for r in rows if r['status']=='exchanged')+c.execute('SELECT COALESCE(SUM(exchanged_quantity),0) FROM exchanges WHERE item_id=?',(item_id,)).fetchone()[0]
  pending=c.execute("SELECT * FROM tickets WHERE item_id=? AND status='pending_review' AND ticket_id!=?",(item_id,exclude_ticket or '')).fetchall()
  rq=sum(t['quantity'] for t in pending);rc=sum(t['amount_cents'] for t in pending)
  return i,{'refunded_quantity':fq,'refunded_cents':fc,'exchanged_quantity':eq,'reserved_quantity':rq,'reserved_cents':rc,'reserved_refund_quantity':sum(t['quantity'] for t in pending if json.loads(t['body']).get('plan')=='refund_proposal')}
 def get_after_sales(self,item_id):
  with self.db() as c:
   i,l=self._ledger(c,item_id)
   return {'exchanges':[dict(r) for r in c.execute('SELECT * FROM exchanges WHERE item_id=?',(item_id,))],'history':[dict(r) for r in c.execute('SELECT * FROM after_sales WHERE item_id=?',(item_id,))],'tickets':[dict(r) for r in c.execute('SELECT ticket_id,status,quantity,amount_cents FROM tickets WHERE item_id=?',(item_id,))],'remaining_quantity':i['quantity']-l['refunded_quantity']-l['exchanged_quantity']-l['reserved_quantity'],'remaining_cents':i['paid_cents']-l['refunded_cents']-i['paid_cents']*l['exchanged_quantity']//i['quantity']-l['reserved_cents'],'unit':i['unit'],'paid_cents':i['paid_cents'],**l}
 def get_rules(self,sku=None,issue_type=None):
  if issue_type and issue_type not in json.loads((self.root/'config/store_rules.json').read_text())['issue_types']:raise ToolError('unknown issue type; hand off for rule interpretation')
  if sku:self.get_inventory(sku)
  with self.db() as c:return json.loads(c.execute('SELECT body FROM rules').fetchone()[0])
 def get_inventory(self,sku):
  with self.db() as c:
   # SKU allowed only if present in a session order, preventing arbitrary catalog enumeration.
   allowed=c.execute('SELECT 1 FROM order_items i JOIN orders o USING(order_id) WHERE o.actor_id=? AND i.sku=?',(self.business_actor,sku)).fetchone()
   if not allowed:raise ToolError('outside product scope')
   row=c.execute('SELECT * FROM inventory WHERE sku=?',(sku,)).fetchone()
   return dict(row)|{'stock_confirmation_required':True}
 def get_hours(self):
  with self.db() as c:return {'timezone':'Asia/Shanghai',**json.loads(c.execute('SELECT body FROM opening_hours WHERE store_id=?',(self.scope['store_id'],)).fetchone()[0]),'booking_requires_staff_confirmation':True}
 def _calculate(self,c,item_id,quantity,exclude_ticket=None):
  if type(quantity)!=int or quantity<=0:raise ToolError('positive integer quantity required')
  i,l=self._ledger(c,item_id,exclude_ticket)
  if quantity>i['quantity']-l['refunded_quantity']-l['exchanged_quantity']-l['reserved_quantity']:raise ToolError('quantity exceeds remaining allowance')
  consumed=i['paid_cents']*l['exchanged_quantity']//i['quantity']
  amount=i['paid_cents']*(l['refunded_quantity']+l['exchanged_quantity']+l['reserved_refund_quantity']+quantity)//i['quantity']-l['refunded_cents']-consumed-l['reserved_cents']
  remaining=i['paid_cents']-l['refunded_cents']-consumed-l['reserved_cents'];amount=max(0,min(amount,remaining))
  return {'item_id':item_id,'quantity':quantity,'unit':i['unit'],'suggested_cents':amount,'remaining_cents':remaining,'requires_review':True,'executed':False,'calculation':'integer cumulative paid allocation, excluding exchanged/reserved quantities'}
 def calculate_refund(self,item_id,quantity):
  with self.db() as c:return self._calculate(c,item_id,quantity)
 def create_ticket(self,item_id=None,body=None,request_key=None):
  body=body or {};key=request_key
  if not isinstance(key,str) or not key:raise ToolError('request_key required')
  # One active thread per customer and order item; an unresolved case uses case scope.
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE')
   if item_id:self._item(c,item_id)
   dedupe=self.actor+':'+(item_id or self.case_id);existing=c.execute('SELECT * FROM tickets WHERE dedupe_key=?',(dedupe,)).fetchone()
   op=c.execute('SELECT response FROM operations WHERE request_key=? AND actor_id=?',(self.actor+':'+key,self.actor)).fetchone()
   if op:return json.loads(op[0])
   if existing:return {'ticket_id':existing['ticket_id'],'deduplicated':True,'status':existing['status']}
   active=c.execute("SELECT * FROM tickets WHERE actor_id=? AND case_scope=? AND status NOT IN ('closed_manual','refunded_simulated','exchanged_simulated','inspection_confirmed','cancelled','resolved_no_refund') ORDER BY created_at LIMIT 1",(self.actor,self.case_id)).fetchone()
   if active:
    if item_id and active['item_id']!=item_id:raise ToolError('existing case ticket found; verify and bind_ticket_item, or seek staff for a different item')
    return {'ticket_id':active['ticket_id'],'deduplicated':True,'status':active['status']}
   tid='T'+hashlib.sha256(dedupe.encode()).hexdigest()[:14];c.execute('INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?)',(tid,self.actor,self.case_id,item_id,'awaiting_evidence',0,0,json.dumps(body,ensure_ascii=False),dedupe,self.now));result={'ticket_id':tid,'status':'awaiting_evidence','deduplicated':False};c.execute('INSERT INTO operations VALUES (?,?,?)',(self.actor+':'+key,self.actor,json.dumps(result)));c.execute('INSERT INTO audit(actor_id,action,object_id,body) VALUES (?,?,?,?)',(self.actor,'create_ticket',tid,json.dumps(body)));return result
 def get_ticket(self,ticket_id):
  with self.db() as c:
   r=c.execute('SELECT * FROM tickets WHERE ticket_id=? AND actor_id=?',(ticket_id,self.actor)).fetchone()
   if not r:raise ToolError('outside ticket scope')
   out=dict(r);out['body']=json.loads(out['body']);return out
 def bind_ticket_item(self,ticket_id,item_id,request_key=None):
  if not request_key:raise ToolError('request_key required')
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE');i=self._item(c,item_id);t=c.execute('SELECT * FROM tickets WHERE ticket_id=? AND actor_id=?',(ticket_id,self.actor)).fetchone()
   if not t:raise ToolError('outside ticket scope')
   if t['status'] in ['human_takeover','refunded_simulated','exchanged_simulated','closed_manual','inspection_confirmed']:raise ToolError('closed/manual ticket cannot be rebound')
   if t['item_id']==item_id:return {'ticket_id':ticket_id,'item_id':item_id,'deduplicated':True}
   if t['item_id']:raise ToolError('changing an existing binding requires staff review')
   if not c.execute('SELECT 1 FROM purchase_verifications WHERE actor_id=? AND item_id=?',(self.actor,item_id)).fetchone():raise ToolError('host purchase verification required before binding')
   body=json.loads(t['body']);pid=body.pop('proposal_id',None)
   if pid:c.execute("UPDATE proposals SET consent='superseded' WHERE proposal_id=?",(pid,))
   existing=c.execute('SELECT * FROM tickets WHERE dedupe_key=?',(self.actor+':'+item_id,)).fetchone()
   if existing:
    c.execute("UPDATE tickets SET status='cancelled',quantity=0,amount_cents=0 WHERE ticket_id=?",(ticket_id,));result={'ticket_id':existing['ticket_id'],'item_id':item_id,'merged_from':ticket_id,'deduplicated':True}
   else:
    c.execute("UPDATE tickets SET item_id=?,dedupe_key=?,status='awaiting_evidence',quantity=0,amount_cents=0,body=? WHERE ticket_id=?",(item_id,self.actor+':'+item_id,canonical(body),ticket_id));result={'ticket_id':ticket_id,'item_id':item_id,'deduplicated':False}
   c.execute('INSERT INTO audit(actor_id,action,object_id,body) VALUES (?,?,?,?)',(self.actor,'bind_ticket_item',ticket_id,canonical(result)));return result
 def update_ticket(self,ticket_id,body,status='awaiting_evidence',quantity=0,amount_cents=0,request_key=None):
  if status not in ['awaiting_evidence','awaiting_confirmation','pending_review','human_takeover','cancelled','resolved_no_refund']:raise ToolError('agent cannot execute completion')
  if not request_key:raise ToolError('request_key required')
  if type(quantity)!=int or type(amount_cents)!=int or quantity<0 or amount_cents<0:raise ToolError('integer nonnegative units required')
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE');t=c.execute('SELECT * FROM tickets WHERE ticket_id=? AND actor_id=?',(ticket_id,self.actor)).fetchone()
   if not t:raise ToolError('outside ticket scope')
   payload=canonical({'ticket_id':ticket_id,'body':body,'status':status,'quantity':quantity,'amount_cents':amount_cents})
   op=c.execute('SELECT response FROM operations WHERE request_key=? AND actor_id=?',(self.actor+':'+request_key,self.actor)).fetchone()
   if op:
    old=json.loads(op[0])
    if old.get('payload')!=payload:raise ToolError('idempotency key reused with different arguments')
    return old['result']
   if t['status'] in ['refunded_simulated','exchanged_simulated','closed_manual','inspection_confirmed']:raise ToolError('staff-closed ticket cannot be reopened')
   if t['status']=='human_takeover':raise ToolError('human owns this ticket; autonomous updates stopped')
   if status in ['pending_review','human_takeover','awaiting_confirmation']:
    if any(not meaningful(body.get(k)) for k in ['issue','next_action']):raise ToolError('nonempty issue/next_action required')
    if body.get('customer_preference') not in ['refund','exchange','store_inspection','unknown']:raise ToolError('explicit customer preference or unknown required')
    if not isinstance(body.get('uncertainties'),list) or any(not meaningful(x) for x in body['uncertainties']):raise ToolError('uncertainties must be a valid list (empty means none)')
    refs=body.get('evidence_refs')
    if not isinstance(refs,list):raise ToolError('evidence_refs list required')
    for e in refs:
     if not isinstance(e,dict) or not c.execute('SELECT 1 FROM submitted_media WHERE actor_id=? AND media_id=?',(self.actor,e.get('media_id'))).fetchone():raise ToolError('evidence not submitted to agent')
     media=json.loads(c.execute('SELECT body FROM submitted_media WHERE actor_id=? AND media_id=?',(self.actor,e['media_id'])).fetchone()[0])
     if 'time_seconds' in e and (media.get('kind')!='video' or type(e['time_seconds']) not in [int,float] or not 0<=e['time_seconds']<(media.get('duration_seconds') or 0)):raise ToolError('invalid video timestamp')
   if status=='human_takeover':
    if not meaningful(body.get('handoff_reason')):raise ToolError('specific handoff reason required')
   if status in ['pending_review','awaiting_confirmation']:
    plan=body.get('plan')
    if plan not in ['refund_proposal','exchange_proposal','store_inspection']:raise ToolError('explicit plan required')
    if plan!='store_inspection':
     if not t['item_id']:raise ToolError('bound item required')
     if not c.execute('SELECT 1 FROM purchase_verifications WHERE actor_id=? AND item_id=?',(self.actor,t['item_id'])).fetchone():raise ToolError('host purchase verification required; model boolean is not proof')
     if not body['evidence_refs']:raise ToolError('evidence required')
    if plan=='refund_proposal':
     calc=self._calculate(c,t['item_id'],quantity,ticket_id)
     if amount_cents!=calc['suggested_cents']:raise ToolError('refund must match integer suggestion')
    elif plan=='exchange_proposal':
     if amount_cents!=0 or quantity<=0:raise ToolError('exchange requires positive quantity and zero money')
     i,l=self._ledger(c,t['item_id'],ticket_id)
     if quantity>i['quantity']-l['refunded_quantity']-l['exchanged_quantity']-l['reserved_quantity']:raise ToolError('exchange quantity exceeds remaining')
     stock=c.execute('SELECT quantity FROM inventory WHERE sku=?',(i['sku'],)).fetchone()[0]
     if stock is not None and stock<quantity:raise ToolError('stock unavailable; ask alternative or manual')
    elif quantity or amount_cents:raise ToolError('inspection has no financial quantity or amount; use body inspection_quantity if known')
    proposal={'ticket_id':ticket_id,'item_id':t['item_id'],'plan':plan,'quantity':quantity,'amount_cents':amount_cents,'terms':{k:v for k,v in body.items() if k not in ['proposal_id','customer_consent','stock_confirmed','purchase_confirmed','quantity_confirmed']}}
    fingerprint_payload={**proposal,'terms':{k:v for k,v in proposal['terms'].items() if k!='customer_preference'}}
    fingerprint=hashlib.sha256(canonical(fingerprint_payload).encode()).hexdigest()
    previous=json.loads(t['body']).get('proposal_id');prev=c.execute('SELECT * FROM proposals WHERE proposal_id=?',(previous,)).fetchone()
    pid=previous if prev and prev['fingerprint']==fingerprint and prev['consent']!='superseded' else 'P'+hashlib.sha256((fingerprint+str(c.execute('SELECT COUNT(*) FROM proposals').fetchone()[0]+1)).encode()).hexdigest()[:20]
    if previous and previous!=pid:c.execute("UPDATE proposals SET consent='superseded' WHERE proposal_id=?",(previous,))
    c.execute('INSERT OR IGNORE INTO proposals(proposal_id,ticket_id,fingerprint,body) VALUES (?,?,?,?)',(pid,ticket_id,fingerprint,canonical(proposal)));p=c.execute('SELECT * FROM proposals WHERE proposal_id=?',(pid,)).fetchone();body={**body,'proposal_id':pid,'customer_consent':p['consent']=='agreed','stock_confirmed':p['staff_stock']!='pending'}
    if status=='pending_review':
     if p['consent']!='agreed':raise ToolError('customer consent for this proposal_id required')
     cs=c.execute('SELECT * FROM customer_state WHERE actor_id=?',(self.actor,)).fetchone()
     if not cs:raise ToolError('current customer state required')
     desired=cs['desired'];allowed={'refund':{'refund_proposal','store_inspection'},'exchange':{'exchange_proposal','store_inspection'},'store_inspection':{'store_inspection'}}.get(desired,set())
     facts=json.loads(cs['body'])
     if plan not in allowed and not facts.get('allow_alternative'):raise ToolError('plan conflicts with current customer intent')
   elif quantity or amount_cents:raise ToolError('non-proposal state must release financial reservations')
   else:
    previous=json.loads(t['body']).get('proposal_id')
    if previous:c.execute("UPDATE proposals SET consent='superseded' WHERE proposal_id=?",(previous,))
   # Draft proposals do not reserve quantity/money. Original proposal quantities live in proposals.
   rq=quantity if status=='pending_review' else 0;ra=amount_cents if status=='pending_review' else 0
   c.execute('UPDATE tickets SET status=?,quantity=?,amount_cents=?,body=? WHERE ticket_id=?',(status,rq,ra,canonical(body),ticket_id));result={'ticket_id':ticket_id,'status':status,'proposal_id':body.get('proposal_id'),'reserved_cents':ra,'stock_confirmation':'staff_confirmed' if body.get('stock_confirmed') else 'pending_staff','executed':False}
   c.execute('INSERT INTO operations VALUES (?,?,?)',(self.actor+':'+request_key,self.actor,canonical({'payload':payload,'result':result})));c.execute('INSERT INTO audit(actor_id,action,object_id,body) VALUES (?,?,?,?)',(self.actor,'update_ticket',ticket_id,canonical({'status':status,'body':body,'quantity':rq,'amount_cents':ra})));return result
 def get_proposal(self,proposal_id):
  with self.db() as c:
   row=c.execute('SELECT p.* FROM proposals p JOIN tickets t USING(ticket_id) WHERE proposal_id=? AND actor_id=?',(proposal_id,self.actor)).fetchone()
   if not row:raise ToolError('proposal not found')
   return dict(row)|{'body':json.loads(row['body'])}
 def mark_human_takeover(self,ticket_id,reason,body,request_key):
  return self.update_ticket(ticket_id,{**body,'handoff_reason':reason},'human_takeover',request_key=request_key)
 def record_handling_result(self,ticket_id,result,request_key):
  """Record staff-bound review request. Agent cannot impersonate staff or execute money movement."""
  if result.get('completed') or result.get('status') in ['refunded','exchanged']:raise ToolError('staff confirmation required; no real execution channel')
  t=self.get_ticket(ticket_id);return self.update_ticket(ticket_id,{**t['body'],'handling_result':result},t['status'],t['quantity'],t['amount_cents'],request_key)
CATALOG=['query_orders','get_order','get_after_sales','get_rules','get_inventory','get_hours','calculate_refund','create_ticket','get_ticket','update_ticket','mark_human_takeover','record_handling_result','get_proposal','bind_ticket_item']
def dispatch(token,tool,args):
 if tool not in CATALOG:raise ToolError('unknown tool')
 return getattr(ToolSession(token),tool)(**args)
if __name__=='__main__':
 import sys
 for line in sys.stdin:
  try:
   request=json.loads(line);print(json.dumps({'ok':True,'result':dispatch(request['token'],request['tool'],request.get('args',{}))},ensure_ascii=False),flush=True)
  except (ValueError,KeyError,TypeError,sqlite3.Error) as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),flush=True)
