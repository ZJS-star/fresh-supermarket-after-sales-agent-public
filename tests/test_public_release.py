"""Public fixtures contain no private dataset or real model responses."""
import io,json,sqlite3,time
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from agent_mvp.api import create_app
from agent_mvp.demo.software import SoftwareModel
from test_demo import auth,settle

def test_seed_has_no_business_rows():
 with sqlite3.connect(Path(__file__).resolve().parents[1]/'after_sales_dataset/snapshot/business.sqlite3') as c:
  for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
   assert c.execute('SELECT count(*) FROM "'+name+'"').fetchone()[0]==0

def test_public_software_flow_upload_confirm_review(tmp_path):
 with TestClient(create_app(tmp_path/'runs',SoftwareModel)) as c:
  auth(c);out=io.BytesIO();Image.new('RGB',(60,60),'green').save(out,format='PNG')
  up=c.post('/demo/api/uploads',files={'file':('fixture.png',out.getvalue(),'image/png')}).json()['id']
  r=c.post('/demo/api/applications',json={'request_key':'public-flow','description':'软件测试素材，想先到店检查','desired':'store_inspection','item_id':'QH1022001-1','uploads':[up]})
  assert r.status_code==202;ident=r.json()['application'];s=settle(c,ident);assert s['plan']['needs_confirmation']
  c.post('/demo/api/applications/'+ident+'/consent',json={'request_key':'agree','proposal_id':s['plan']['id'],'agree':True});s=settle(c,ident);assert s['status']=='待门店处理'
  auth(c,'merchant');r=c.post('/demo/api/applications/'+ident+'/actions',json={'request_key':'approve','operation':'confirm_inspection','proposal_id':s['plan']['id']});assert r.status_code==202;s=settle(c,ident)
  assert s['status']=='已安排到店' and not s['plan']['needs_confirmation']
