"""Deterministic demo integrity report, not dataset oracle evaluation or model scoring."""

import argparse, json, sqlite3
from pathlib import Path
from .space import Space, ROOT
from .views import read_events


def audit(space, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    trace_dir = output.parent / "live_traces"
    trace_dir.mkdir(exist_ok=True)
    results = []
    with space.db() as c:
        applications = [
            dict(r)
            for r in c.execute("SELECT * FROM applications ORDER BY created,rowid")
        ]
    for app in applications:
        run = space.run(app["id"])
        run.refresh_staff()
        trace = json.loads(run.export().read_text())
        errors = []
        s = run.state
        t = run.session.get_ticket(s["ticket_id"])
        p = run.session.get_proposal(s["proposal_id"]) if s["proposal_id"] else None
        if run.state["customer_claims"][0]["text"] != app["description"]:
            errors.append("initial_complaint_differs_from_user_submission")
        if t["item_id"] != app["item_id"]:
            errors.append("selected_item_differs_from_ticket")
        for media in s["media"]:
            if (
                not (run.directory / media["local_path"])
                .resolve()
                .is_relative_to((run.directory / "submitted").resolve())
            ):
                errors.append("unsubmitted_media_path")
        if s["status"] == "human_takeover" and not t["body"].get("handoff_reason"):
            errors.append("missing_staff_handoff_reason")
        with space.business() as c:
            if app["item_id"]:
                buyer = c.execute(
                    "SELECT o.actor_id FROM orders o JOIN order_items i USING(order_id) WHERE item_id=?",
                    (app["item_id"],),
                ).fetchone()[0]
                if buyer != app["buyer"]:
                    errors.append("foreign_customer_order")
            if t["status"] in [
                "pending_review",
                "refunded_simulated",
                "exchanged_simulated",
                "inspection_confirmed",
            ]:
                if (
                    not p
                    or p["consent"] != "agreed"
                    or t["body"].get("proposal_id") != p["proposal_id"]
                ):
                    errors.append("missing_current_consent")
                if (
                    t["body"]["plan"] in ["store_inspection", "exchange_proposal"]
                    and t["amount_cents"] != 0
                ):
                    errors.append("nonrefund_has_refund_amount")
            action = {
                "inspection_confirmed": "confirm_inspection",
                "refunded_simulated": "approve_refund",
                "exchanged_simulated": "approve_exchange",
            }.get(t["status"])
            if (
                action
                and not c.execute(
                    "SELECT 1 FROM audit WHERE object_id=? AND action=?",
                    (t["ticket_id"], action),
                ).fetchone()
            ):
                errors.append("completion_without_staff_audit")
        (trace_dir / (app["number"] + ".jsonl")).write_text(
            json.dumps(trace, ensure_ascii=False) + "\n"
        )
        results.append(
            {
                "application": app["number"],
                "local_id": app["id"],
                "mode": run.meta["model_kind"],
                "state": t["status"],
                "submitted_media_count": len(s["media"]),
                "customer_turns": len(s["customer_claims"]),
                "model_responses": s["model_calls"],
                "model_seconds": (
                    s["model_seconds"]
                    if run.meta["model_kind"] == "live_model"
                    else None
                ),
                "model_usage": s["model_usage"] or None,
                "deterministic_errors": errors,
                "ticket": t,
                "proposal": p,
                "human_semantic_review": None,
                "task_success": None,
            }
        )
    report = {
        "kind": "interactive_demo_integrity_not_model_benchmark",
        "space": space.path.name,
        "applications": results,
        "status": (
            "PASS" if all(not r["deterministic_errors"] for r in results) else "FAIL"
        ),
        "human_semantic_review": "pending",
        "task_success_rate": None,
        "warning": "Small manually steered live development sessions; offline browser fixtures are separate. No oracle accessed, no generalization or semantic success score.",
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument(
        "--output", type=Path, default=Path("reports/demo/live_validation.json")
    )
    args = p.parse_args()
    r = audit(Space(args.root), args.output)
    print(
        json.dumps(
            {
                "status": r["status"],
                "applications": len(r["applications"]),
                "semantic_review": r["human_semantic_review"],
            },
            ensure_ascii=False,
        )
    )
