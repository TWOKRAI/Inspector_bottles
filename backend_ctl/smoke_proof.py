# -*- coding: utf-8 -*-
"""Smoke proof-of-value для backend_ctl (P2): диагноз Этапа 2 без GUI.

Поднимает прототип headless с BACKEND_CTL=1, подключает driver и через
introspect.handlers подтверждает: у `preprocessor` (плагин resize с register_schema)
ЕСТЬ приёмник register_update, а у `process_negative` (negative без schema) — НЕТ.
Ровно та диагностика, что в Этапе 2 заняла ~30 шагов qt-mcp.

Запуск:
    BACKEND_CTL=1 python -m backend_ctl.smoke_proof
"""

from __future__ import annotations

import os
import sys
import time


def _has_register_update(result: dict) -> bool:
    """True, если у процесса есть router-приёмник register_update.

    Честная проверка по списку router_handlers (а не по подстроке в repr — иначе
    timeout-ответ ложно трактуется). Возвращает False при ошибке/таймауте.
    """
    if not isinstance(result, dict) or not result.get("success"):
        return False
    handlers = (result.get("result") or {}).get("router_handlers") or []
    return "register_update" in handlers


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    port = int(os.environ.get("BACKEND_CTL_PORT", "8765"))

    from multiprocess_prototype.main import bootstrap
    from backend_ctl import BackendDriver

    print("[smoke] поднимаю систему headless (BACKEND_CTL=1)...")
    launcher = bootstrap()
    launcher.start()
    if not launcher.wait_until_ready(timeout=30.0):
        print("[smoke] FAIL: система не готова за 30с")
        launcher.shutdown()
        return 1
    print("[smoke] система готова. Подключаю driver...")

    rc = 0
    try:
        time.sleep(2.0)  # прогрев процессов (introspect к холодному процессу может таймаутить)
        with BackendDriver(port=port) as drv:
            time.sleep(0.5)  # дать сокету зарегистрировать клиента

            for proc, expect in [("preprocessor", True), ("process_negative", False)]:
                res = drv.introspect_handlers(proc, timeout=8.0)
                has = _has_register_update(res)
                mark = "OK" if has == expect else "MISMATCH"
                print(f"[smoke] {proc:18} register_update={has} (ожидалось {expect}) [{mark}]")
                print(f"         ответ: {res}")
                if has != expect:
                    rc = 1

            # Бонус: статус живого процесса
            st = drv.introspect_status("preprocessor", timeout=5.0)
            print(f"[smoke] preprocessor status: {st}")
    finally:
        print("[smoke] гашу систему (PID-specific)...")
        launcher.shutdown()

    print(f"[smoke] {'PASS' if rc == 0 else 'FAIL'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
