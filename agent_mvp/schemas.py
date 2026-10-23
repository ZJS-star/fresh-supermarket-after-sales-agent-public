"""Typed model tool boundary. Host idempotency keys and consent/staff flags are excluded."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class Query(Strict):
 purchased_date:str|None=None
 category:str|None=None
 paid_cents:int|None=Field(None,ge=0,description='Integer cents, entire order paid amount')
 receipt_ref:str|None=None
class Order(Strict):order_id:str
class Item(Strict):item_id:str
class SKU(Strict):sku:str
class Rule(Strict):
 sku:str|None=None
 issue_type:Literal['visible_discoloration','odor_claim','uncertain','identity_conflict','safety_escalation']|None=None
class Quantity(Item):quantity:int=Field(gt=0,description='Integer g/piece/box in purchased unit; do not infer damaged quantity')
class Evidence(Strict):
 media_id:str
 region_normalized:list[float]|None=None
 time_seconds:float|None=Field(None,ge=0)
 @field_validator("region_normalized")
 @classmethod
 def region(cls,v):
  if v is not None and (len(v)!=4 or not all(0<=x<=1 for x in v) or v[0]>=v[2] or v[1]>=v[3]):raise ValueError("region must be normalized left,top,right,bottom")
  return v
class Body(Strict):
 issue:str=Field(min_length=2)
 evidence_refs:list[Evidence]
 customer_preference:Literal['refund','exchange','store_inspection','unknown']
 uncertainties:list[str]
 next_action:str=Field(min_length=2)
 plan:Literal['refund_proposal','exchange_proposal','store_inspection','human_takeover']|None=None
 handoff_reason:str|None=None
 inspection_quantity:int|None=None
 appointment_time:str|None=Field(None,description='ISO8601 with timezone, actual customer-agreed visit time; omit if unknown')
class Create(Strict):
 item_id:str|None=None
 body:Body
class Ticket(Strict):ticket_id:str
class Bind(Ticket):item_id:str
class Update(Ticket):
 body:Body
 status:Literal['awaiting_evidence','awaiting_confirmation','pending_review','human_takeover','cancelled']='awaiting_evidence'
 quantity:int=Field(0,ge=0,description='Refund/exchange quantity in purchased unit. Inspection must be 0.')
 amount_cents:int=Field(0,ge=0,description='Refund cents only. Exchange/inspection must be 0.')
class Handoff(Ticket):
 reason:str=Field(min_length=4)
 body:Body
class Proposal(Strict):proposal_id:str
class Verify(Order):
 receipt_ref:str=Field(description='Exact ref actually supplied by customer; host cross-checks against captured clue and POS')
 media_ids:list[str]
class Finding(Strict):
 statement:str=Field(min_length=2)
 source_type:Literal['visual_observation','customer_claim','unknown']
 evidence_refs:list[Evidence]
class MediaClassification(Strict):
 media_id:str
 category:Literal['product','receipt','weight_label','packaging_label','payment','other','unknown']
 basis:str=Field(min_length=2,max_length=250,description='Visible layout/content basis, not filename or upload hint; uncertain=unknown')
 receipt_ref:str|None=Field(None,min_length=1,max_length=80,description='Only exact legible receipt number; omit unreadable values')
class CustomerReply(Strict):
 message:str=Field(min_length=4,max_length=450,description='Customer-facing plain Chinese, 1-3 sentences; acknowledge intent and concrete next step/question. No internal findings, IDs, Markdown or generic ongoing work if this turn has ended.')
class Findings(Strict):
 media_classifications:list[MediaClassification]=Field(default_factory=list)
 findings:list[Finding]
 unresolved:list[str]|None=Field(None,description="本次更新的未决问题；未变化可省略，省略不会清空既有问题")
 customer_preference:Literal['refund','exchange','store_inspection','unknown']|None=None
 preference_quote:str|None=None
class Propose(Strict):
 plan:Literal['refund_proposal','exchange_proposal','store_inspection']
 item_id:str|None=None
 ticket_id:str|None=None
 issue:str=Field(min_length=2)
 evidence_refs:list[Evidence]
 uncertainties:list[str]
 next_action:str='请店员审核并确认安排'
 quantity:int=Field(0,ge=0,description='Refund/exchange quantity in original unit; inspection=0')
 amount_cents:int=Field(0,ge=0,description='Refund amount only; exchange/inspection=0')
 appointment_time:str|None=Field(None,description='顾客已提供的到店时间必须填写，ISO8601含时区，按宿主场景时间解析相对日期。未知时先问顾客，不在文本中虚构时间。')
class Empty(Strict):pass
TOOLS={
 'reply_to_customer':(CustomerReply,'结束本轮并向顾客发送简洁答复：已处理什么、还缺什么、下一步。仅在前置查询成功后调用；可与独立的record_findings同时调用，减少重复模型请求。不能只说正在核实。'),
 'bind_ticket_item':(Bind,'补交材料且购买核验成功后，把原未绑定工单关联到该明细；更换已有绑定须人工处理。'),
 'propose_plan':(Propose,'优先使用此工具创建/修改具体退款、换货或检查提案。宿主生成工单和proposal_id，尚未提交待审；必须随后向顾客展示数量/金额/安排并征求同意。'),
 'submit_proposal':(Proposal,'顾客已明确同意当前proposal_id后提交待店员审核。宿主原样复用已同意的条款，不需重填工单正文。'),
 'record_findings':(Findings,'记录视觉观察和未知，并按实际画面填写media_classifications自动分类商品、小票、标签、支付截图或其他；上传类型仅为提示。不填写无变化的customer_preference，unknown不清空已知诉求。'),
 'query_orders':(Query,'查询当前身份范围的候选订单；可能零条、多条或尚未同步。'),
 'get_order':(Order,'读取候选订单详情，不自动确认购买归属。'),
 'get_after_sales':(Item,'读取历史退款、换货及剩余数量/金额。'),
 'get_rules':(Rule,'读取模拟门店规则。'),
 'get_inventory':(SKU,'查询库存快照，查询不是店员确认。'),
 'get_hours':(Empty,'查询营业和可预约处理时间。'),
 'calculate_refund':(Quantity,'按整数分和历史记录计算退款建议。'),
 'create_ticket':(Create,'仅创建awaiting_evidence工单，可暂不绑定订单。body.plan=human_takeover不会实际转人工，必须另调mark_human_takeover。'),
 'get_ticket':(Ticket,'读取真实工单状态。'),
 'update_ticket':(Update,'生成具体方案awaiting_confirmation，再等顾客对proposal_id确认后pending_review。换货零金额，检查零数量零金额。'),
 'mark_human_takeover':(Handoff,'真实创建/更新工单后交给人工，停止自主沟通。'),
 'get_proposal':(Proposal,'读取方案内容和顾客/店员确认状态。'),
 'verify_purchase':(Verify,'以实际顾客线索+提交材料+已查询POS核验购买，不能只靠模型布尔值。')}
def definitions():return [{'type':'function','function':{'name':name,'description':desc,'parameters':model.model_json_schema()}} for name,(model,desc) in TOOLS.items()]
def validate(name,args):
 if name not in TOOLS:raise ValueError('tool not allowed')
 return TOOLS[name][0].model_validate(args).model_dump(exclude_none=True)

def normalize_protocol(name,args):
 """Decode JSON-encoded containers used by some compatible gateways. Never coerce scalar business values."""
 import json,types
 from typing import get_args,get_origin,Union
 if name not in TOOLS:raise ValueError('tool not allowed')
 def visit(annotation,value):
  origin=get_origin(annotation)
  if origin in (Union,types.UnionType):
   options=[x for x in get_args(annotation) if x is not type(None)]
   if len(options)==1:return visit(options[0],value)
  is_model=isinstance(annotation,type) and issubclass(annotation,BaseModel)
  if (origin is list or is_model) and isinstance(value,str):
   try:value=json.loads(value)
   except ValueError:raise ValueError('collection argument must be a JSON array/object, not plain text') from None
  if origin is list and isinstance(value,list):return [visit(get_args(annotation)[0],v) for v in value]
  if is_model and isinstance(value,dict):return {k:visit(annotation.model_fields[k].annotation,v) if k in annotation.model_fields else v for k,v in value.items()}
  return value
 return visit(TOOLS[name][0],args)
