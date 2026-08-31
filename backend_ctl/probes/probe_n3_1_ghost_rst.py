# -*- coding: utf-8 -*-
"""Зонд Н3-1: детерминированное воспроизведение призрака подписки RST-обрывом.

Находка Н3-1 (переприёмка F2 раунд 3, 2026-08-12): подписка клиента переживает
его закрытие — ПМ вечно пушит `state.changed` мёртвому адресу. Раунд 3 получил
**0/12** на двух формах завершения (`watch → unwatch → close` и `watch → close`)
и записал причину как «гонка в уборке `on_session_closed`».

Жёсткое ревью 2026-08-12 опровергло «гонку»: призрак воспроизводится **с первой
попытки** третьей формой — TCP RST (SO_LINGER=0) посреди потока пушей, то есть
аварийной смертью клиента (креш, kill, обрыв сети) без FIN-рукопожатия.
Замер на стенде `webcam_sketch` (боевой GUI, 8 процессов):
`errors_delivery_failed` 0 → 310 → **1486 за 30 с (~39/с)** при нуле живых
клиентов; голос дросселирован штатно (1 запись / ~5 с, адрес мёртвой сессии
назван). Лечится только рестартом ПМ.

Значит уборка `on_session_closed` не зовётся (или не доезжает до брокера
подписок) на пути аварийного разрыва соединения — это НЕ редкая гонка, а
непокрытая ветка. Ремонт судить этим зондом: после фикса вердикт обязан стать
«no ghost reproduced», и отдельно проверить, что штатные формы (unwatch/close)
не сломаны.

Запуск (стенд должен быть поднят, порт 8765):
    .venv/Scripts/python.exe backend_ctl/probes/probe_n3_1_ghost_rst.py
"""

import json
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend_ctl.driver import BackendDriver  # noqa: E402

ATTEMPTS = 6
WATCH_WINDOW_SEC = 30.0


def router_error_counters() -> dict:
    """Счётчики ошибок роутера ПМ свежим клиентом (сам зонд следов не оставляет)."""
    drv = BackendDriver()
    drv.connect()
    try:
        resp = drv.send_command("ProcessManager", "introspect.router_stats", {}, timeout=10.0)
        res = resp.get("result") or {}
        flat: dict = {}

        def walk(node, path: str = "") -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    kp = f"{path}.{k}" if path else str(k)
                    if isinstance(v, (int, float)) and ("error" in str(k).lower() or "delivery" in str(k).lower()):
                        flat[kp] = v
                    else:
                        walk(v, kp)

        walk(res)
        return flat
    finally:
        try:
            drv.close()
        except Exception:  # noqa: BLE001 — уборка зонда не судится
            pass


def one_rst_attempt() -> None:
    """Подписаться (state + хвост), дать пушам потечь и оборвать сокет RST'ом."""
    drv = BackendDriver()
    drv.connect()
    drv.state_subscribe("processes.**", timeout=10.0)
    drv.observability_tail_all(level="INFO", timeout=10.0)
    time.sleep(1.5)  # обрыв должен лечь ПОСРЕДИ потока пушей, не на тишине
    sock = drv._sock
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()  # RST: без FIN, без снятия подписок, без close() драйвера


def main() -> int:
    print("BASELINE:", json.dumps(router_error_counters(), ensure_ascii=False))
    for i in range(ATTEMPTS):
        try:
            one_rst_attempt()
            print(f"attempt {i}: rst done")
        except Exception as exc:  # noqa: BLE001 — неудавшаяся попытка не валит замер
            print(f"attempt {i}: err {exc!r}")
        time.sleep(1.0)

    t0 = router_error_counters()
    print("T0:", json.dumps(t0, ensure_ascii=False))
    time.sleep(WATCH_WINDOW_SEC)
    t1 = router_error_counters()
    print(f"T1(+{WATCH_WINDOW_SEC:.0f}s):", json.dumps(t1, ensure_ascii=False))

    growth = {k: (t1.get(k, 0) - t0.get(k, 0)) for k in sorted(set(t0) | set(t1)) if t1.get(k, 0) != t0.get(k, 0)}
    print("GROWTH:", json.dumps(growth, ensure_ascii=False))
    ghost = any(v > 0 for v in growth.values())
    print("VERDICT:", "GHOST REPRODUCED (рост без клиентов)" if ghost else "no ghost reproduced")
    # Призрак = дефект жив = ненулевой код выхода: зонд годится в приёмку фикса.
    return 1 if ghost else 0


if __name__ == "__main__":
    raise SystemExit(main())
