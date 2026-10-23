"""Shared POS + per-application host state. No case/private/oracle reads here."""

import datetime as dt, hashlib, json, secrets, shutil, sqlite3, threading, uuid
from pathlib import Path
from .. import DATA
from ..runtime import Run, SYSTEM
from ..model import VisionModel
from controls import canonical, setup

ROOT = Path(__file__).resolve().parents[2] / ".demo"
ACCOUNTS = {
    "customer": ("小林", "BUYER_LIN"),
    "other": ("小陈", "BUYER_CHEN"),
    "merchant": ("门店客服", None),
    "console": ("演示管理员", None),
}
STORE = "青禾鲜选 · 邻里店"
NOW = "2026-10-23T10:00:00+08:00"
TERMINAL = {
    "refunded_simulated",
    "exchanged_simulated",
    "inspection_confirmed",
    "closed_manual",
    "cancelled",
    "resolved_no_refund",
}
DEMO_SYSTEM = """这是一个自主提交的本地演示申请。订单选项由已登录模拟账号选择并由宿主核验，属于独立业务依据；不要要求有订单顾客反复提供凭证编号。每申请只处理已选择的商品。先读宿主已建工单、核验记录和顾客描述，再根据材料决定追问、提案或交接。未知订单不强行匹配。内部视觉观察、冲突、购买核验细节写record_findings/工具，最终面向顾客文字只需1至3句，说明下一步；不输出媒体编号、订单内部ID、工具名或内部JSON。异常数量未核实优先检查，不臆造退款数量。预订先提方案再确认；只有店员批准才算安排。创建工单不等于已提出方案，必须实际调用propose_plan取得当前proposal_id，才可以邀请顾客在方案卡片确认。"""


def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(
        timespec="seconds"
    )


