# ruff: noqa  (одноразовый сэмплер стенда, не код продукта)
"""Стенд-сэмплер 2: все источники как в рецепте, прогрев + съём каждые 10 с. Только BackendDriver."""

import ctypes
import json
import sys
import time
from backend_ctl import BackendDriver

OUT = sys.argv[1]
WARM_S = float(sys.argv[2])
MEAS_S = float(sys.argv[3])
FREE_STOP = float(sys.argv[4]) * 2**20  # МБ
RSS_STOP = float(sys.argv[5]) * 2**20  # МБ
START_RUN = len(sys.argv) > 6 and sys.argv[6] == "run_start"
STEP = 10.0
PROCS = ["gui", "ProcessManager", "devices", "camera_0", "camera_1", "camera_2", "camera_3"]


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


def snap(d, label):
    t = time.time()
    st = d.get_status("gui")["result"]
    dr = st["workers"].get("data_receiver", {})
    rs = d.introspect_router_stats("gui")["result"]["router_stats"]
    return {
        "t": t,
        "label": label,
        "free_ram": free_ram(),
        "gui_cpu_s": st["cpu"]["seconds_total"],
        "gui_cpu_cores": st["cpu"].get("cores"),
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
                "frame_restore_failures",
                "recv_middleware_count",
                "send_middleware_count",
                "queue_data_evicted",
                "received",
                "errors",
            )
        },
        "rss": {p: rss(d, p) for p in PROCS},
    }


def main():
    f = open(OUT, "a", encoding="utf-8")
    mb = lambda v: None if v is None else round(v / 2**20)

    def log(s):
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
        f.flush()
        print(
            f"{s['label']} free={mb(s['free_ram'])}MB rss={ {k: mb(v) for k, v in s['rss'].items()} } "
            f"cpu_s={s['gui_cpu_s']} in={s['dr']['frames_in']} shown={s['dr']['shown']} age={s['dr']['max_frame_age_ms']}",
            flush=True,
        )

    with BackendDriver(port=8765) as d:

        def stop(reason, s):
            print("STOP:", reason, "RSS МБ по процессам:", {k: mb(v) for k, v in s["rss"].items()}, flush=True)
            f.write(json.dumps({"stop_reason": reason, "t": time.time()}) + "\n")
            f.flush()
            print("SHUTDOWN:", d.system_shutdown(mode="graceful"), flush=True)
            sys.exit(2)

        def watch(s):
            if s["rss"]["gui"] and s["rss"]["gui"] > RSS_STOP:
                stop("gui_rss > лимита", s)
            if s["free_ram"] < FREE_STOP:
                stop(f"free_ram {mb(s['free_ram'])} МБ < лимита", s)

        print(
            "PLUGINS_gui:", json.dumps(d.introspect_plugins("gui"), ensure_ascii=False, default=str)[:1500], flush=True
        )
        s = snap(d, "pre_frames")
        log(s)
        watch(s)
        if START_RUN:
            print("run_start:", str(d.run_start())[:300], flush=True)
        t0 = time.time()
        k = 0
        while time.time() - t0 < WARM_S + MEAS_S:
            k += 1
            time.sleep(max(0.0, t0 + k * STEP - time.time()))
            s = snap(d, "warm" if time.time() - t0 <= WARM_S else "meas")
            log(s)
            watch(s)
        print("DONE", flush=True)


main()
