"""Interactive demo software checks; no live model performance claims."""

import time, json
from fastapi.testclient import TestClient
from agent_mvp.api import create_app


class Quiet:
    kind = "offline_demo_software_test"
    configured = True

    def complete(self, messages, tools):
        return {
            "message": {
                "role": "assistant",
                "content": "请补充清晰照片和有问题的数量。",
            },
            "usage": None,
            "duration_seconds": 0,
        }


def client(tmp_path):
    return TestClient(create_app(tmp_path / "runs", Quiet))


def auth(c, who="customer"):
    assert c.post("/demo/api/login", json={"account": who}).status_code == 200


def create(c, key="initial", item="QH1022001-1", uploads=None):
    r = c.post(
        "/demo/api/applications",
        json={
            "request_key": key,
            "description": "果肉看起来不对，想先检查",
            "item_id": item,
            "desired": "store_inspection",
            "uploads": uploads or [],
        },
    )
    assert r.status_code == 202, r.text
    return r.json()["application"]


def settle(c, ident):
    for _ in range(200):
        s = c.get("/demo/api/applications/" + ident).json()
        if not s.get("task"):
            return s
        time.sleep(0.01)
    raise AssertionError("task did not settle")


def test_blank_application_shared_business_and_role_scope(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        s = settle(c, a)
        space = c.app.state.demo
        run = space.run(a)
        assert len(run.state["customer_claims"]) == 1 and run.state["media"] == []
        assert "果肉看起来不对" in run.state["customer_claims"][0]["text"]
        assert run.meta["case_id"] == a
        assert (
            run.directory / "runtime/business.sqlite3"
        ).resolve() == space.path / "business.sqlite3"
        assert create(c) == a
        b = create(c, "second", "QH1022002-1")
        settle(c, b)
        assert len(c.get("/demo/api/applications").json()["applications"]) == 2
        assert (
            c.post(
                "/demo/api/applications/" + a + "/actions",
                json={"request_key": "x", "operation": "takeover"},
            ).status_code
            == 403
        )
        auth(c, "other")
        assert c.get("/demo/api/applications/" + a).status_code == 422
        assert c.get("/demo/api/applications").json()["applications"] == []
        assert (
            c.post(
                "/demo/api/applications",
                json={
                    "request_key": "bad",
                    "description": "x",
                    "item_id": "QH1022001-1",
                },
            ).status_code
            == 422
        )
        auth(c, "merchant")
        assert len(c.get("/demo/api/applications").json()["applications"]) == 2
        c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "staff", "text": "门店已收到，请带实物到店。"},
        )
        s = settle(c, a)
        assert s["manual"]
        assert any(m["role"] == "staff" for m in s["messages"])
        assert s["internal"]["mode"].startswith("offline_")
        auth(c)
        s = c.get("/demo/api/applications/" + a).json()
        assert "internal" not in s
        assert any("请带实物" in m["text"] for m in s["messages"])


def test_serial_duplicate_tasks_and_closed_guard(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        settle(c, a)
        payload = {"request_key": "same", "text": "补充：不确定重量"}
        x = c.post("/demo/api/applications/" + a + "/messages", json=payload).json()
        y = c.post("/demo/api/applications/" + a + "/messages", json=payload).json()
        assert x["task"]["id"] == y["task"]["id"]
        settle(c, a)
        assert (
            sum(
                "补充：" in m["text"]
                for m in c.app.state.demo.run(a).state["customer_claims"]
            )
            == 1
        )
        assert (
            c.post(
                "/demo/api/applications/" + a + "/messages",
                json={"request_key": "empty"},
            ).status_code
            == 422
        )
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/actions",
            json={
                "request_key": "close",
                "operation": "close_manual",
                "note": "顾客已到店检查，协商结束。",
            },
        )
        settle(c, a)
        auth(c)
        c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "late", "text": "继续"},
        )
        s = settle(c, a)
        assert s["closed"]
        assert s["failure"]


