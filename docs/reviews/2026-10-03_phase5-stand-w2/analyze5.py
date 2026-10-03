# ruff: noqa  # артефакт замера 2026-10-03: код сохранён как есть, им сняты числа отчёта; переносится в scripts/stand_gate (Task 5.6)
import json
import re
import sys
from pathlib import Path

M = Path(__file__).parent / "raw"
EV = re.compile(r"event inspection: (\w+): (.*?) trace=([0-9a-f]{32})")
MK = re.compile(r"\((lag|stale_restore|stale_exec|door)@(\w+)\)")


def w(rec, key):
    tot = 0
    for ws in rec["workers"].values():
        v = ws.get(key)
        if isinstance(v, (int, float)) and key not in ("queue_wait_ms", "effective_hz"):
            tot += v
    return tot


def born(rec):
    return (
        w(rec, "not_inspected_lag")
        + w(rec, "not_inspected_stale_restore")
        + w(rec, "not_inspected_stale_exec")
        + rec["rs"].get("not_inspected_door", 0)
    )


def own_in(rec):  # маркеры процесса, родившиеся ДО его исполнителя (идут в handled)
    return w(rec, "not_inspected_lag") + w(rec, "not_inspected_stale_restore") + w(rec, "not_inspected_stale_exec")


def drops(rec):
    rs = rec["rs"]
    return (
        w(rec, "lag_dropped_items")
        + rs.get("frame_stale_drops", 0)
        + rs.get("frame_torn_reads", 0)
        + rs.get("frame_restore_failures", 0)
    )


def has_ni(rec):
    return (
        any(
            k.startswith("not_inspected")
            for ws in rec["workers"].values()
            for k in ws.get("_keys", [])
            if k.startswith("not_inspected")
        )
        or "not_inspected_door" in rec["rs"]
    )


def journal(case_dir):
    logs = list(Path(case_dir, "logs").rglob("messages.log"))
    rows = []
    for f in logs:
        for m in EV.finditer(f.read_text(encoding="utf-8", errors="replace")):
            rows.append(m.groups())
    traces = [r[2] for r in rows]
    mk = [MK.search(r[1]) for r in rows]
    by = {}
    for m in mk:
        if m:
            by[f"{m.group(1)}@{m.group(2)}"] = by.get(f"{m.group(1)}@{m.group(2)}", 0) + 1
    return {
        "rows": len(rows),
        "distinct": len(set(traces)),
        "dup": len(traces) - len(set(traces)),
        "markers": sum(1 for m in mk if m),
        "by": by,
        "reject": sum(1 for r in rows if r[0] == "reject"),
        "pass": sum(1 for r in rows if r[0] == "pass"),
    }


def sub(a, b):
    out = {"workers": {}, "rs": {k: a["rs"].get(k, 0) - b["rs"].get(k, 0) for k in a["rs"]}}
    for wn, ws in a["workers"].items():
        out["workers"][wn] = {
            k: (v - b["workers"].get(wn, {}).get(k, 0) if isinstance(v, (int, float)) else v) for k, v in ws.items()
        }
    return out


def case(tag):
    r = json.loads((M / f"{tag}.json").read_text(encoding="utf-8"))
    print(f"\n=== {tag} overflow={r['overflow']} delay={r['reject_delay_ms']} window={r.get('window_s')}s")
    for label, a, b in (("окно s1-s0", r["s1"], r["s0"]), ("итог s2", r["s2"], None)):
        print(f"  [{label}]")
        for p in ("processor", "inspector", "renderer", "storage"):
            rec = sub(a[p], b[p]) if b else a[p]
            ni = has_ni(a[p])
            print(
                f"    {p:9s} born={born(rec):5d} drops={drops(rec):5d} diff={born(rec) - drops(rec):4d} "
                f"handled={w(rec, 'not_inspected_handled'):5d} own_in={own_in(rec):4d} "
                f"stale_exec={w(rec, 'not_inspected_stale_exec')} door={rec['rs'].get('door_drops', 0)}/{rec['rs'].get('not_inspected_door', '-')} "
                f"evicted={rec['rs'].get('queue_data_evicted', 0)} ni_keys={ni}"
            )
        P = sub(a["processor"], b["processor"]) if b else a["processor"]
        for nb in ("inspector", "renderer"):
            N = sub(a[nb], b[nb]) if b else a[nb]
            got = w(N, "not_inspected_handled") - own_in(N)
            print(
                f"    сосед {nb}: handled-own_in={got} born(processor)={born(P)} разница={born(P) - got} "
                f"(evicted processor={P['rs'].get('queue_data_evicted', 0)})"
            )
    j = journal(r["case_dir"])
    cam = r.get("camera_before_pause") or {}
    cam_cyc = next((ws.get("cycles") for ws in cam.get("workers", {}).values() if "cycles" in ws), None)
    insp = r["s2"]["inspector"]
    se_insp = w(insp, "not_inspected_stale_exec")
    post_chain = se_insp - j["by"].get("stale_exec@inspector", 0)
    tomb = post_chain + insp["rs"].get("not_inspected_door", 0)
    ev = sum(r["s2"][p]["rs"].get("queue_data_evicted", 0) for p in ("camera_0", "processor"))
    print(f"  журнал: {j}")
    print(
        f"  кадров камеры≈{cam_cyc}; distinct={j['distinct']}; надгробий inspector (post-chain stale_exec + door)={tomb}; "
        f"evicted camera+processor={ev}; остаток=камера−distinct={None if cam_cyc is None else cam_cyc - j['distinct']}"
    )
    print(f"  hz: {r['hz_median']}")
    print(
        "  queue_wait_ms s1: "
        + ", ".join(
            f"{p}={r['s1'][p]['workers'].get('pipeline_executor', {}).get('queue_wait_ms')}"
            for p in ("processor", "inspector", "renderer", "storage")
        )
    )
    if "pause" in r:
        p = r["pause"]
        mid = r["pause_mid"]["processor"]
        print(
            f"  пауза: {p['worker']} {p['stopped_s']} с, RSS {p['rss0'] / 2**20:.1f}→{p['rss1'] / 2**20:.1f} МиБ, дренаж {p['drain_s']} с; "
            f"mid lag={w(mid, 'not_inspected_lag')} handled={w(mid, 'not_inspected_handled')} evicted={mid['rs'].get('queue_data_evicted')}; "
            f"after handled={w(p['after']['processor'], 'not_inspected_handled')} evicted={p['after']['processor']['rs'].get('queue_data_evicted')}"
        )


