"""Cookie role-scoped interactive endpoints; never use a dataset case to create an application."""

import hashlib
import json, re, uuid
from decimal import Decimal
from pathlib import Path
from fastapi import HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .space import Space, ROOT, ACCOUNTS, STORE, NOW, TERMINAL
from .jobs import Jobs, friendly_error
from .views import view
from .. import DATA
from ..media import register, parts, ALLOWED, MAX_MEDIA_BYTES
from ..model import VisionModel


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    account: Literal["customer", "other", "merchant", "console"]


class Apply(Strict):
    request_key: str
    description: str = Field(min_length=1, max_length=4000)
    desired: Literal["refund", "exchange", "store_inspection", "unknown"] = "unknown"
    item_id: str | None = None
    uploads: list[str] = Field(default_factory=list, max_length=6)


class Send(Strict):
    request_key: str
    text: str = Field("", max_length=4000)
    uploads: list[str] = Field(default_factory=list, max_length=6)
    desired: Literal["refund", "exchange", "store_inspection", "unknown"] | None = None


class Consent(Strict):
    request_key: str
    proposal_id: str
    agree: bool


class Operation(Strict):
    request_key: str
    proposal_id: str | None = None
    operation: Literal[
        "takeover",
        "confirm_stock",
        "approve_refund",
        "approve_exchange",
        "confirm_inspection",
        "cancel",
        "close_manual",
    ]
    note: str = Field("", max_length=2000)


class Proposal(Strict):
    request_key: str
    type: Literal["refund_proposal", "exchange_proposal", "store_inspection"]
    quantity: int = Field(0, ge=0, strict=True)
    amount_yuan: str | None = None
    appointment: str | None = None
    uncertainties: str = Field("", max_length=1000)


class Retry(Strict):
    request_key: str


