"""Проба 1.1a на Mac: harness.stop() minimal_app + опрос supervision_status во время стопа.

Запуск: PYTHONPATH=<дерево> python probe_stop10.py <N> <порт>
Печатает по прогону: время stop(), число ответов supervision_status во время стопа, макс. время ответа.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from backend_ctl.harness import BackendHarness

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8797
APP_YAML = Path("examples/minimal_app/app.yaml").resolve()


def build():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(APP_YAML)


def main():
    rows = []
    for i in range(N):
        log_dir = tempfile.mkdtemp(prefix="probe_stop_")
        os.environ["MULTIPROCESS_LOG_DIR"] = log_dir
        h = BackendHarness(launcher_factory=build, port=PORT)
        drv = h.start()
        answers = []
        shape = []
        stop_flag = threading.Event()

        def poll():
            while not stop_flag.is_set():
                t0 = time.monotonic()
                try:
                    r = drv.supervision_status(timeout=1.0)
                    if not shape: shape.append(repr(r)[:160])
                    ok = isinstance(r, dict) and (r.get("success") is True or isinstance(r.get("result"), dict))
                except Exception:
                    ok = False
                if ok:
                    answers.append(time.monotonic() - t0)
                time.sleep(0.05)

        th = threading.Thread(target=poll, daemon=True)
        th.start()
        t0 = time.monotonic()
        try:
            drv.system_shutdown()
        except Exception as exc:
            print('system_shutdown exc', repr(exc)[:120])
        h.stop()
        dt = time.monotonic() - t0
        stop_flag.set()
        th.join(2)
        did_not_stop = 0
        for p in Path(log_dir).rglob("*.log"):
            try:
                did_not_stop += p.read_text(errors="ignore").count("did not stop in")
            except OSError:
                pass
        rows.append((dt, len(answers), max(answers) if answers else 0.0, did_not_stop))
        print("shape:", shape[:1]) if i == 0 else None
        print(f"run {i + 1}: stop={dt:.2f}s answers={len(answers)} max_answer={rows[-1][2]:.3f}s did_not_stop={did_not_stop}", flush=True)

    print("max stop:", f"{max(r[0] for r in rows):.2f}s", "min answers:", min(r[1] for r in rows),
          "did_not_stop total:", sum(r[3] for r in rows))


if __name__ == "__main__":
    main()
