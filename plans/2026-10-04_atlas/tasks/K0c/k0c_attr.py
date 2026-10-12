"""K0c: токены по трекам.

Правила привязки (метод — в K0c.result.md):
- субагент: id трека в первых 400 символах промпта (или единственный трек во всём
  промпте с id в первых 1000) и время в окне — «уверенно»; иначе — «неуверенно»;
  промпт о чужой работе (OTHER) отбрасывается;
- главная сессия: каждое сообщение assistant относится к треку, названному в последнем
  промпте владельца (текст user, не tool_result), если время в окне трека;
  сессия, где за окно названо больше одного трека, — «неуверенно».
- инъекции: субагент трека, чей промпт говорит об инъекциях.
Токены дедуплицируются по message.id. fresh = input + cache_creation + output.
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"

TRACKS = {
    # id: (regex, окно начала, окно конца) — локальное время
    "Ж 1.1": (
        r"lifecycle-owner-scope.{0,30}1\.1(?![\d.a-z])|Ж ?1\.1(?![\d.])|lifecycle-1\.1",
        "2026-10-11T00:00",
        "2026-10-12T11:40",
    ),
    "Ж 1.2a": (r"1\.2a", "2026-10-12T09:00", "2026-10-12T16:10"),
    "T3.1": (r"T3\.1(?![\d.])", "2026-10-11T00:00", "2026-10-12T15:05"),
    "T3.3": (r"T3\.3(?![\d.])", "2026-10-11T00:00", "2026-10-12T14:45"),
    "Ж 0.3+0.4": (
        r"lifecycle.{0,40}0\.[34](?![\d.])|Task 0\.[34](?![\d.])|task-0\.[34]|lifecycle-0\.[34]"
        r"|qt_lifetime|Subscribers",
        "2026-10-05T12:00",
        "2026-10-05T21:40",
    ),
    "Ж T1": (
        r"task-T1|T1-gc|lifecycle.{0,40}\bT1(?![\d.])|\bT1 (—|-|гейт|р2|приёмк|C2)|\bT1\b(?![\d.])",
        "2026-10-05T21:00",
        "2026-10-07T14:00",
    ),
    "T1.2+T1.3": (r"T1\.2(?![\d])|T1\.3(?![\d])|t12-t13", "2026-09-28T00:00", "2026-09-30T16:30"),
}
# прогон матрицы инъекций — по заголовку промпта, не по слову в правилах
INJ = re.compile(r"injection-matrix|break-injection", re.I)
# чужая работа, упоминающая id трека: Атлас 1.9f, sim T2.4, страница для владельца
OTHER = re.compile(r"1\.9f|\bT2\.4\b|documentation page for the owner")
# «Task 1.2» до разделения на 1.2a/1.2b — это Ж 1.2a
ALIAS = [(re.compile(r"Task 1\.2 of plan|for Task 1\.2 of|Task 1\.2\b.{0,40}lifecycle"), "Ж 1.2a")]
HEAD = 400
COMP = {k: (re.compile(v[0]), v[1], v[2]) for k, v in TRACKS.items()}


def loc(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%dT%H:%M")


def user_text(m):
    c = m.get("content")
    if isinstance(c, str):
        return c
    out = []
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
    return "\n".join(out)


def in_win(tid, t):
    _, a, b = COMP[tid]
    return a <= t <= b


def load(path):
    """-> список событий: ('u', t, text) | ('a', t, model, (inp, cc, cr, out))"""
    ev, seen = [], {}
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if not isinstance(m, dict) or not d.get("timestamp"):
                continue
            t = loc(d["timestamp"])
            if d.get("type") == "user":
                txt = user_text(m)
                if txt:
                    ev.append(("u", t, txt))
            u = m.get("usage")
            if u:
                key = m.get("id") or d.get("requestId")
                vals = (
                    u.get("input_tokens") or 0,
                    u.get("cache_creation_input_tokens") or 0,
                    u.get("cache_read_input_tokens") or 0,
                    u.get("output_tokens") or 0,
                )
                if key in seen:
                    # строк с одним id несколько, первая — до конца стрима: берём максимум по полю
                    e = ev[seen[key]]
                    ev[seen[key]] = (e[0], e[1], e[2], tuple(max(x, y) for x, y in zip(e[3], vals)))
                    continue
                seen[key] = len(ev)
                ev.append(("a", t, m.get("model", "?"), vals))
    return ev


def tracks_in(text, t):
    return [k for k, (rx, _, _) in COMP.items() if rx.search(text) and in_win(k, t)]


def main():
    # agg[track][kind] = [fresh, cache_read, out, files]
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, set()]))
    for proj in ROOT.iterdir():
        if "Inspector-bottles" not in proj.name or proj.name.startswith("C--"):
            continue
        for p in proj.rglob("*.jsonl"):
            try:
                ev = load(p)
            except OSError:
                continue
            sub = "subagents" in p.parts
            if sub:
                first = next((e for e in ev if e[0] == "u"), None)
                if not first:
                    continue
                head = first[2][:HEAD]
                if OTHER.search(head):
                    continue
                hit = [tid for rx, tid in ALIAS if rx.search(head) and in_win(tid, first[1])] or tracks_in(
                    head, first[1]
                )
                sure = len(hit) == 1
                if not hit:
                    hit = tracks_in(first[2], first[1])
                    sure = len(hit) == 1 and COMP[hit[0]][0].search(first[2]).start() < 1000
                if not hit:
                    continue
                inj = bool(INJ.search(first[2][:200]))
                for e in ev:
                    if e[0] != "a":
                        continue
                    i, cc, cr, o = e[3]
                    for tid in hit:
                        # повторный вызов того же агента после окна — уже другая работа
                        if not in_win(tid, e[1]):
                            continue
                        kind = ("sub_inj" if inj else "sub") + ("" if sure else "?")
                        a = agg[tid][kind]
                        w = 1 / len(hit)
                        a[0] += (i + cc + o) * w
                        a[1] += cr * w
                        a[2] += o * w
                        a[3].add(p.name)
                continue
            cur, named = None, defaultdict(set)
            for e in ev:
                if e[0] == "u":
                    hit = [tid for rx, tid in ALIAS if rx.search(e[2]) and in_win(tid, e[1])] or tracks_in(e[2], e[1])
                    if OTHER.search(e[2]):
                        named["other"].add(e[1][:10])
                    for tid in hit:
                        named[tid].add(e[1][:10])
                    if hit:
                        cur = hit[-1] if len(hit) == 1 else cur if cur in hit else hit[0]
                    continue
                if cur is None or not in_win(cur, e[1]):
                    continue
                i, cc, cr, o = e[3]
                sure = len(named) == 1
                a = agg[cur]["lead" + ("" if sure else "?")]
                a[0] += i + cc + o
                a[1] += cr
                a[2] += o
                a[3].add(p.name)
    for tid in TRACKS:
        kinds = agg.get(tid, {})
        parts = [
            f"{k}: fresh {v[0] / 1e3:.0f}k, cr {v[1] / 1e6:.2f}M, out {v[2] / 1e3:.0f}k, files {len(v[3])}"
            for k, v in sorted(kinds.items())
        ]
        print(f"{tid}\n  " + "\n  ".join(parts))


if __name__ == "__main__":
    main()
