# -*- coding: utf-8 -*-
"""Headless-диагностика телеметрии через backend_ctl (без GUI).

Поднимает прототип headless (BACKEND_CTL=1), подключает driver и через
request/reply localизует обрыв live-телеметрии процессов:

  1. introspect.handlers(ProcessManager) — есть ли `state.subscribe`/`state.changed`
     в router.message_dispatcher (иначе IPC-подписка молча дропается);
  2. state.subscribe(processes.**) — отвечает ли handle_state_subscribe (sub_id);
  3. state.get(processes) — публикует ли ProcessMonitor телеметрию в дерево;
  4. introspect.status(<proc>) — живые ли процессы.

Это та же диагностика, что в GUI занимает десятки шагов qt-mcp, — но
детерминированно и headless. Запуск:

    BACKEND_CTL=1 python -m backend_ctl.telemetry_probe
"""

from __future__ import annotations

import json
import os
import sys
import time


def _unwrap(res: dict) -> dict:
    """Достать вложенный handler-результат: request() → {success, result:{...}}."""
    if not isinstance(res, dict):
        return {}
    return res.get("result") if isinstance(res.get("result"), dict) else res


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    port = int(os.environ.get("BACKEND_CTL_PORT", "8765"))

    from multiprocess_prototype.main import bootstrap
    from backend_ctl import BackendDriver

    print("[probe] поднимаю систему headless (BACKEND_CTL=1)...")
    launcher = bootstrap()
    launcher.start()
    if not launcher.wait_until_ready(timeout=30.0):
        print("[probe] FAIL: система не готова за 30с")
        launcher.shutdown()
        return 1
    print("[probe] система готова. Подключаю driver...\n")

    try:
        time.sleep(2.0)  # прогрев процессов
        with BackendDriver(port=port) as drv:
            time.sleep(0.5)

            # 1. Хендлеры ProcessManager — есть ли state.* в message_dispatcher?
            res = drv.introspect_handlers("ProcessManager", timeout=8.0)
            rh = _unwrap(res).get("router_handlers") or []
            print(f"[1] introspect.handlers(ProcessManager): success={res.get('success')}")
            print(f"    router_handlers ({len(rh)}): {sorted(rh)}")
            for key in ("state.subscribe", "state.set", "state.changed", "process.command"):
                print(f"    >>> '{key}' в message_dispatcher: {key in rh}")
            print()

            # 2. state.subscribe — отвечает ли handle_state_subscribe?
            sub = drv.send_command(
                "ProcessManager",
                "state.subscribe",
                {"pattern": "processes.**", "subscriber": "backend_ctl_probe", "exclude_sources": []},
                timeout=6.0,
            )
            sub_r = _unwrap(sub)
            print(
                f"[2] state.subscribe(processes.**): success={sub.get('success')}, "
                f"status={sub_r.get('status')}, sub_id={sub_r.get('sub_id')}"
            )
            print()

            # 3. state.get(processes) — публикует ли ProcessMonitor телеметрию?
            got = drv.send_command("ProcessManager", "state.get", {"path": "processes"}, timeout=6.0)
            got_r = _unwrap(got)
            value = got_r.get("value")
            print(f"[3] state.get(processes): success={got.get('success')}, status={got_r.get('status')}")
            vs = json.dumps(value, ensure_ascii=False)
            print(f"    value (первые 800): {vs[:800]}")
            if isinstance(value, dict):
                print(f"    >>> процессов в дереве: {list(value.keys())}")
            print()

            # 4. Статус живого процесса
            for proc in ("camera_0", "ProcessManager"):
                st = drv.introspect_status(proc, timeout=5.0)
                print(f"[4] introspect.status({proc}): {json.dumps(_unwrap(st), ensure_ascii=False)[:400]}")
    finally:
        print("\n[probe] гашу систему (PID-specific)...")
        launcher.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
