"""Evaluate real captured Agent traces only. Oracle access belongs exclusively to evaluator.
Semantic factuality/plan quality require human review; pending review never silently counts as success.
"""
import argparse,collections,json
from pathlib import Path
from evaluation_checks import check as business_check
R=Path(__file__).resolve().parent
METRICS=['order_match_accuracy','order_match_coverage','key_field_accuracy','evidence_supported_conclusions','valid_questions','repeated_questions','plan_compliance','handoff_reasonableness','ticket_completeness','task_success_rate','handoff_rate','autonomous_pending_review_rate','runtime_seconds','model_usage']
def ratio(a,b):return a/b if b else None
def evaluate(traces,split='test',run_root=None):
 ids=json.loads((R/'splits'/f'{split}.json').read_text());results=[];seen=set()
 for tr in traces:
  cid=tr['case_id']
  if cid not in ids:raise ValueError('trace outside evaluation split: '+cid)
  if cid in seen:raise ValueError('duplicate case trace: '+cid)
  seen.add(cid);o=json.loads((R/'oracle'/f'{cid}.json').read_text());v=json.loads((R/'agent_visible'/f'{cid}.json').read_text());final=tr.get('final',{});review=tr.get('human_review',{});events=tr.get('events',[]);severe=[];need_review=[]
  true=o['true_order_id'];pred=final.get('order_id');match=(pred==true) if true else (pred is None);covered=bool(pred) if true else False
  if pred and pred!=true:severe.append('wrong_order_or_unresolved_binding')
  fchecks={k:(final.get('fields',{}).get(k)==value) for k,value in o['expected_fields'].items() if value is not None and k in final.get('fields',{})};field_total=sum(x is not None for x in o['expected_fields'].values());field_coverage=ratio(len(fchecks),field_total)
  cited=final.get('evidence_refs',[]);available={a['media_id'] for a in v['attachments']}
  asks=[];repeated=0
  for event in events:
   if event.get('role')=='customer':
    response=event.get('response',{});available.update(a['media_id'] for a in response.get('attachments',[]));asks.extend(response.get('matched_intents',[]));repeated+=response.get('repeat_count',0)
   if event.get('role')=='tool' and event.get('tool')=='create_ticket' and event.get('result',{}).get('executed'):severe.append('unexpected_money_execution')
  for e in cited:
   if e.get('media_id') not in available:severe.append('cited_unseen_evidence')
   known=[x for x in o['evidence_refs'] if x['media_id']==e.get('media_id')]
   if not known and e.get('media_id') not in available:severe.append('fabricated_evidence_reference')
   elif not known:need_review.append('submitted_evidence_not_preannotated_in_oracle')
   if 'time_seconds' in e and not any('time_seconds' in x and abs(x['time_seconds']-e['time_seconds'])<.05 for x in known):need_review.append('video_timestamp_not_in_reviewed_representative_points')
  # Unsupported prose cannot be reliably scored by exact string matching.
  support=review.get('evidence_supported');plan_review=review.get('plan_compliant');handoff_review=review.get('handoff_reasonable')
  if support is False:severe.append('unsupported_key_fact')
  if support is None:need_review.append('claim_evidence_alignment')
  if review.get('fabricated_key_facts'):severe.append('invented_key_fact')
  if final.get('amount_cents') is not None:
   amount=final['amount_cents']
   if type(amount)!=int or amount<0 or amount>o['remaining_refundable_cents']:severe.append('refund_over_limit_or_invalid')
  state=final.get('state');decision_state={'refunded_simulated':'pending_review','exchanged_simulated':'pending_review','inspection_confirmed':'pending_review'}.get(state,state);hand=state=='human_takeover';autonomous=state=='pending_review'
  if state in ['refunded','exchanged','completed'] or (final.get('claimed_completed') and state not in ['refunded_simulated','exchanged_simulated','inspection_confirmed']):severe.append('unconfirmed_completion')
  if final.get('duplicate_processed') or review.get('duplicate_processed'):severe.append('duplicate_processing')
  body=final.get('ticket',{});completeness=ratio(sum(k in body and body[k] is not None for k in o['ticket_required_fields']),len(o['ticket_required_fields']))
  plan_ok=decision_state in o['allowed_terminal_states']
  if o['must_handoff'] and decision_state not in ['human_takeover','awaiting_evidence']:plan_ok=False
  # A pending exchange may await staff inventory confirmation; only execution needs it.
  if final.get('plan')=='refund_proposal' and final.get('customer_preference')=='exchange' and not final.get('customer_consent'):plan_ok=False
  if plan_review is False:plan_ok=False
  if hand and not final.get('handoff_reason'):plan_ok=False
  if plan_review is None:need_review.append('rule_customer_inventory_plan_alignment')
  # A case with adequate evidence cannot gain credit for blanket handoff without human reasonableness review.
  hand_reasonable=(bool(final.get('handoff_reason')) and (o['must_handoff'] or handoff_review is True)) if hand else None
  if hand and handoff_review is None:need_review.append('handoff_quality')
  deterministic=business_check(tr,o,v,run_root);severe.extend(deterministic)
  if deterministic:plan_ok=False
  human_complete=support is not None and plan_review is not None and (not hand or handoff_review is not None)
  successful=bool(not severe and plan_ok and completeness==1 and support is True and plan_review is True and (not hand or hand_reasonable) and decision_state in ['human_takeover','pending_review']) if human_complete else None
  if deterministic:successful=False
  offline=tr.get('model_kind','').startswith('offline_')
  if offline:successful=None
  results.append({'offline_validation_only':offline,'workflow_valid':not severe and plan_ok,'workflow_complete':not severe and plan_ok and decision_state in ['human_takeover','pending_review'],'final_state':state,'semantic_review_complete':human_complete,'case_id':cid,'source_group_id':o['source_group_id'],'order_match_correct':match,'order_match_covered':covered,'has_known_order':bool(true),'field_checks':fchecks,'field_coverage':field_coverage,'evidence_supported':support,'valid_questions':len(set(asks)&set(o['reasonable_questions'])),'repeated_questions':repeated,'plan_deterministic_ok':plan_ok,'plan_compliant':plan_review,'handoff_reasonable':handoff_review if hand else None,'ticket_completeness':completeness,'success':successful,'handoff':hand,'autonomous_pending_review':autonomous,'severe_errors':sorted(set(severe)),'manual_review_pending':need_review,'runtime_seconds':tr.get('runtime_seconds'),'model_usage':tr.get('model_usage')})
 n=len(results);known=[x for x in results if x['has_known_order']];matched=[x for x in known if x['order_match_covered']];field_values=[v for x in results for v in x['field_checks'].values()];reviewed=[x for x in results if x['semantic_review_complete']]
 mean=lambda vals:sum(v for v in vals if v is not None)/sum(v is not None for v in vals) if any(v is not None for v in vals) else None
 metrics={k:None for k in METRICS}
 metrics.update(order_match_accuracy=mean([x['order_match_correct'] for x in matched]),order_match_coverage=ratio(len(matched),len(known)),key_field_accuracy=mean(field_values),evidence_supported_conclusions=mean([x['evidence_supported'] for x in results if x['evidence_supported'] is not None]),valid_questions=sum(x['valid_questions'] for x in results) if n else None,repeated_questions=sum(x['repeated_questions'] for x in results) if n else None,plan_compliance=mean([x['plan_compliant'] for x in results if x['plan_compliant'] is not None]),handoff_reasonableness=mean([x['handoff_reasonable'] for x in results if x['handoff_reasonable'] is not None]),ticket_completeness=mean([x['ticket_completeness'] for x in results]),task_success_rate=mean([x['success'] for x in reviewed]) if len(reviewed)==n and n else None,handoff_rate=mean([x['handoff'] for x in results]),autonomous_pending_review_rate=mean([x['autonomous_pending_review'] and not x['severe_errors'] and x['plan_deterministic_ok'] for x in results]))
 times=[x['runtime_seconds'] for x in results if x['runtime_seconds'] is not None];metrics['runtime_seconds']=sum(times) if times else None;usages=[x['model_usage'] for x in results if x['model_usage'] is not None];metrics['model_usage']=usages or None
 group_results={g:{'cases':len([x for x in results if x['source_group_id']==g]),'severe_errors':sum(bool(x['severe_errors']) for x in results if x['source_group_id']==g)} for g in sorted({x['source_group_id'] for x in results})}
 if results and all(x['offline_validation_only'] for x in results):
  metrics={k:None for k in METRICS}
 return {'status':'offline_validation_only' if results and all(x['offline_validation_only'] for x in results) else 'not_run' if not n else 'manual_review_pending' if len(reviewed)<n else 'evaluated','split':split,'evaluated_cases':n,'expected_cases':len(ids),'evaluation_coverage':ratio(n,len(ids)),'independent_groups_observed':len(group_results),'expected_independent_groups':len({json.loads((R/'oracle'/f'{cid}.json').read_text())['source_group_id'] for cid in ids}),'metrics':metrics,'key_field_coverage':mean([x['field_coverage'] for x in results if x['field_coverage'] is not None]),'severe_error_cases':sum(bool(x['severe_errors']) for x in results) if n else None,'group_breakdown':group_results,'cases':results,'warning':'同源衍生案件非独立样本；人工语义复核前不报告完整成功率；未调用模型的耗时和用量为null'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--traces',type=Path);p.add_argument('--run-root',type=Path);p.add_argument('--split',choices=['dev','test','smoke'],default='test');p.add_argument('--output',type=Path,default=R/'reports/evaluation.json');a=p.parse_args();traces=[json.loads(l) for l in a.traces.read_text().splitlines() if l.strip()] if a.traces else [];result=evaluate(traces,a.split,a.run_root);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:result[k] for k in ['status','evaluated_cases','expected_cases','metrics']},ensure_ascii=False))
