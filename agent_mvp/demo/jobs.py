"""Durable single-process task queue; one serial lane per application, SQLite business transactions."""

import concurrent.futures, json, re, threading, uuid
from .space import now, TERMINAL
from controls import canonical


def friendly_error(error):
    text = str(error)
    for needles, message in [
        (["stock", "inventory"], "同款库存不足或尚未确认，请选择其他方案或接待核实。"),
        (
            ["consent", "proposal changed", "stale"],
            "方案已更新或尚未确认，请刷新后确认当前方案。",
        ),
        (["closed", "already closed"], "申请已经结束，不能继续修改。"),
        (
            ["quantity", "allowance", "refund", "integer"],
            "数量或金额不符合剩余可处理额度，请核对。",
        ),
        (["appointment"], "请选择营业时段内、顾客已同意的未来预约时间。"),
        (["evidence", "submitted"], "请先提交相关材料，再保存方案。"),
        (["bound", "verification"], "购买信息还未核实，请先核对订单或改为到店检查。"),
    ]:
        if any(n in text for n in needles):
            return message
    return (
        text
        if any("\u4e00" <= ch <= "\u9fff" for ch in text) and len(text) < 120
        else "暂时未能处理，请重试或联系门店客服。"
    )


def service_text(run):
    s = run.state
    status = s["status"]
    if status == "pending_review":
        return "您已确认方案，申请已交门店审核。处理进度会在这里更新。"
    if status == "human_takeover" or s.get("handoff"):
        return "申请已交由门店客服接待，现有材料已保留，请等待门店回复。"
    if status in ["model_error", "model_unconfigured", "step_limit"]:
        return "服务暂时繁忙，您的材料已保存。请稍后重试，也可以联系门店客服。"
    if s.get("proposal_id") and s.get("reply_turn") == s["turn"]:
        return s["last_reply"]
    if s.get("proposal_id"):
        return "已为您整理处理方案，请查看下方内容。您可以确认，也可以提出修改。"
    raw = s.get("last_reply", "").strip()
    if s.get("reply_turn") == s["turn"]:
        return raw
    # Compatibility for plain-text model responses: preserve concrete requests, including
    # imperative questions without question marks. Internal reasoning stays in the journal.
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"^[\s#*\-]+", "", line).replace("**", "").strip()
        if not line or re.search(r"偏好引述|已记录为|source_type|media_id|tool_calls|record_findings|propose_plan|awaiting_|pending_review|human_takeover|proposal_id|ticket_id|amount_cents|[{}]|```|U[a-f0-9]{10,}", line):
            continue
        lines.append(line)
    public = "\n".join(lines)
    if public and len(public) <= 600:
        return public
    requests = [line for line in lines if re.search(r"请|麻烦|能否|是否|方便|？|\?", line)]
    return "\n".join(requests[:3])[:600] or "材料已保存。请告诉我们方便到店的日期和时间，以及希望处理的数量；购买信息不清楚也可以说明。"



