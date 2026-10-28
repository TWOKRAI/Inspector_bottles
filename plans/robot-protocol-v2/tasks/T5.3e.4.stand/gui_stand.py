"""GUI-стенд T5.3e.4: сим v2 + настоящий GUI (frontend/run.py) с вкладкой робота.

Подъём один (боевой вход, память project_gui_stand_production_entry_only): INSPECTOR_GUI_UNATTENDED=1.
Сим и манифест - из `../T5.3e.stand/` (копия манифеста делается `run_stand.py --prepare-only`).

    gui_stand.py start   - preflight портов, сим, GUI; пишет pids.json в каталог прогона; печатает пути
    gui_stand.py stop    - system_shutdown не здесь (его шлёт лид через backend_ctl); добивает по PID из pids.json

Запуск - через machine_gate.sh в окне stand; команда `start` возвращается после старта процессов (не ждёт GUI).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess  # nosec B404 - стенд запускает сим и GUI
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parents[3]
SIM = HERE.parent / "T5.3e.stand" / "sim_v2.py"
STAND_ROOT = Path(os.environ.get("TEMP", ".")) / "t53e-stand"
PORTS = {"sim": 5021, "backend_ctl": 8765, "qt_probe": 9142}


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start(args: argparse.Namespace) -> int:
    busy = {k: p for k, p in PORTS.items() if port_busy(p)}
    if busy:
        print(f"preflight: заняты порты {busy}", file=sys.stderr)
        return 2
    manifest = STAND_ROOT / "manifest" / "app.yaml"
    if not manifest.exists():
        print(f"нет {manifest}: сначала run_stand.py --prepare-only", file=sys.stderr)
        return 2
    run_dir = STAND_ROOT / f"gui-{time.strftime('%Y%m%d-%H%M%S')}"
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "logs").mkdir()
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(WORKTREE),
        PYTHONUTF8="1",
        BACKEND_CTL="1",
        INSPECTOR_GUI_UNATTENDED="1",
        QT_MCP_PROBE="1",
        INSPECTOR_MANIFEST=str(manifest),
        INSPECTOR_DATA_DIR=str(run_dir / "data"),
        MULTIPROCESS_LOG_DIR=str(run_dir / "logs"),
        INSPECTOR_LOG_DIR=str(run_dir / "logs"),
    )
    env.pop("INSPECTOR_HEADLESS", None)
    py = str(args.python)
    sim = subprocess.Popen(  # nosec B603
        [py, str(SIM), "--log", str(run_dir / "sim.log"), "--ctl", str(run_dir / "sim.ctl"), "--delay-ms", "0"],
        cwd=run_dir,
        env=env,
        stdout=(run_dir / "sim.out.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    gui = subprocess.Popen(  # nosec B603
        [py, str(WORKTREE / "multiprocess_prototype" / "frontend" / "run.py")],
        cwd=run_dir,
        env=env,
        stdout=(run_dir / "gui.out.log").open("w"),
        stderr=subprocess.STDOUT,
    )
    (STAND_ROOT / "gui_pids.json").write_text(
        json.dumps({"run_dir": str(run_dir), "sim": sim.pid, "gui": gui.pid}), encoding="utf-8"
    )
    print(json.dumps({"run_dir": str(run_dir), "sim_pid": sim.pid, "gui_pid": gui.pid}))
    return 0


def stop(_args: argparse.Namespace) -> int:
    path = STAND_ROOT / "gui_pids.json"
    if not path.exists():
        print("нет gui_pids.json")
        return 0
    info = json.loads(path.read_text(encoding="utf-8"))
    for name in ("gui", "sim"):
        subprocess.run(["taskkill", "/PID", str(info[name]), "/T", "/F"], capture_output=True)  # nosec B603 B607
    left = {k: p for k, p in PORTS.items() if port_busy(p)}
    print(f"добито по PID {info['gui']}, {info['sim']}; заняты порты: {left or 'нет'}")
    return 0 if not left else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["start", "stop"])
    ap.add_argument("--python", type=Path, default=Path(sys.executable))
    args = ap.parse_args()
    return start(args) if args.cmd == "start" else stop(args)


if __name__ == "__main__":
    raise SystemExit(main())