def attach(app, root=ROOT, model_factory=None):
    space = Space(root, model_factory)
    jobs = Jobs(space)
    app.state.demo = space
    app.state.demo_jobs = jobs

    @app.middleware("http")
    async def same_origin(request, call_next):
        origin = request.headers.get("origin")
        if (
            request.url.path.startswith("/demo/api")
            and request.method == "POST"
            and origin
            and origin.rstrip("/") != str(request.base_url).rstrip("/")
        ):
            return JSONResponse(
                status_code=403, content={"detail": "请从当前演示页面提交操作"}
            )
        return await call_next(request)

    web = Path(__file__).parent / "web"
    asset_version = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(web.iterdir()) if p.suffix in [".js", ".css"])).hexdigest()[:12]

    @app.get("/demo/assets/{filename}")
    def asset(filename: str):
        if filename not in {p.name for p in web.iterdir() if p.suffix in [".js", ".css"]}:
            raise HTTPException(404)
        text = (web / filename).read_text()
        if filename.endswith(".js"):
            text = text.replace("'./shared.js'", "'./shared.js?v=" + asset_version + "'")
        return Response(text, media_type="text/javascript" if filename.endswith(".js") else "text/css", headers={"Cache-Control": "no-cache"})

    def page(filename):
        text = (web / filename).read_text()
        text = re.sub(r'(/demo/assets/[^"?]+)(")', lambda m: m[1] + "?v=" + asset_version + m[2], text)
        return HTMLResponse(text, headers={"Cache-Control": "no-cache"})

    cookie_prefix = (
        "qh_" + hashlib.sha256(str(space.root.resolve()).encode()).hexdigest()[:8] + "_"
    )

    def cookie_name(role):
        return cookie_prefix + role

    def login(request, roles=None):
        role = request.headers.get("x-demo-role")
        cookie = {
            "customer": cookie_name("customer"),
            "merchant": cookie_name("merchant"),
            "console": cookie_name("console"),
        }.get(role, cookie_name("demo"))
        with space.db() as c:
            s = c.execute(
                "SELECT * FROM sessions WHERE token=?",
                (request.cookies.get(cookie, ""),),
            ).fetchone()
        if not s or (role and s["role"] != role):
            raise HTTPException(401, "请先选择演示身份")
        s = dict(s)
        if not role and roles and s["role"] not in roles:
            for candidate in roles:
                with space.db() as c:
                    other = c.execute(
                        "SELECT * FROM sessions WHERE token=?",
                        (request.cookies.get(cookie_name(candidate), ""),),
                    ).fetchone()
                if other:
                    s = dict(other)
                    break
        if roles and s["role"] not in roles:
            raise HTTPException(403, "当前身份无权执行此操作")
        return s

    def access(request, ident, staff=False):
        s = login(request, ["merchant"] if staff else ["customer", "merchant"])
        space.application(ident, None if s["role"] == "merchant" else s["buyer"])
        return s

    def accepted(job):
        return {"task": {"id": job["id"], "status": job["status"]}, "accepted": True}

    def state(request, ident):
        s = access(request, ident)
        return view(space, ident, s["role"] == "merchant")

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": friendly_error(exc)})

    @app.get("/")
    def customer():
        return page("customer.html")

    @app.get("/staff")
    def staff():
        return page("merchant.html")

    @app.get("/console")
    def console():
        return page("console.html")

    @app.post("/demo/api/login")
    def do_login(data: Login):
        account, buyer = ACCOUNTS[data.account]
        role = "customer" if buyer else data.account
        token = uuid.uuid4().hex + uuid.uuid4().hex
        with space.db() as c:
            c.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (token, role, buyer, space.path.name),
            )
        r = JSONResponse({"name": account, "role": role})
        r.set_cookie(cookie_name("demo"), token, httponly=True, samesite="strict")
        r.set_cookie(cookie_name(role), token, httponly=True, samesite="strict")
        return r

    @app.post("/demo/api/logout")
    def logout(request: Request):
        with space.db() as c:
            role = request.headers.get("x-demo-role", "customer")
            c.execute(
                "DELETE FROM sessions WHERE token=?",
                (request.cookies.get(cookie_name(role), ""),),
            )
        r = JSONResponse({"ok": True})
        r.delete_cookie(cookie_name("demo"))
        r.delete_cookie(cookie_name(role))
        return r

    @app.get("/demo/api/me")
    def me(request: Request):
        s = login(request)
        return {
            "role": s["role"],
            "name": next(
                v[0]
                for k, v in ACCOUNTS.items()
                if v[1] == s["buyer"] and ("customer" if v[1] else k) == s["role"]
            ),
            "store": STORE,
            "generation": space.path.name,
        }

    @app.get("/demo/api/orders")
    def orders(request: Request):
        return {"orders": space.orders(login(request, ["customer"])["buyer"])}

    @app.get("/demo/api/applications")
    def listing(request: Request):
        s = login(request, ["customer", "merchant"])
        with space.db() as c:
            ids = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM applications ORDER BY created DESC,rowid DESC"
                )
            ]
        rows = []
        for ident in ids:
            a = space.application(ident)
            if s["role"] == "customer" and a["buyer"] != s["buyer"]:
                continue
            d = view(space, ident)
            rows.append(
                {
                    k: d[k]
                    for k in [
                        "id",
                        "number",
                        "description",
                        "created",
                        "status",
                        "category",
                        "closed",
                        "item",
                        "intent",
                        "task",
                        "next_step",
                    ]
                }
            )
        return {
            "applications": rows,
            "counts": {
                k: sum(d["category"] == k for d in rows)
                for k in ["pending", "review", "customer", "completed"]
            },
        }

    @app.post("/demo/api/applications", status_code=202)
    def apply(request: Request, data: Apply):
        s = login(request, ["customer"])
        ident, created = space.create(
            s["buyer"],
            data.description,
            data.desired,
            data.item_id,
            data.uploads,
            data.request_key,
        )
        if created:
            jobs.message(ident, "customer", data.description, "initial")
            job = jobs.add(ident, "initial", {"action": "start"})
        else:
            with space.db() as c:
                job = c.execute(
                    "SELECT * FROM jobs WHERE application=? ORDER BY rowid DESC",
                    (ident,),
                ).fetchone()
        return {
            "application": ident,
            "created": created,
            **(accepted(dict(job)) if job else {}),
        }

    @app.get("/demo/api/applications/{ident}")
    def detail(request: Request, ident: str):
        return state(request, ident)

    @app.post("/demo/api/uploads")
    def upload(
        request: Request,
        file: UploadFile = File(...),
        kind: Literal["auto", "image", "receipt", "video"] = Form("auto"),
    ):
        s = login(request, ["customer"])
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED:
            raise ValueError("请选择JPG、PNG、WebP图片或MP4、MOV视频")
        data = file.file.read(MAX_MEDIA_BYTES + 1)
        if not data or len(data) > MAX_MEDIA_BYTES:
            raise ValueError("单份材料不能为空且不能超过25MB")
        uid = uuid.uuid4().hex
        dest = space.path / "uploads" / (uid + suffix)
        dest.write_bytes(data)
        try:
            rec = register(dest, space.path / "uploads", uid, kind)
            parts(rec, space.path / "uploads")
        except Exception:
            dest.unlink(missing_ok=True)
            raise ValueError(
                "这份材料无法读取，请换一份清晰图片或3分钟以内的视频"
            ) from None
        with space.db() as c:
            c.execute(
                "INSERT INTO uploads VALUES (?,?,?,?,?,NULL)",
                (uid, s["buyer"], dest.name, rec["kind"], (file.filename or "")[:100]),
            )
        return {"id": uid, "kind": rec["kind"]}

    @app.get("/demo/api/uploads/{uid}")
    def upload_preview(request: Request, uid: str):
        s = login(request, ["customer"])
        with space.db() as c:
            u = c.execute(
                "SELECT * FROM uploads WHERE id=? AND buyer=?", (uid, s["buyer"])
            ).fetchone()
        if not u:
            raise HTTPException(404, "材料不存在")
        return FileResponse(space.path / "uploads" / u["path"])

    @app.post("/demo/api/applications/{ident}/messages", status_code=202)
    def send(request: Request, ident: str, data: Send):
        s = access(request, ident)
        action = "staff_message" if s["role"] == "merchant" else "message"
        if not data.text.strip() and not data.uploads:
            raise ValueError("请先输入文字或选择材料")
        if action == "staff_message" and data.uploads:
            raise ValueError("门店回复暂只支持文字")
        if s["role"] == "merchant":
            space.run(ident).takeover_requested.set()
        return accepted(
            jobs.add(
                ident,
                data.request_key,
                {
                    "action": action,
                    "buyer": s["buyer"],
                    **data.model_dump(exclude={"request_key"}),
                },
            )
        )

    @app.post("/demo/api/applications/{ident}/consent", status_code=202)
    def consent(request: Request, ident: str, data: Consent):
        login(request, ["customer"])
        access(request, ident)
        return accepted(
            jobs.add(
                ident,
                data.request_key,
                {"action": "consent", **data.model_dump(exclude={"request_key"})},
            )
        )

    @app.post("/demo/api/applications/{ident}/retry", status_code=202)
    def retry(request: Request, ident: str, data: Retry):
        access(request, ident)
        return accepted(jobs.add(ident, data.request_key, {"action": "retry"}))

    @app.get("/demo/api/applications/{ident}/media/{mid}")
    def media(request: Request, ident: str, mid: str):
        if not request.headers.get("x-demo-role") and request.cookies.get(
            cookie_name("merchant")
        ):
            access(request, ident, True)
        else:
            access(request, ident)
        r = space.run(ident)
        m = next((m for m in r.state["media"] if m["media_id"] == mid), None)
        if not m:
            raise HTTPException(404, "材料不存在")
        return FileResponse(r.directory / m["local_path"])

    @app.post("/demo/api/applications/{ident}/actions", status_code=202)
    def operation(request: Request, ident: str, data: Operation):
        access(request, ident, True)
        if data.operation in ["cancel", "close_manual"] and not data.note.strip():
            raise ValueError("请填写处理说明后再结束申请")
        if data.operation == "takeover":
            space.run(ident).takeover_requested.set()
        return accepted(
            jobs.add(
                ident,
                data.request_key,
                {
                    "action": "staff_action",
                    **data.model_dump(exclude={"request_key"}),
                    "proposal_id": data.proposal_id
                    or space.run(ident).state.get("proposal_id"),
                },
            )
        )

    @app.get("/demo/api/applications/{ident}/quote")
    def quote(request: Request, ident: str, quantity: int):
        access(request, ident, True)
        r = space.run(ident)
        t = r.session.get_ticket(r.state["ticket_id"])
        with r.session.db() as c:
            result = r.session._calculate(c, t["item_id"], quantity, t["ticket_id"])
        return {
            "amount_yuan": str(Decimal(result["suggested_cents"]) / 100),
            "quantity": quantity,
        }

    @app.post("/demo/api/applications/{ident}/proposal", status_code=202)
    def proposal(request: Request, ident: str, data: Proposal):
        access(request, ident, True)
        r = space.run(ident)
        t = r.session.get_ticket(r.state["ticket_id"])
        b = t["body"]
        amount = 0
        q = data.quantity
        if data.type == "refund_proposal":
            with r.session.db() as c:
                calculated = r.session._calculate(c, t["item_id"], q, t["ticket_id"])[
                    "suggested_cents"
                ]
            if data.amount_yuan is not None:
                exact = Decimal(data.amount_yuan) * 100
                if not exact.is_finite() or exact != exact.to_integral_value():
                    raise ValueError("金额最多保留两位小数")
                amount = int(exact)
            else:
                amount = calculated
        if data.type == "store_inspection":
            q = 0
        appointment = data.appointment
        if appointment:
            import datetime as dt

            parsed = dt.datetime.fromisoformat(appointment)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
            appointment = parsed.isoformat()
        body = {
            "issue": b["issue"],
            "evidence_refs": [{"media_id": m["media_id"]} for m in r.state["media"]],
            "customer_preference": r.state["current_customer_intent"],
            "uncertainties": [
                x.strip() for x in data.uncertainties.splitlines() if x.strip()
            ],
            "plan": data.type,
            "next_action": "请顾客确认方案，再由门店审核",
        }
        if appointment:
            body["appointment_time"] = appointment
        return accepted(
            jobs.add(
                ident,
                data.request_key,
                {
                    "action": "staff_proposal",
                    "body": body,
                    "quantity": q,
                    "amount_cents": amount,
                },
            )
        )

    @app.get("/demo/api/console")
    def configuration(request: Request):
        login(request, ["console"])
        m = space.models()
        with space.db() as c:
            tasks = [
                dict(r)
                for r in c.execute(
                    "SELECT id,application,status,error,updated FROM jobs ORDER BY rowid DESC LIMIT 30"
                )
            ]
        return {
            "space": space.path.name,
            "scenario_time": NOW,
            "model_configured": bool(getattr(m, "configured", False)),
            "model": getattr(getattr(m, "config", None), "model", None),
            "mode": getattr(m, "kind", "unknown"),
            "tasks": tasks,
            "archives": [p.name for p in space.root.glob("space_*") if p != space.path],
            "preset_url": "/dev-console",
            "sample_materials": [
                {"label": "占位图片（非视觉证据）", "url": "/demo/api/sample/product"},
                {"label": "演示小票（生成）", "url": "/demo/api/sample/receipt"},
            ],
        }

    @app.post("/demo/api/console/reset")
    def reset(request: Request):
        login(request, ["console"])
        generation = space.reset()
        return {"generation": generation, "history_preserved": True}

    @app.get("/demo/api/sample/{kind}")
    def sample(request: Request, kind: str):
        login(request, ["console"])
        files = {
            "product": DATA / "media/C0001/M02.jpg",
            "receipt": ROOT / "materials/receipt.png",
        }
        p = files.get(kind)
        if p and not p.exists():
            candidates = list(p.parent.glob(p.stem + ".*"))
            p = candidates[0] if candidates else p
        if not p or not p.exists():
            raise HTTPException(404, "请在项目素材目录手动选择演示材料")
        return FileResponse(p, filename="demo-" + kind + p.suffix)

    return space, jobs