class Jobs:
    def __init__(self, space):
        self.space = space
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.locks = {}
        self.guard = threading.Lock()
        self.enqueue_lock = threading.RLock()
        self.futures = {}
        self.active = set()
        with space.db() as c:
            c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            pending = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM jobs WHERE status='queued' ORDER BY created"
                )
            ]
        for ident in pending:
            self.schedule(ident)

    def close(self):
        self.pool.shutdown(wait=True)

    def add(self, application, key, payload):
        with self.enqueue_lock:
            return self._add(application, key, payload)

    def _add(self, application, key, payload):
        if not key or len(key) > 100:
            raise ValueError("请刷新后重试")
        with self.space.db() as c:
            old = c.execute(
                "SELECT * FROM jobs WHERE application=? AND request_key=?",
                (application, key),
            ).fetchone()
            if old:
                if old["payload"] != canonical(payload):
                    raise ValueError("重复请求内容已变化，请重新提交")
                return dict(old)
            active = c.execute(
                "SELECT * FROM jobs WHERE application=? AND payload=? AND status IN ('queued','running') ORDER BY rowid LIMIT 1",
                (application, canonical(payload)),
            ).fetchone()
            if active:
                return dict(active)
            ident = uuid.uuid4().hex
            t = now()
            c.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                (ident, application, key, canonical(payload), "queued", None, t, t),
            )
        self.schedule(ident)
        with self.space.db() as c:
            return dict(c.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone())

    def schedule(self, ident):
        with self.space.db() as c:
            app = c.execute(
                "SELECT application FROM jobs WHERE id=?", (ident,)
            ).fetchone()[0]
        with self.guard:
            if app not in self.active:
                self.active.add(app)
                self.futures[app] = self.pool.submit(self.drain, app)

    def drain(self, app):
        while True:
            with self.guard:
                with self.space.db() as c:
                    next_job = c.execute(
                        "SELECT id FROM jobs WHERE application=? AND status='queued' ORDER BY rowid LIMIT 1",
                        (app,),
                    ).fetchone()
                if not next_job:
                    self.active.discard(app)
                    return
            self.execute(next_job["id"])

    def message(self, application, role, text, stamp=None):
        with self.space.db() as c:
            c.execute(
                "INSERT OR IGNORE INTO display_messages(application,role,text,created,message_key) VALUES (?,?,?,?,?)",
                (application, role, text, now(), stamp or uuid.uuid4().hex),
            )

    def handoff_reason(self, run, note):
        ticket = run.session.get_ticket(run.state["ticket_id"])
        body = {
            **ticket["body"],
            "handoff_reason": note or "门店客服主动接待，继续核实当前申请和已提交材料",
        }
        with run.session.db() as c:
            c.execute(
                "UPDATE tickets SET body=? WHERE ticket_id=?",
                (canonical(body), ticket["ticket_id"]),
            )
        run.log({"role": "staff_note", "text": body["handoff_reason"]})
        run.snapshot_final()
        run.save()

    def execute(self, ident):
        with self.space.db() as c:
            j = dict(c.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone())
        app = j["application"]
        with self.guard:
            lane = self.locks.setdefault(app, threading.RLock())
        with lane:
            run = self.space.run(app)
            payload = json.loads(j["payload"])
            action = payload["action"]
            was_handoff = run.state.get("handoff", False)
            try:
                with self.space.db() as c:
                    c.execute(
                        "UPDATE jobs SET status='running',updated=? WHERE id=?",
                        (now(), ident),
                    )
                run.log(
                    {"role": "host", "action": "demo_task_started", "job_id": ident}
                )
                events = [
                    json.loads(x)
                    for x in (run.directory / "events.jsonl").read_text().splitlines()
                ]
                applied = any(
                    e.get("action") == "demo_job_input_applied"
                    and e.get("job_id") == ident
                    for e in events
                )
                if action in ["message", "consent"] and run.state["status"] in TERMINAL:
                    raise ValueError("申请已经结束，请从首页新建申请")
                if not applied:
                    if action == "message":
                        already_received = any(
                            e.get("role") == "customer"
                            and e.get("response", {}).get("demo_request_id") == ident
                            for e in events
                        )
                        if not already_received:
                            media = self.space.uploads(
                                payload["buyer"], payload.get("uploads", [])
                            )
                            run.receive(
                                payload["text"] or "补充材料",
                                media,
                                desired=payload.get("desired"),
                                advance=False,
                                response={"demo_request_id": ident},
                            )
                        else:
                            from ..recovery import recover_customer_journal

                            recover_customer_journal(run)
                        self.message(
                            app, "customer", payload["text"] or "补充了材料", ident
                        )
                        with self.space.db() as c:
                            for uid in payload.get("uploads", []):
                                c.execute(
                                    "UPDATE uploads SET used_by=? WHERE id=?",
                                    (app, uid),
                                )
                    elif action == "consent":
                        run.receive(
                            (
                                "同意当前具体方案"
                                if payload["agree"]
                                else "希望修改当前方案"
                            ),
                            consent={
                                "proposal_id": payload["proposal_id"],
                                "agree": payload["agree"],
                            },
                            advance=False,
                        )
                        self.message(
                            app,
                            "customer",
                            (
                                "我同意这项方案。"
                                if payload["agree"]
                                else "我希望修改这项方案。"
                            ),
                            ident,
                        )
                        if payload["agree"]:
                            if run.state.get("manual_owner"):
                                run.staff("submit_review")
                            else:
                                run.call_tool(
                                    "submit_proposal",
                                    {"proposal_id": payload["proposal_id"]},
                                )
                    elif action == "staff_message":
                        if run.state["status"] in TERMINAL:
                            raise ValueError("申请已结束，不能继续发送消息")
                        run.staff("takeover")
                        self.handoff_reason(run, payload["text"])
                        run.staff_message(payload["text"])
                        self.message(app, "staff", payload["text"], ident)
                    elif action == "staff_action":
                        if payload["operation"] in [
                            "approve_refund",
                            "approve_exchange",
                            "confirm_inspection",
                            "confirm_stock",
                        ] and payload.get("proposal_id") != run.state.get(
                            "proposal_id"
                        ):
                            raise ValueError(
                                "proposal changed; review current version before approving"
                            )
                        run.staff(payload["operation"])
                        note = payload.get("note", "").strip()
                        if payload["operation"] == "takeover":
                            self.handoff_reason(run, note)
                        if note:
                            run.log({"role": "staff_note", "text": note})
                            self.message(app, "staff", note, ident)
                        else:
                            self.message(
                                app,
                                "notice",
                                {
                                    "takeover": "门店客服已接待您的申请。",
                                    "approve_refund": "门店已通过退款审核，演示退款已记录。",
                                    "approve_exchange": "门店已通过换货审核，演示换货已记录。",
                                    "confirm_inspection": "门店已确认到店安排，请按约定时间携带商品和购买凭证。",
                                    "close_manual": "门店已结束本次申请。",
                                    "cancel": "本次申请已取消。",
                                    "confirm_stock": "门店已确认换货库存。",
                                    "submit_review": "方案已提交门店审核。",
                                }.get(payload["operation"], "处理进度已更新。"),
                                ident,
                            )
                    elif action == "staff_proposal":
                        run.staff_modify(
                            payload["body"],
                            payload["quantity"],
                            payload["amount_cents"],
                        )
                        self.message(
                            app,
                            "notice",
                            "门店更新了处理方案。之前的确认已失效，请查看并确认新版本。",
                            ident,
                        )
                    elif action not in ["start", "retry"]:
                        raise ValueError("不支持的操作")
                    run.log(
                        {
                            "role": "host",
                            "action": "demo_job_input_applied",
                            "job_id": ident,
                        }
                    )
                    run.save()
                if (
                    action in ["start", "retry", "message"]
                    and not run.state["handoff"]
                    and run.state["status"] not in TERMINAL | {"pending_review"}
                ):
                    run.advance()
                if action in ["start", "retry", "message", "consent"]:
                    if not run.state["handoff"]:
                        self.message(app, "service", service_text(run), ident)
                    elif action == "consent":
                        self.message(
                            app,
                            "notice",
                            "方案确认状态已更新，门店客服将继续处理。",
                            ident,
                        )
                    elif not was_handoff:
                        self.message(
                            app,
                            "notice",
                            "申请已交门店客服接待，当前材料已保留。",
                            ident,
                        )
                run.export()
                failure = (
                    run.state.get("last_error")
                    if run.state["status"]
                    in ["model_error", "model_unconfigured", "step_limit"]
                    else None
                )
                with self.space.db() as c:
                    c.execute(
                        "UPDATE jobs SET status=?,error=?,updated=? WHERE id=?",
                        ("failed" if failure else "done", failure, now(), ident),
                    )
            except Exception as exc:
                run.log(
                    {
                        "role": "host",
                        "action": "demo_job_failed",
                        "job_id": ident,
                        "error": str(exc)[:600],
                    }
                )
                run.save()
                with self.space.db() as c:
                    c.execute(
                        "UPDATE jobs SET status='failed',error=?,updated=? WHERE id=?",
                        (str(exc)[:600], now(), ident),
                    )