def test_simultaneous_role_cookies_upload_batch_and_resume(tmp_path):
    from PIL import Image
    import io

    with client(tmp_path) as c:
        auth(c)
        auth(c, "merchant")
        customer = {"X-Demo-Role": "customer"}
        merchant = {"X-Demo-Role": "merchant"}
        assert c.get("/demo/api/me", headers=customer).json()["role"] == "customer"
        assert c.get("/demo/api/me", headers=merchant).json()["role"] == "merchant"
        buf = io.BytesIO()
        Image.new("RGB", (60, 60), "green").save(buf, format="PNG")
        uploads = []
        for _ in range(2):
            r = c.post(
                "/demo/api/uploads",
                headers=customer,
                files={"file": ("a.png", buf.getvalue(), "image/png")},
                data={"kind": "image"},
            )
            assert r.status_code == 200
            uploads.append(r.json()["id"])
        assert (
            c.post(
                "/demo/api/uploads",
                headers=customer,
                files={"file": ("x.png", b"broken", "image/png")},
            ).status_code
            == 422
        )
        r = c.post(
            "/demo/api/applications",
            headers=customer,
            json={
                "request_key": "batch",
                "description": "两张照片一次提交",
                "uploads": uploads,
            },
        )
        a = r.json()["application"]
        for _ in range(100):
            s = c.get("/demo/api/applications/" + a, headers=customer).json()
            if not s["task"]:
                break
            time.sleep(0.01)
        run = c.app.state.demo.run(a)
        assert len(run.state["media"]) == 2
        assert len(run.state["customer_claims"]) == 1
        assert (
            c.post(
                "/demo/api/applications/" + a + "/actions",
                headers=customer,
                json={"request_key": "bad", "operation": "takeover"},
            ).status_code
            == 403
        )
        root = c.app.state.demo.root
    # A fresh app reopens the same space and durable history.
    from agent_mvp.demo.space import Space

    restored = Space(root, Quiet)
    assert restored.application(a)
    assert len(restored.run(a).state["media"]) == 2


def test_shared_refund_history_and_proposal_version_invalidation(tmp_path):
    with client(tmp_path) as c:
        from PIL import Image
        import io

        auth(c)
        buf = io.BytesIO()
        Image.new("RGB", (60, 60), "green").save(buf, format="PNG")
        u = c.post(
            "/demo/api/uploads",
            files={"file": ("photo.png", buf.getvalue(), "image/png")},
        ).json()["id"]
        a = create(c, uploads=[u])
        settle(c, a)
        auth(c, "merchant")
        r = c.post(
            "/demo/api/applications/" + a + "/proposal",
            json={"request_key": "refund", "type": "refund_proposal", "quantity": 1000},
        )
        assert r.status_code == 202, r.text
        s = settle(c, a)
        p1 = s["plan"]["id"]
        auth(c)
        c.post(
            "/demo/api/applications/" + a + "/consent",
            json={"request_key": "agree1", "proposal_id": p1, "agree": True},
        )
        s = settle(c, a)
        assert s["plan"]["consent"] == "agreed"
        assert s["status"] == "待门店处理"
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/proposal",
            json={
                "request_key": "changed",
                "type": "store_inspection",
                "quantity": 0,
                "appointment": "2026-10-24T10:00",
            },
        )
        s = settle(c, a)
        p2 = s["plan"]["id"]
        assert p2 != p1 and s["plan"]["needs_confirmation"]
        auth(c)
        c.post(
            "/demo/api/applications/" + a + "/consent",
            json={"request_key": "stale", "proposal_id": p1, "agree": True},
        )
        s = settle(c, a)
        assert s["plan"]["consent"] == "pending"
        # Replace with refund again, confirm current version, execute once and observe shared history.
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/proposal",
            json={
                "request_key": "refund2",
                "type": "refund_proposal",
                "quantity": 1000,
            },
        )
        s = settle(c, a)
        pid = s["plan"]["id"]
        auth(c)
        c.post(
            "/demo/api/applications/" + a + "/consent",
            json={"request_key": "agree2", "proposal_id": pid, "agree": True},
        )
        settle(c, a)
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/actions",
            json={"request_key": "execute", "operation": "approve_refund"},
        )
        s = settle(c, a)
        assert s["closed"], s
        auth(c)
        b = create(c, "followup")
        s = settle(c, b)
        assert b != a
        r = c.app.state.demo.run(b)
        history = r.session.get_after_sales("QH1022001-1")
        assert (
            history["refunded_quantity"] == 1000
            and history["remaining_quantity"] == 1784
        )
        assert len(history["history"]) == 1


def test_reset_retains_old_space_and_evaluation_db_stays_isolated(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        settle(c, a)
        old = c.app.state.demo.path
        auth(c, "console")
        r = c.post("/demo/api/console/reset", json={})
        assert r.status_code == 200
        assert (old / "runs" / a / "events.jsonl").exists()
        auth(c)
        assert c.get("/demo/api/applications").json()["applications"] == []


def test_queued_restart_recovers_already_received_input_without_duplicate(tmp_path):
    from agent_mvp.demo.jobs import Jobs
    from controls import canonical
    from agent_mvp.demo.space import now

    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        settle(c, a)
        space = c.app.state.demo
        run = space.run(a)
        jobid = "interrupted"
        run.receive(
            "崩溃前收到的补充", advance=False, response={"demo_request_id": jobid}
        )
        n = len(run.state["customer_claims"])
        with space.db() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                (
                    jobid,
                    a,
                    "interrupted",
                    canonical(
                        {
                            "action": "message",
                            "buyer": "BUYER_LIN",
                            "text": "崩溃前收到的补充",
                            "uploads": [],
                        }
                    ),
                    "running",
                    None,
                    now(),
                    now(),
                ),
            )
        restarted = Jobs(space)
        try:
            for _ in range(100):
                with space.db() as db:
                    status = db.execute(
                        "SELECT status FROM jobs WHERE id=?", (jobid,)
                    ).fetchone()[0]
                if status not in ["queued", "running"]:
                    break
                time.sleep(0.01)
            assert status == "done"
            assert len(run.state["customer_claims"]) == n
        finally:
            restarted.close()
        assert (
            c.post(
                "/demo/api/login",
                json={"account": "merchant"},
                headers={"Origin": "https://external.invalid"},
            ).status_code
            == 403
        )


