"""Host/staff control plane. These methods are never in the model tool catalogue."""
import hashlib,json,sqlite3
from pathlib import Path
SCHEMA='''
CREATE TABLE IF NOT EXISTS exchanges(record_id TEXT PRIMARY KEY,item_id TEXT,exchanged_quantity INTEGER,status TEXT,updated_at TEXT,ticket_id TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS submitted_media(actor_id TEXT,media_id TEXT,body TEXT,PRIMARY KEY(actor_id,media_id));
CREATE TABLE IF NOT EXISTS purchase_verifications(actor_id TEXT,item_id TEXT,basis TEXT,PRIMARY KEY(actor_id,item_id));
CREATE TABLE IF NOT EXISTS proposals(proposal_id TEXT PRIMARY KEY,ticket_id TEXT,fingerprint TEXT,body TEXT,consent TEXT DEFAULT 'pending',staff_stock TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS customer_state(actor_id TEXT PRIMARY KEY,desired TEXT,body TEXT);
CREATE TABLE IF NOT EXISTS host_events(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT,kind TEXT,body TEXT);
'''
def setup(c): c.executescript(SCHEMA)
def canonical(body): return json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def meaningful(v):
 if isinstance(v,str): return bool(v.strip()) and v.strip().lower() not in {'unknown','none','null','n/a','待定'}
 if isinstance(v,list): return bool(v) and all(meaningful(x) for x in v)
 if isinstance(v,dict): return bool(v) and all(meaningful(x) for x in v.values())
 return v is not None
class ControlPlane:
 def __init__(self,session): self.s=session
 def db(self): return self.s.db()
 def event(self,c,kind,body): c.execute('INSERT INTO host_events(actor_id,kind,body) VALUES (?,?,?)',(self.s.actor,kind,canonical(body)))
 def submit_media(self,media):
  with self.db() as c:
   for m in media:
    if not m.get('media_id'): raise ValueError('media_id required')
    c.execute('INSERT OR REPLACE INTO submitted_media VALUES (?,?,?)',(self.s.actor,m['media_id'],canonical(m)))
   self.event(c,'media_submitted',media)
 def customer_update(self,desired=None,**facts):
  with self.db() as c:
   old=c.execute('SELECT * FROM customer_state WHERE actor_id=?',(self.s.actor,)).fetchone();state=json.loads(old['body']) if old else {};state.update(facts);desired=desired or (old['desired'] if old else 'unknown')
   if old and old['desired']!=desired:
    c.execute("UPDATE proposals SET consent='superseded' WHERE ticket_id IN (SELECT ticket_id FROM tickets WHERE actor_id=?)",(self.s.actor,))
    c.execute("UPDATE tickets SET status='awaiting_evidence',quantity=0,amount_cents=0 WHERE actor_id=? AND status IN ('pending_review','awaiting_confirmation')",(self.s.actor,))
   c.execute('INSERT OR REPLACE INTO customer_state VALUES (?,?,?)',(self.s.actor,desired,canonical(state)));self.event(c,'customer_update',{'desired':desired,**facts})
 def verify_purchase(self,item_id,basis):
  # Trusted staff/host attestation, with separately returned POS and actual customer clue/evidence.
  with self.db() as c:
   self.s._item(c,item_id)
   if not basis.get('order_tool_observed') or not meaningful(basis.get('customer_clue')) or not meaningful(basis.get('source')):raise ValueError('POS plus independent customer clue and source required')
   c.execute('INSERT OR REPLACE INTO purchase_verifications VALUES (?,?,?)',(self.s.actor,item_id,canonical(basis)));self.event(c,'purchase_verified',{'item_id':item_id,'basis':basis})
 def expire_appointments(self,new_time):
  import datetime as dt
  expired=[]
  with self.db() as c:
   for t in c.execute("SELECT * FROM tickets WHERE actor_id=? AND status IN ('pending_review','awaiting_confirmation')",(self.s.actor,)).fetchall():
    b=json.loads(t['body']);when=b.get('appointment_time')
    if when and dt.datetime.fromisoformat(when)<dt.datetime.fromisoformat(new_time):
     pid=b.get('proposal_id')
     if pid:c.execute("UPDATE proposals SET consent='superseded' WHERE proposal_id=?",(pid,));expired.append(pid)
     c.execute("UPDATE tickets SET status='awaiting_evidence',quantity=0,amount_cents=0 WHERE ticket_id=?",(t['ticket_id'],))
   if expired:self.event(c,'appointments_expired',{'proposal_ids':expired,'current_time':new_time})
  return expired
 def consent(self,proposal_id,agree):
  with self.db() as c:
   p=c.execute('SELECT p.* FROM proposals p JOIN tickets t USING(ticket_id) WHERE proposal_id=? AND actor_id=?',(proposal_id,self.s.actor)).fetchone()
   if not p:raise ValueError('proposal not in session')
   t=c.execute('SELECT * FROM tickets WHERE ticket_id=?',(p['ticket_id'],)).fetchone();b=json.loads(t['body'])
   if t['status'] in ['refunded_simulated','exchanged_simulated','closed_manual','inspection_confirmed']:raise ValueError('staff-closed proposal cannot be reconfirmed')
   if b.get('proposal_id')!=proposal_id or p['consent']=='superseded':raise ValueError('proposal changed; consent cannot be reused')
   c.execute('UPDATE proposals SET consent=? WHERE proposal_id=?',('agreed' if agree else 'declined',proposal_id))
   if not agree:c.execute("UPDATE tickets SET status='awaiting_evidence',quantity=0,amount_cents=0 WHERE ticket_id=?",(p['ticket_id'],))
   if agree:
    old=c.execute('SELECT * FROM customer_state WHERE actor_id=?',(self.s.actor,)).fetchone();facts=json.loads(old['body']) if old else {};facts['accepted_proposal_id']=proposal_id;desired={'refund_proposal':'refund','exchange_proposal':'exchange','store_inspection':'store_inspection'}[json.loads(p['body'])['plan']];c.execute('INSERT OR REPLACE INTO customer_state VALUES (?,?,?)',(self.s.actor,desired,canonical(facts)))
   self.event(c,'proposal_consent',{'proposal_id':proposal_id,'agree':agree,'proposal':json.loads(p['body'])})
 def confirm_stock(self,proposal_id,staff):
  if not meaningful(staff):raise ValueError('staff identity required')
  with self.db() as c:
   p=c.execute('SELECT p.* FROM proposals p JOIN tickets t USING(ticket_id) WHERE proposal_id=? AND actor_id=?',(proposal_id,self.s.actor)).fetchone()
   if not p or json.loads(p['body'])['plan']!='exchange_proposal':raise ValueError('current exchange proposal required')
   t=c.execute('SELECT * FROM tickets WHERE ticket_id=?',(p['ticket_id'],)).fetchone();b=json.loads(t['body'])
   if b.get('proposal_id')!=proposal_id:raise ValueError('stale proposal')
   i=self.s._item(c,t['item_id']);stock=c.execute('SELECT quantity FROM inventory WHERE sku=?',(i['sku'],)).fetchone()[0]
   if stock is None or stock<json.loads(p['body'])['quantity']:raise ValueError('insufficient or unknown stock')
   c.execute("UPDATE proposals SET staff_stock=? WHERE proposal_id=?",(staff,proposal_id));self.event(c,'staff_stock_confirmation',{'proposal_id':proposal_id,'staff':staff})
