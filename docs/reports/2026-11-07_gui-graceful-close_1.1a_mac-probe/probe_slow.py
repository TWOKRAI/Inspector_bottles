"""Проба 1.1a (различающая): ребёнок с shutdown 4 с; ответы supervision_status ПОСЛЕ system.shutdown."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from backend_ctl.harness import BackendHarness

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8799
SCRATCH = Path(__file__).resolve().parent
APP_YAML = SCRATCH / "slowapp" / "app.yaml"


def build():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(APP_YAML)


def main():
    rows = []
    for i in range(N):
        log_dir = tempfile.mkdtemp(prefix="probe_slow_")
        os.environ["MULTIPROCESS_LOG_DIR"] = log_dir
        h = BackendHarness(launcher_factory=build, port=PORT)
        drv = h.start()
        samples = []  # (t_start, duration)
        stop_flag = threading.Event()

        def poll():
            while not stop_flag.is_set():
                t0 = time.monotonic()
                try:
                    r = drv.supervision_status(timeout=1.0)
                    ok = isinstance(r, dict) and r.get("type") == "response" and not r.get("error")
                except Exception:
                    ok = False
                if ok:
                    samples.append((t0, time.monotonic() - t0))
                time.sleep(0.05)

        th = threading.Thread(target=poll, daemon=True)
        th.start()
        time.sleep(1.0)
        t_sd = time.monotonic()
        res = drv.system_shutdown(wait_timeout=30.0)
        dt = time.monotonic() - t_sd
        stop_flag.set()
        th.join(2)
        h.stop()
        after = [d for (t, d) in samples if t > t_sd]
        dns = 0
        for p in Path(log_dir).rglob("*.log"):
            try:
                dns += p.read_text(errors="ignore").count("did not stop in")
            except OSError:
                pass
        rows.append((dt, len(after), max(after) if after else 0.0, dns))
        print(f"run {i + 1}: shutdown={dt:.2f}s answers_after={len(after)} max={rows[-1][2]:.3f}s did_not_stop={dns} accepted={res.get('accepted')}", flush=True)
    print("min answers_after:", min(r[1] for r in rows), "max shutdown:", f"{max(r[0] for r in rows):.2f}s")


if __name__ == "__main__":
    main()