def test_demo_cookie_namespaces_do_not_collide_between_services(tmp_path):
    with client(tmp_path / "first") as one, client(tmp_path / "second") as two:
        auth(one)
        two.cookies.update(one.cookies)
        auth(two)
        one.cookies.update(two.cookies)
        assert (
            one.get("/demo/api/me", headers={"X-Demo-Role": "customer"}).status_code
            == 200
        )
        assert (
            two.get("/demo/api/me", headers={"X-Demo-Role": "customer"}).status_code
            == 200
        )


def test_blank_create_never_reads_dataset_cases_or_hidden_answers(
    tmp_path, monkeypatch
):
    from pathlib import Path

    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert not any(
            p in str(path)
            for p in ["/oracle/", "/customer_private/", "/agent_visible/"]
        )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        s = settle(c, a)
        assert s["media"] == []


def test_failed_staff_proposal_does_not_publish_customer_error(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c, item="QH1022002-1")
        settle(c, a)
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/proposal",
            json={
                "request_key": "out-of-stock",
                "type": "exchange_proposal",
                "quantity": 1,
            },
        )
        s = settle(c, a)
        assert s["failure"]
        auth(c)
        assert c.get("/demo/api/applications/" + a).json()["failure"] is None


def test_manual_takeover_suppresses_automatic_outbound_messages(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        settle(c, a)
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "staff", "text": "门店已接待，请补充。"},
        )
        settle(c, a)
        auth(c)
        before = c.get("/demo/api/applications/" + a).json()
        auto = sum(m["role"] == "service" for m in before["messages"])
        calls = c.app.state.demo.run(a).state["model_calls"]
        c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "manual-customer", "text": "我稍后带实物到店"},
        )
        after = settle(c, a)
        assert sum(m["role"] == "service" for m in after["messages"]) == auto
        assert c.app.state.demo.run(a).state["model_calls"] == calls


def test_different_click_keys_dedupe_same_active_operation(tmp_path):
    class Slow(Quiet):
        def complete(self, messages, tools):
            time.sleep(0.1)
            return super().complete(messages, tools)

    with TestClient(create_app(tmp_path / "runs", Slow)) as c:
        auth(c)
        a = create(c)
        first = c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "click1", "text": "稍后到店"},
        ).json()
        second = c.post(
            "/demo/api/applications/" + a + "/messages",
            json={"request_key": "click2", "text": "稍后到店"},
        ).json()
        assert first["task"]["id"] == second["task"]["id"]
        settle(c, a)
        assert len(c.app.state.demo.run(a).state["customer_claims"]) == 2


def test_console_optional_downloads_are_readable_and_scoped(tmp_path, monkeypatch):
    import agent_mvp.demo.api as demo_api
    from PIL import Image

    root = tmp_path / "assets"
    (root / "materials").mkdir(parents=True)
    Image.new("RGB", (40, 40), "white").save(root / "materials/receipt.png")
    monkeypatch.setattr(demo_api, "ROOT", root)
    with client(tmp_path) as c:
        auth(c)
        assert (
            c.get(
                "/demo/api/sample/product", headers={"X-Demo-Role": "customer"}
            ).status_code
            == 403
        )
        auth(c, "console")
        assert c.get("/demo/api/sample/product").status_code == 200
        assert c.get("/demo/api/sample/receipt").status_code == 200


def test_staff_approval_is_bound_to_displayed_proposal_version(tmp_path):
    with client(tmp_path) as c:
        auth(c)
        a = create(c)
        settle(c, a)
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/proposal",
            json={
                "request_key": "plan",
                "type": "store_inspection",
                "appointment": "2026-10-24T10:00",
            },
        )
        s = settle(c, a)
        current = s["plan"]["id"]
        auth(c)
        c.post(
            "/demo/api/applications/" + a + "/consent",
            json={"request_key": "consent", "proposal_id": current, "agree": True},
        )
        settle(c, a)
        auth(c, "merchant")
        c.post(
            "/demo/api/applications/" + a + "/actions",
            json={
                "request_key": "old-approval",
                "operation": "confirm_inspection",
                "proposal_id": "obsolete-displayed-version",
            },
        )
        s = settle(c, a)
        assert not s["closed"] and s["plan"]["id"] == current
        assert s["failure"]
