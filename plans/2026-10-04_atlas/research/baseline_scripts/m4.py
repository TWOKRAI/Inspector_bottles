# ruff: noqa: E501, E731, E741 — замерочный скрипт Task 0.6, логику не трогаем, чтобы числа baseline.md воспроизводились
import json
import glob
import os
import statistics as st
import datetime
import collections

P = "C:/Users/INNOTECH/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles"
EDIT = {
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "mcp__serena__replace_content",
    "mcp__serena__replace_symbol_body",
    "mcp__serena__insert_after_symbol",
    "mcp__serena__insert_before_symbol",
}
rows = []
types = collections.Counter()
for meta in glob.glob(P + "/*/subagents/*.meta.json"):
    try:
        m = json.load(open(meta, encoding="utf-8"))
    except Exception:
        continue
    t = m.get("agentType")
    types[t] += 1
    if t not in ("developer", "teamlead"):
        continue
    f = meta.replace(".meta.json", ".jsonl")
    if not os.path.exists(f):
        continue
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(f))
    seen = {}
    order = []
    first = None
    for line in open(f, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") != "assistant":
            continue
        msg = o.get("message", {})
        mid = msg.get("id") or o.get("uuid")
        u = msg.get("usage") or {}
        if mid not in seen:
            order.append(mid)
            seen[mid] = {"u": u, "edit": False}
        else:
            if u.get("output_tokens", 0) >= seen[mid]["u"].get("output_tokens", 0):
                seen[mid]["u"] = u
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in EDIT:
                seen[mid]["edit"] = True
    cum = 0
    fe = None
    for i, mid in enumerate(order):
        u = seen[mid]["u"]
        cum += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0)
        if seen[mid]["edit"]:
            ctx = (
                u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            )
            fe = (i + 1, ctx, cum)
            break
    if fe:
        rows.append(
            (
                mt.date().isoformat(),
                t,
                m.get("description", "")[:50],
                os.path.basename(f)[6:-6],
            )
            + fe
        )
rows.sort()
print("agent types in transcripts:", dict(types))
print("dev/teamlead with an edit:", len(rows))
for r in rows[-40:]:
    print(r)


def q(v):
    v = sorted(v)
    n = len(v)
    p = lambda k: v[min(n - 1, int(round(k * (n - 1))))]
    return dict(n=n, min=v[0], p25=p(0.25), median=st.median(v), p75=p(0.75), max=v[-1])


rr = [r for r in rows if r[0] >= "2026-08-05"]
print("window>=2026-08-05 n=", len(rr))
print("ctx_at_first_edit", q([r[5] for r in rr]))
print("cum_new_tokens_to_first_edit", q([r[6] for r in rr]))
print("turns_to_first_edit", q([r[4] for r in rr]))