class Space:
    def __init__(self, root=ROOT, model_factory=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.models = model_factory or VisionModel
        self.lock = threading.RLock()
        self.runs = {}
        if not (self.root / "current.json").exists():
            self.reset()
        self.path = (
            self.root
            / json.loads((self.root / "current.json").read_text())["generation"]
        )

    def db(self):
        c = sqlite3.connect(self.path / "control.sqlite3", timeout=20)
        c.row_factory = sqlite3.Row
        return c

    def business(self):
        c = sqlite3.connect(self.path / "business.sqlite3", timeout=20)
        c.row_factory = sqlite3.Row
        return c

    def reset(self):
        with self.lock:
            if hasattr(self, "path"):
                with self.db() as c:
                    if c.execute(
                        "SELECT 1 FROM jobs WHERE status IN ('queued','running')"
                    ).fetchone():
                        raise ValueError("仍有任务处理中，请处理结束后重置")
            generation = "space_" + uuid.uuid4().hex[:12]
            p = self.root / generation
            p.mkdir()
            (p / "runs").mkdir()
            (p / "uploads").mkdir()
            with sqlite3.connect(p / "control.sqlite3") as c:
                c.executescript(
                    """
    CREATE TABLE applications(id TEXT PRIMARY KEY,number TEXT UNIQUE,buyer TEXT,item_id TEXT,description TEXT,created TEXT,request_key TEXT,request_body TEXT,UNIQUE(buyer,request_key));
    CREATE TABLE jobs(id TEXT PRIMARY KEY,application TEXT,request_key TEXT,payload TEXT,status TEXT,error TEXT,created TEXT,updated TEXT,UNIQUE(application,request_key));
    CREATE TABLE sessions(token TEXT PRIMARY KEY,role TEXT,buyer TEXT,generation TEXT);
    CREATE TABLE uploads(id TEXT PRIMARY KEY,buyer TEXT,path TEXT,kind TEXT,name TEXT,used_by TEXT);
    CREATE TABLE display_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,application TEXT,role TEXT,text TEXT,created TEXT,message_key TEXT,UNIQUE(application,role,message_key));
   """
                )
            # Only reuse schema, never dataset transactions or case inputs.
            with sqlite3.connect(
                DATA / "snapshot/business.sqlite3"
            ) as source, sqlite3.connect(p / "business.sqlite3") as c:
                for (sql,) in source.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ):
                    c.execute(sql)
                setup(c)
                products = [
                    ("DURIAN", "泰国金枕榴莲", '["榴莲"]', "榴莲", "整果称重", "g"),
                    ("GRAPE", "阳光玫瑰葡萄", '["葡萄"]', "葡萄", "500克 / 盒", "box"),
                    ("MELON", "麒麟西瓜", '["西瓜"]', "西瓜", "小果 / 个", "piece"),
                ]
                c.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)
                for oid, buyer, sku, q, unit, paid, discount in [
                    ("QH1022001", "BUYER_LIN", "DURIAN", 2784, "g", 19490, 0),
                    ("QH1022002", "BUYER_LIN", "GRAPE", 2, "box", 3980, 200),
                    ("QH1022003", "BUYER_LIN", "MELON", 1, "piece", 1800, 0),
                    ("QH1022004", "BUYER_CHEN", "GRAPE", 1, "box", 1990, 100),
                ]:
                    c.execute(
                        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            oid,
                            buyer,
                            "STORE_SIM_01",
                            "2026-10-22T17:30:00+08:00",
                            "store",
                            "wechat",
                            paid + discount,
                            discount,
                            paid,
                            "paid",
                            1,
                            "DEMO-" + oid,
                        ),
                    )
                    c.execute(
                        "INSERT INTO order_items VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            oid + "-1",
                            oid,
                            sku,
                            q,
                            unit,
                            paid + discount,
                            q,
                            paid + discount,
                            discount,
                            paid,
                            0,
                        ),
                    )
                # A second line makes explicit item selection necessary.
                c.execute(
                    "INSERT INTO order_items VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "QH1022002-2",
                        "QH1022002",
                        "MELON",
                        1,
                        "piece",
                        1800,
                        1,
                        1800,
                        0,
                        1800,
                        0,
                    ),
                )
                c.execute(
                    "UPDATE orders SET gross_cents=gross_cents+1800,paid_cents=paid_cents+1800 WHERE order_id='QH1022002'"
                )
                c.executemany(
                    "INSERT INTO inventory VALUES (?,?,?,?)",
                    [
                        ("DURIAN", 30000, "g", NOW),
                        ("GRAPE", 0, "box", NOW),
                        ("MELON", 8, "piece", NOW),
                    ],
                )
                rules = json.loads((DATA / "config/store_rules.json").read_text())
                c.execute(
                    "INSERT INTO rules VALUES (?,?)",
                    (rules["version"], canonical(rules)),
                )
                c.execute(
                    "INSERT INTO opening_hours VALUES (?,?)",
                    ("STORE_SIM_01", canonical(rules["hours"])),
                )
            self.path = p
            (self.root / "current.json").write_text(
                canonical({"generation": generation})
            )
            return generation

    def orders(self, buyer):
        with self.business() as c:
            orders = [
                dict(o)
                for o in c.execute("SELECT * FROM orders WHERE actor_id=?", (buyer,))
            ]
            for o in orders:
                o["items"] = [
                    dict(i)
                    for i in c.execute(
                        "SELECT i.*,p.name,p.spec FROM order_items i JOIN products p USING(sku) WHERE order_id=?",
                        (o["order_id"],),
                    )
                ]
            return orders

    def application(self, ident, buyer=None):
        with self.db() as c:
            r = c.execute("SELECT * FROM applications WHERE id=?", (ident,)).fetchone()
        if not r or (buyer and r["buyer"] != buyer):
            raise ValueError("找不到这份售后申请")
        return dict(r)

    def run(self, ident):
        self.application(ident)
        with self.lock:
            if ident not in self.runs:
                self.runs[ident] = Run(self.path / "runs" / ident, self.models())
            return self.runs[ident]

    def create(self, buyer, description, desired, item_id, uploads, key):
        if not description.strip():
            raise ValueError("请填写遇到的问题")
        if not key or len(key) > 100:
            raise ValueError("请重试提交")
        with self.lock:
            with self.db() as c:
                old = c.execute(
                    "SELECT * FROM applications WHERE buyer=? AND request_key=?",
                    (buyer, key),
                ).fetchone()
                if old:
                    if old["request_body"] != canonical(
                        {
                            "description": description,
                            "desired": desired,
                            "item_id": item_id,
                            "uploads": uploads,
                        }
                    ):
                        raise ValueError("重复提交的内容有变化，请重新提交")
                    return old["id"], False
            chosen = None
            for order in self.orders(buyer):
                for item in order["items"]:
                    if item["item_id"] == item_id:
                        chosen = (order, item)
            if item_id and not chosen:
                raise ValueError("请选择本人订单中的商品")
            # Active duplicate item applications return the existing case; completed ones may be followed by a new request.
            if item_id:
                with self.db() as c:
                    existing = c.execute(
                        "SELECT id FROM applications WHERE buyer=? AND item_id=?",
                        (buyer, item_id),
                    ).fetchall()
                for e in existing:
                    r = self.run(e["id"])
                    r.refresh_staff()
                    if r.state["status"] not in TERMINAL:
                        return e["id"], False
            media = self.uploads(buyer, uploads)
            ident = uuid.uuid4().hex
            d = self.path / "runs" / ident
            d.mkdir()
            (d / "runtime").mkdir()
            (d / "runtime/business.sqlite3").symlink_to(self.path / "business.sqlite3")
            shutil.copytree(DATA / "config", d / "config")
            token = secrets.token_urlsafe(32)
            actor = "APPLICATION:" + ident
            scope = {
                "actor_id": actor,
                "business_actor": buyer,
                "store_id": "STORE_SIM_01",
                "now": NOW,
                "orders": [o["order_id"] for o in self.orders(buyer)],
            }
            (d / "runtime/permissions.json").write_text(
                canonical({ident: {**scope, "token": token}})
            )
            model = self.models()
            meta = {
                "run_id": ident,
                "case_id": ident,
                "actor_id": actor,
                "business_token": token,
                "customer_token": secrets.token_urlsafe(32),
                "staff_token": secrets.token_urlsafe(32),
                "model_kind": getattr(model, "kind", "live_model"),
                "mode": "interactive_demo",
                "generation": self.path.name,
            }
            (d / "meta.json").write_text(canonical(meta))
            state = {
                "case_id": ident,
                "run_id": ident,
                "current_time": NOW,
                "messages": [
                    {"role": "system", "content": SYSTEM + "\n" + DEMO_SYSTEM}
                ],
                "media": [],
                "customer_claims": [],
                "verified_facts": [],
                "observed_findings": [],
                "order_candidates": [],
                "confirmed_item": None,
                "unresolved_questions": [],
                "current_customer_intent": "unknown",
                "proposal_id": None,
                "ticket_id": None,
                "handoff": False,
                "status": "ready",
                "turn": 0,
                "model_usage": [],
                "model_seconds": 0,
                "model_calls": 0,
                "final": {},
            }
            (d / "state.json").write_text(canonical(state))
            (d / "events.jsonl").write_text("")
            r = Run(d, model)
            self.runs[ident] = r
            r.receive(description, media, desired=desired, advance=False)
            body = {
                "issue": description,
                "evidence_refs": [
                    {"media_id": m["media_id"]} for m in r.state["media"]
                ],
                "customer_preference": desired,
                "uncertainties": ["材料尚待服务人员核实"],
                "next_action": "查看顾客提交材料并核实具体问题",
            }
            if chosen:
                order, item = chosen
                observed = r.call_tool("get_order", {"order_id": order["order_id"]})
                r.control.verify_purchase(
                    item_id,
                    {
                        "order_tool_observed": True,
                        "customer_clue": "已登录模拟顾客主动选择本人购买明细",
                        "source": "authenticated_demo_order_selection",
                    },
                )
                r.state["confirmed_item"] = [item_id]
                r.state["messages"].append(
                    {
                        "role": "system",
                        "content": canonical(
                            {
                                "authenticated_selected_item": item_id,
                                "order_id": order["order_id"],
                                "verified_purchase": True,
                                "pos": observed,
                            }
                        ),
                    }
                )
            r.call_tool("create_ticket", {"item_id": item_id, "body": body})
            r.save()
            with self.db() as c:
                count = c.execute("SELECT count(*) FROM applications").fetchone()[0]
                number = "QH" + str(202610230001 + count)
                c.execute(
                    "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        number,
                        buyer,
                        item_id,
                        description,
                        now(),
                        key,
                        canonical(
                            {
                                "description": description,
                                "desired": desired,
                                "item_id": item_id,
                                "uploads": uploads,
                            }
                        ),
                    ),
                )
                for uid in uploads:
                    c.execute("UPDATE uploads SET used_by=? WHERE id=?", (ident, uid))
            return ident, True

    def uploads(self, buyer, ids):
        if len(ids) > 6 or len(set(ids)) != len(ids):
            raise ValueError("每条消息最多6份不同材料")
        out = []
        with self.db() as c:
            for uid in ids:
                u = c.execute(
                    "SELECT * FROM uploads WHERE id=? AND buyer=?", (uid, buyer)
                ).fetchone()
                if not u or u["used_by"]:
                    raise ValueError("材料不可用，请重新上传")
                out.append(
                    {"path": str(self.path / "uploads" / u["path"]), "kind": u["kind"]}
                )
        return out
