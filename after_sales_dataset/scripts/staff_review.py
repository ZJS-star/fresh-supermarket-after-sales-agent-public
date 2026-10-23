"""Trusted simulated staff actions; never a model tool. No external money movement."""
import argparse,json,sqlite3,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R))
from controls import setup,canonical

def apply(ticket_id,action,staff_name,root=R,current_time=None):
 if action not in ['approve_refund','approve_exchange','confirm_inspection','close_manual','takeover','cancel']:raise ValueError('unsupported staff action')
 if not staff_name.strip():raise ValueError('staff identity required')
 c=sqlite3.connect(Path(root)/'runtime/business.sqlite3');c.row_factory=sqlite3.Row;setup(c)
 try:
  c.execute('BEGIN IMMEDIATE');t=c.execute('SELECT * FROM tickets WHERE ticket_id=?',(ticket_id,)).fetchone()
  if not t:raise ValueError('ticket not found')
  body=json.loads(t['body']);expected={'approve_refund':'refund_proposal','approve_exchange':'exchange_proposal','confirm_inspection':'store_inspection'}
  if action in expected and body.get('plan')!=expected[action]:raise ValueError('staff action does not match proposal type')
  terminals={'approve_refund':'refunded_simulated','approve_exchange':'exchanged_simulated','confirm_inspection':'inspection_confirmed','close_manual':'closed_manual','cancel':'closed_manual'}
  if t['status'] in ['refunded_simulated','exchanged_simulated','closed_manual','inspection_confirmed']:
   if terminals.get(action)!=t['status']:raise ValueError('already closed with another outcome')
   return {'ticket_id':ticket_id,'status':t['status'],'deduplicated':True,'simulation_only':True}
  if action in expected:
   if t['status']!='pending_review':raise ValueError('valid pending review required')
   p=c.execute('SELECT * FROM proposals WHERE proposal_id=?',(body.get('proposal_id'),)).fetchone()
   if not p or p['consent']!='agreed':raise ValueError('current proposal consent required')
   pb=json.loads(p['body'])
   if pb['quantity']!=t['quantity'] or pb['amount_cents']!=t['amount_cents']:raise ValueError('ticket differs from consented proposal')
   i=c.execute('SELECT * FROM order_items WHERE item_id=?',(t['item_id'],)).fetchone()
   if action in ['approve_refund','approve_exchange']:
    if not i or t['quantity']<=0:raise ValueError('positive confirmed quantity and item required')
    h=c.execute("SELECT COALESCE(SUM(refunded_quantity),0),COALESCE(SUM(refunded_cents),0) FROM after_sales WHERE item_id=? AND status IN ('refunded','exchanged')",(t['item_id'],)).fetchone()
    exchanged=c.execute('SELECT COALESCE(SUM(exchanged_quantity),0) FROM exchanges WHERE item_id=?',(t['item_id'],)).fetchone()[0]
    if h[0]+exchanged+t['quantity']>i['quantity'] or h[1]+t['amount_cents']>i['paid_cents']:raise ValueError('remaining allowance exceeded')
   if action=='confirm_inspection':
    import datetime as dt
    appointment=dt.datetime.fromisoformat(body.get('appointment_time',''));now=dt.datetime.fromisoformat(current_time or t['created_at']);hours=json.loads(c.execute('SELECT body FROM opening_hours').fetchone()[0])
    if appointment.tzinfo is None or appointment<=now or not hours['appointment_start']<=appointment.strftime('%H:%M')<=hours['appointment_end'] or appointment.minute%hours['slot_minutes']:raise ValueError('valid future customer-agreed appointment within store slots required')
   if action=='approve_refund':
    if t['amount_cents']<=0:raise ValueError('positive refund required')
    c.execute('INSERT INTO after_sales VALUES (?,?,?,?,?,?)',('STAFF_'+ticket_id,t['item_id'],t['quantity'],t['amount_cents'],'refunded',t['created_at']))
   elif action=='approve_exchange':
    if p['staff_stock']=='pending' or t['amount_cents']!=0:raise ValueError('staff inventory confirmation required; exchange money must be zero')
    stock=c.execute('SELECT quantity FROM inventory WHERE sku=?',(i['sku'],)).fetchone()[0]
    if stock is None or stock<t['quantity']:raise ValueError('stock insufficient')
    c.execute('UPDATE inventory SET quantity=quantity-? WHERE sku=?',(t['quantity'],i['sku']));c.execute('INSERT INTO exchanges VALUES (?,?,?,?,?,?)',('EXCHANGE_'+ticket_id,t['item_id'],t['quantity'],'exchanged_simulated',t['created_at'],ticket_id))
   status=terminals[action]
  else:status='human_takeover' if action=='takeover' else 'closed_manual'
  c.execute('UPDATE tickets SET status=?,quantity=CASE WHEN ? IN (\'closed_manual\',\'human_takeover\') THEN 0 ELSE quantity END,amount_cents=CASE WHEN ? IN (\'closed_manual\',\'human_takeover\') THEN 0 ELSE amount_cents END WHERE ticket_id=?',(status,status,status,ticket_id));c.execute('INSERT INTO audit(actor_id,action,object_id,body) VALUES (?,?,?,?)',('STAFF_SIM:'+staff_name,action,ticket_id,canonical({'simulation_only':True})));c.commit();return {'ticket_id':ticket_id,'status':status,'simulation_only':True,'actual_money_moved':False}
 except: c.rollback();raise
 finally:c.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--ticket',required=True);p.add_argument('--action',required=True);p.add_argument('--staff',required=True);a=p.parse_args();print(json.dumps(apply(a.ticket,a.action,a.staff)))
