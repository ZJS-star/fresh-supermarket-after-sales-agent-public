"""Explicit deterministic UI software fixture. NEVER a live Agent score or visual conclusion."""

import json, re
from ..api import create_app
from .space import ROOT


class SoftwareModel:
    kind = "offline_demo_browser_software_test"
    configured = True

    def complete(self, messages, tools):
        refs = []
        for m in messages:
            if isinstance(m.get("content"), list):
                for p in m["content"]:
                    if p.get("type") == "text":
                        refs += re.findall(r"已提交证据 (\w+)", p.get("text", ""))
        if not refs:
            text = "请补充商品照片或小票，方便门店检查。"
        elif messages[-1]["role"] == "tool":
            text = "我们建议先到店检查，请查看方案后确认，门店会继续审核安排。"
        else:
            args = {
                "plan": "store_inspection",
                "issue": "顾客自主提交的问题，原因及异常数量尚待门店核实",
                "evidence_refs": [{"media_id": r} for r in dict.fromkeys(refs)],
                "uncertainties": ["软件测试不识别图片事实，需门店检查"],
                "appointment_time": "2026-10-24T10:00:00+08:00",
            }
            return {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "fixture-proposal",
                            "type": "function",
                            "function": {
                                "name": "propose_plan",
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                },
                "usage": None,
                "duration_seconds": 0,
            }
        return {
            "message": {"role": "assistant", "content": text},
            "usage": None,
            "duration_seconds": 0,
        }


app = create_app(ROOT / "software" / "runs", SoftwareModel)
