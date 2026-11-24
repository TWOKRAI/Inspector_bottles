# ruff: noqa  (одноразовый сэмплер стенда, не код продукта)
"""Стенд-сэмплер: лестница источников + съём метрик gui каждые 10 с. Только BackendDriver (штатный)."""

import ctypes
import json
import sys
import time
from backend_ctl import BackendDriver

OUT = sys.argv[1]
STAGES = [int(x) for x in sys.argv[2].split(",")]  # числа работающих источников
STAGE_S = float(sys.argv[3])  # сек съёма на ступень после прогрева
HOLD_S = float(sys.argv[4])  # доп. удержание на последней ступени
RSS_STOP = float(sys.argv[5]) * 1024**3  # стоп по RSS gui, ГБ
FREE_STOP = float(sys.argv[6]) * 1024**3  # стоп по свободной RAM, ГБ
WARM_S, STEP = 10.0, 10.0
CAMS = ["camera_0", "camera_1", "camera_2", "camera_3"]
OTHERS = ["ProcessManager", "devices"] + CAMS


class MS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_ulong), ("ml", ctypes.c_ulong)] + [
        (n, ctypes.c_ulonglong) for n in ("tp", "ap", "tpf", "apf", "tv", "av", "aev")
    ]


def free_ram():
    m = MS()
    m.l = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ap


def rss(d, p):
    m = d.introspect_memory(p)
    raw = getattr(m, "raw", m)
    r = raw.get("result", raw) if isinstance(raw, dict) else {}
    return (r.get("os") or {}).get("rss")


def snap(d, stage, label):
    t = time.time()
    st = d.get_status("gui")["result"]
    dr = st["workers"]["data_receiver"]
    rs = d.introspect_router_stats("gui")["result"]["router_stats"]
    s = {
        "t": t,
        "stage": stage,
        "label": label,
        "free_ram": free_ram(),
        "gui_rss": rss(d, "gui"),
        "gui_cpu_s": st["cpu"]["seconds_total"],
        "gui_cpu_method": st["cpu"].get("method"),
        "dr": {
            k: dr.get(k)
            for k in (
                "frames_in",
                "batches",
                "superseded",
                "pending",
                "bytes_held",
                "max_bytes_held",
                "shown",
                "max_frame_age_ms",
                "pump_busy_share",
                "qt_pending",
            )
        },
        "router": {
            k: rs.get(k)
            for k in (
                "shm_bytes_read",
                "frame_stale_drops",
                "middleware_dropped",
                "frame_torn_reads",
                "queue_data_evicted",
                "received",
                "errors",
            )
        },
        "others_rss": {p: rss(d, p) for p in OTHERS},
    }
    return s


def main():
    f = open(OUT, "a", encoding="utf-8")

    def log(s):
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
        f.flush()
        mb = lambda v: None if v is None else round(v / 2**20)
        print(
            f"S{s['stage']}/{s['label']} gui_rss={mb(s['gui_rss'])}MB free={mb(s['free_ram'])}MB cpu_s={s['gui_cpu_s']} "
            f"frames_in={s['dr']['frames_in']} shown={s['dr']['shown']} age={s['dr']['max_frame_age_ms']}",
            flush=True,
        )

    with BackendDriver(port=8765) as d:

        def stop(reason):
            print("STOP:", reason, flush=True)
            f.write(json.dumps({"stop_reason": reason, "t": time.time()}) + "\n")
            f.flush()
            print("SHUTDOWN:", d.system_shutdown(mode="graceful"), flush=True)
            sys.exit(2)

        def watch(s):
            if s["gui_rss"] and s["gui_rss"] > RSS_STOP:
                stop(f"gui_rss {s['gui_rss'] / 2**20:.0f} MB > limit")
            if s["free_ram"] < FREE_STOP:
                stop(f"free_ram {s['free_ram'] / 2**20:.0f} MB < limit")

        for i, n in enumerate(STAGES):
            for j, c in enumerate(CAMS):
                cmd = "worker.start" if j < n else "worker.stop"
                r = d.send_command(c, cmd, {"worker_name": "source_producer_synthetic_frame_source"})
                print("cmd", c, cmd, str(r.get("result") or r)[:150].replace("\n", " "), flush=True)
            t0 = time.time()
            print(f"=== stage {n} sources: warmup {WARM_S}s", flush=True)
            while time.time() - t0 < WARM_S:
                time.sleep(2)
                watch(snap(d, n, "warm"))
            dur = STAGE_S + (HOLD_S if i == len(STAGES) - 1 else 0)
            t0 = time.time()
            k = 0
            while True:
                s = snap(d, n, "meas")
                log(s)
                watch(s)
                k += 1
                if time.time() - t0 >= dur:
                    break
                time.sleep(max(0.0, t0 + k * STEP - time.time()))
        print("DONE", flush=True)


main()
