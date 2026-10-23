"""Lossless journal, bounded transport context: preserve customer media and recent tool pairs."""
from .media import deduplicate_pixels


def project_messages(messages, state, recent_tool_rounds=2):
    # Preserve every actual customer turn (including pixels and exact clues), all host
    # system attestations, and recent public answers. Older tool outputs already live
    # in host state, and need not resend long JSON-encoded failed arguments forever.
    calls = [i for i,m in enumerate(messages) if m.get('role')=='assistant' and m.get('tool_calls')]
    selected = set(calls[-recent_tool_rounds:])
    ids = {c['id'] for i in selected for c in messages[i]['tool_calls']}
    finals = [i for i,m in enumerate(messages) if m.get('role')=='assistant' and not m.get('tool_calls')]
    selected.update(finals[-4:])
    projected = [m for i,m in enumerate(messages) if m.get('role') in ['system','user'] or i in selected or m.get('role')=='tool' and m.get('tool_call_id') in ids]
    return deduplicate_pixels(projected)
