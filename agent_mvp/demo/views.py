"""Role projections: customer never sees raw model prose, IDs or developer internals."""

import json
from .space import TERMINAL, STORE
from .jobs import friendly_error


def read_events(run):
    return [
        json.loads(line)
        for line in (run.directory / "events.jsonl")
        .read_text()
        .splitlines(keepends=True)
        if line.endswith("\n")
    ]


LABELS = {
    "ready": "已提交",
    "running": "处理中",
    "awaiting_evidence": "待补充材料",
    "awaiting_customer": "待补充信息",
    "awaiting_confirmation": "待确认方案",
    "pending_review": "待门店处理",
    "human_takeover": "门店接待中",
    "inspection_confirmed": "已安排到店",
    "refunded_simulated": "已处理完成",
    "exchanged_simulated": "已处理完成",
    "closed_manual": "已结束",
    "cancelled": "已取消",
    "model_error": "处理暂时中断",
    "model_unconfigured": "处理暂时中断",
    "step_limit": "处理暂时中断",
}
CATEGORIES = {
    "pending_review": "review",
    "awaiting_confirmation": "customer",
    "awaiting_customer": "customer",
    "awaiting_evidence": "customer",
}


def view(space, ident, staff=False):
    app = space.application(ident)
    run = space.run(ident)
    plan = None
    with space.db() as c:
        jobs = [
            dict(r)
            for r in c.execute(
                "SELECT id,status,error,created,updated,payload FROM jobs WHERE application=? ORDER BY rowid DESC",
                (ident,),
            )
        ]
        messages = [
            dict(r)
            for r in c.execute(
                "SELECT role,text,created FROM display_messages WHERE application=? ORDER BY id",
                (ident,),
            )
        ]
    s = json.loads((run.directory / "state.json").read_text())
    ticket = run.session.get_ticket(s["ticket_id"]) if s.get("ticket_id") else None
    status = ticket["status"] if ticket else s["status"]
    if ticket and ticket["status"] == "awaiting_evidence" and s["status"] in ["awaiting_customer", "model_error", "model_unconfigured", "step_limit"]:
        status = s["status"]
    active = next((j for j in jobs if j["status"] in ["queued", "running"]), None)
    if active:
        status = "running"
    item = None
    if app["item_id"]:
        with space.business() as c:
            item = dict(
                c.execute(
                    "SELECT i.*,p.name,p.spec FROM order_items i JOIN products p USING(sku) WHERE item_id=?",
                    (app["item_id"],),
                ).fetchone()
            )
    if s.get("proposal_id") and ticket:
        p = run.session.get_proposal(s["proposal_id"])
        pb = p["body"]
        terms = pb["terms"]
        with run.session.db() as c:
            version = c.execute(
                "SELECT count(*) FROM proposals WHERE ticket_id=?",
                (ticket["ticket_id"],),
            ).fetchone()[0]
        plan = {
            "id": p["proposal_id"],
            "version": version,
            "type": pb["plan"],
            "quantity": pb["quantity"],
            "amount_cents": pb["amount_cents"],
            "consent": p["consent"],
            "appointment": terms.get("appointment_time"),
            "uncertainties": terms.get("uncertainties", []),
            "next_action": terms.get("next_action"),
            "stock_confirmed": p["staff_stock"] != "pending",
            "needs_confirmation": p["consent"] == "pending"
            and ticket["status"] == "awaiting_confirmation",
            "requires": ["商品实物", "购买凭证（如有）"],
            "stage": LABELS.get(ticket["status"], "处理中"),
        }
    progress = "正在处理您的申请"
    if active:
        ev = [e for e in read_events(run)]
        start = max(
            (
                e["sequence"]
                for e in ev
                if e.get("action") == "demo_task_started"
                and e.get("job_id") == active["id"]
            ),
            default=0,
        )
        ev = [e for e in ev if e["sequence"] >= start] if start else []
        last = next(
            (e for e in reversed(ev) if e["role"] in ["tool_intent", "model_request"]),
            {},
        )
        progress = {
            "record_findings": "正在整理材料识别结果",
            "reply_to_customer": "正在整理回复",
            "get_order": "正在核对购买记录",
            "query_orders": "正在查找购买记录",
            "verify_purchase": "正在核对购买信息",
            "get_inventory": "正在查询库存",
            "get_rules": "正在核对门店处理规则",
            "propose_plan": "正在整理处理方案",
            "calculate_refund": "正在核算可退金额",
        }.get(
            last.get("tool"),
            (
                "正在查看您提交的信息和材料"
                if last.get("role") == "model_request"
                else progress
            ),
        )
    category = "completed" if status in TERMINAL else CATEGORIES.get(status, "pending")
    result = {
        "id": ident,
        "number": app["number"],
        "store": STORE,
        "description": app["description"],
        "created": app["created"],
        "status": LABELS.get(status, "处理中"),
        "category": category,
        "next_step": (
            "正在处理"
            if active
            else {
                "pending_review": "等待门店审核",
                "awaiting_confirmation": "等待顾客确认",
                "awaiting_evidence": "等待补充材料",
                "awaiting_customer": "等待顾客回复",
                "human_takeover": "门店继续接待",
            }.get(status, "查看处理结果")
        ),
        "closed": status in TERMINAL,
        "item": item,
        "intent": {
            "refund": "退款",
            "exchange": "换货",
            "store_inspection": "到店检查",
            "unknown": "与门店协商",
        }.get(s["current_customer_intent"], "与门店协商"),
        "plan": plan,
        "messages": messages,
        "media": [
            {
                "id": m["media_id"],
                "kind": m["kind"],
                "category": m.get("classification", {}).get("category", "unknown"),
                "url": f'/demo/api/applications/{ident}/media/{m["media_id"]}',
            }
            for m in s["media"]
        ],
        "task": (
            {"id": active["id"], "status": active["status"], "progress": progress}
            if active
            else None
        ),
        "failure": (
            friendly_error(jobs[0]["error"])
            if jobs
            and jobs[0]["status"] == "failed"
            and (
                staff
                or json.loads(jobs[0]["payload"])["action"]
                in ["start", "retry", "message", "consent"]
            )
            else None
        ),
        "manual": s.get("handoff", False),
        "timeline": [{"text": "顾客提交售后申请", "time": app["created"]}]
        + [
            {
                "text": (
                    "门店客服接待并回复"
                    if m["role"] == "staff"
                    else "顾客确认处理方案" if m["role"] == "customer" else m["text"]
                ),
                "time": m["created"],
            }
            for m in messages
            if m["role"] in ["notice", "staff"]
            or (m["role"] == "customer" and m["text"] == "我同意这项方案。")
        ],
    }
    if staff:
        result["internal"] = {
            "status": status,
            "findings": s["observed_findings"],
            "media_classifications": [m["classification"] for m in s["media"] if m.get("classification")],
            "verified_facts": s["verified_facts"],
            "unresolved": list(
                dict.fromkeys(
                    [
                        f["statement"]
                        for f in s["observed_findings"]
                        if f.get("source_type") == "unknown"
                    ]
                    + (ticket["body"].get("uncertainties", []) if ticket else [])
                )
            ),
            "ticket": ticket,
            "jobs": jobs,
            "model_seconds": s["model_seconds"],
            "model_calls": s["model_calls"],
            "mode": run.meta["model_kind"],
            "events": [e for e in read_events(run)][-60:],
        }
        result["history"] = (
            run.session.get_after_sales(app["item_id"]) if app["item_id"] else None
        )
    return result