# ---- Фаза 5: сводка порогов (добавлено 2026-10-03) ----
def rc(r, key):
    d = r.get(key) or {}
    while isinstance(d, dict) and "actuation_missed_items" not in d and len(d) == 1:
        d = next(iter(d.values()))
    if isinstance(d, dict) and "actuation_missed_items" not in d:
        for v in d.values():
            if isinstance(v, dict) and "actuation_missed_items" in v:
                return v
    return d


def phase5(tag):
    r = json.loads((M / f"{tag}.json").read_text(encoding="utf-8"))
    j = journal(r["case_dir"])
    cam = r.get("camera_before_pause") or {}
    cam_cyc = sum(int(ws.get("cycles") or 0) for ws in cam.get("workers", {}).values())
    verdicts = j["rows"] - j["markers"]
    print(f"\n### {tag}: start={r.get('start_s')} с, первый кадр после ready={r.get('first_frame_after_ready_s')} с")
    print(
        f"  кадров камеры={cam_cyc} строк={j['rows']} маркеров={j['markers']} вердиктов={verdicts} dup={j['dup']} by={j['by']}"
    )
    r2 = rc(r, "rc_s2") if isinstance(rc(r, "rc_s2"), dict) else {}
    ni_units = r2.get("total_not_inspected")
    if cam_cyc and ni_units is not None:
        need = 0.9 * (cam_cyc - ni_units)
        print(
            f"  D1 (единицы) вердиктов {verdicts} >= 0.9*(кадры {cam_cyc} - не проверено {ni_units})={need:.0f}: {'OK' if verdicts >= need else 'FAIL'}; "
            f"сверка inspected+not_inspected={r2.get('total_inspected', 0) + ni_units} vs кадры {cam_cyc}"
        )
    s1, s0 = r["s1"], r["s0"]
    lag_i = w(sub(s1["inspector"], s0["inspector"]), "not_inspected_lag")
    print(f"  D2 lag@inspector окно={lag_i} (<=100): {'OK' if lag_i <= 100 else 'FAIL'}")
    for k in ("rc_s1", "rc_s2"):
        d = rc(r, k)
        print(
            f"  {k}: "
            + ", ".join(
                f"{x}={d.get(x)}"
                for x in (
                    "actuation_fired_items",
                    "actuation_missed_items",
                    "actuation_late_fires",
                    "actuation_unscheduled_items",
                    "total_inspected",
                    "total_not_inspected",
                    "verdicts_written",
                )
            )
            if isinstance(d, dict)
            else f"  {k}: {d}"
        )
    ev0 = {p: s0[p]["rs"].get("queue_data_evicted", 0) for p in s0}
    st0 = {p: s0[p]["rs"].get("frame_stale_drops", 0) for p in s0}
    print(f"  S1 s0 queue_data_evicted={ev0} -> {'OK' if not any(ev0.values()) else 'FAIL'}")
    print(f"  S2 s0 frame_stale_drops={st0} -> {'OK' if not any(st0.values()) else 'FAIL'}")
    if "pause" in r:
        p = r["pause"]
        mid = r["pause_mid"]["processor"]
        aft = p["after"]["processor"]
        pre = r["s0"]["processor"]
        d_df = aft["rs"].get("errors_delivery_failed", 0) - mid["rs"].get("errors_delivery_failed", 0)
        d_ev = aft["rs"].get("queue_data_evicted", 0) - mid["rs"].get("queue_data_evicted", 0)
        print(
            f"  P1 errors_delivery_failed Δ дренаж={d_df} (всего after={aft['rs'].get('errors_delivery_failed', 0)}): {'OK' if d_df == 0 else 'FAIL'}"
        )
        print(
            f"  P2 queue_data_evicted Δ дренаж={d_ev} (всего after={aft['rs'].get('queue_data_evicted', 0)}): {'OK' if d_ev == 0 else 'FAIL'}"
        )
        drss = (p["rss1"] - p["rss0"]) / 2**20 if p.get("rss0") and p.get("rss1") else None
        print(f"  P4 ΔRSS={drss and round(drss, 2)} МиБ (<=1): {'OK' if drss is not None and drss <= 1 else 'FAIL'}")
        print(f"  P5 дренаж={p.get('drain_s')} с (<=0.1); trace={p.get('drain_trace', [])[:6]}")
        P = sub(aft, pre)
        for nb in ("inspector", "renderer"):
            N = sub(p["after"][nb], r["s0"][nb])
            got = w(N, "not_inspected_handled") - own_in(N)
            print(f"  P3 сосед {nb}: handled-own={got} born(processor)={born(P)} разница={born(P) - got}")


if __name__ == "__main__" and "--p5" in sys.argv:
    for t in [a for a in sys.argv[1:] if a != "--p5"]:
        phase5(t)
    sys.exit(0)

if __name__ == "__main__":
    for t in sys.argv[1:]:
        case(t)
