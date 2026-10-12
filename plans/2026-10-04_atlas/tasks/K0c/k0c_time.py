"""Время по трекам: те же правила привязки, что k0c_attr.py; метки сообщений assistant
трека (уверенно + неуверенно) на одной оси; активное — сумма промежутков < 30 мин."""

import runpy
from collections import defaultdict
from datetime import datetime
from pathlib import Path

g = runpy.run_path(str(Path(__file__).with_name("k0c_attr.py")), run_name="lib")
times = defaultdict(set)
for proj in g["ROOT"].iterdir():
    if "Inspector-bottles" not in proj.name or proj.name.startswith("C--"):
        continue
    for p in proj.rglob("*.jsonl"):
        try:
            ev = g["load"](p)
        except OSError:
            continue
        if "subagents" in p.parts:
            f = next((e for e in ev if e[0] == "u"), None)
            if not f or g["OTHER"].search(f[2][: g["HEAD"]]):
                continue
            head = f[2][: g["HEAD"]]
            hit = (
                [t for rx, t in g["ALIAS"] if rx.search(head) and g["in_win"](t, f[1])]
                or g["tracks_in"](head, f[1])
                or g["tracks_in"](f[2], f[1])
            )
            for e in ev:
                if e[0] == "a":
                    for t in (x for x in hit if g["in_win"](x, e[1])):
                        times[t].add(e[1])
            continue
        cur = None
        for e in ev:
            if e[0] == "u":
                hit = [t for rx, t in g["ALIAS"] if rx.search(e[2]) and g["in_win"](t, e[1])] or g["tracks_in"](
                    e[2], e[1]
                )
                if hit:
                    cur = hit[-1] if len(hit) == 1 else cur if cur in hit else hit[0]
            elif cur and g["in_win"](cur, e[1]):
                times[cur].add(e[1])
for t in g["TRACKS"]:
    ts = sorted(datetime.fromisoformat(x).timestamp() for x in times[t])
    act = sum(min(b - a, 1800) for a, b in zip(ts, ts[1:]) if b - a < 1800) / 3600
    t0, t1 = datetime.fromtimestamp(ts[0]), datetime.fromtimestamp(ts[-1])
    cal = (ts[-1] - ts[0]) / 3600
    print(f"{t}\t{t0:%m-%d %H:%M} … {t1:%m-%d %H:%M}\tкалендарь {cal:.1f} ч\tактивно {act:.1f} ч")
