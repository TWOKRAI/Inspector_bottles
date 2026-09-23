# -*- coding: utf-8 -*-
"""Живая приёмка closure 4.4 — точечные подписки переживают рестарт цели и RST клиента.

Две пары, у каждой контроль:

    R  рестарт: клиент A держит точечный ``observability.tail`` на цели, клиент B
       подписался и снял. После ``process_restart_verified`` новая инкарнация
       обязана слать A (>0 записей) и не слать B (==0) — замена подтверждена
       pid + instance_restarts, а не ответом команды.
    S  RST-обрыв: клиент E подписался через канал (наблюдатель записал) и умер
       без FIN. Датчик ревьюера: адресное снятие подписки E у цели отвечает
       ``success: False`` — снимать уже нечего. Контроль: подписка на ЧУЖОЙ явный
       адрес (не кончается на сессию E), взятая тем же клиентом, — её закрытие
       сессии снимать не должно, датчик обязан ответить ``success: True``.
       Контроль убирается в конце.

Почему контроль — чужой адрес, а не тайм-аут сервера: после 4.4 (ревью, п.2)
подписка с тайм-аутом записывается, обход наблюдателя тайм-аутом больше не
обход. Чужой адрес — честный обход: сессия его не владеет.

Стенд не поднимается зондом. Порт — ``BACKEND_CTL_PORT`` (по умолчанию 8765),
цель — ``PROBE_TARGET`` (по умолчанию ``pult``)::

    BACKEND_CTL_PORT=8767 PYTHONPATH=$PWD python backend_ctl/probes/probe_4_4_point_intents_live.py
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import threading
import time

from backend_ctl.driver import BackendDriver

PORT = int(os.environ.get("BACKEND_CTL_PORT", "8765"))
TARGET = os.environ.get("PROBE_TARGET", "pult")
WINDOW_S = 10.0


class _Counter:
    """Считает пуши хвоста, пришедшие этому клиенту, с отметкой времени."""

    def __init__(self, drv: BackendDriver) -> None:
        self._lock = threading.Lock()
        self._ts: list = []
        drv.subscribe(self._on)

    def _on(self, msg: dict) -> None:
        if msg.get("command") in ("observability.record", "log.record"):
            with self._lock:
                self._ts.append(time.time())

    def since(self, t0: float) -> int:
        with self._lock:
            return sum(1 for t in self._ts if t >= t0)


def _driver() -> BackendDriver:
    d = BackendDriver(port=PORT)
    d.connect()
    return d


def _leaf(res):
    node = res
    for _ in range(4):
        if isinstance(node, dict) and isinstance(node.get("result"), dict):
            node = node["result"]
        else:
            break
    return node if isinstance(node, dict) else {}


def _rst(drv: BackendDriver) -> None:
    s = drv._sock
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()


def pair_restart():
    a, b = _driver(), _driver()
    ca, cb = _Counter(a), _Counter(b)
    print(f"R  A tail: {a.observability_tail(TARGET, level='DEBUG', timeout=20.0).get('success')}")
    tb = time.time()
    print(f"R  B tail: {b.observability_tail(TARGET, level='DEBUG', timeout=20.0).get('success')}")
    time.sleep(WINDOW_S)
    # Чувствительность B==0: пока B подписан, он обязан что-то получать, иначе ноль
    # после рестарта доказывался бы тишиной цели, а не снятым намерением.
    nb_before = cb.since(tb)
    print(f"R  B records while subscribed in {WINDOW_S:.0f}s: {nb_before}")
    print(f"R  B untail: {b.observability_untail(TARGET, timeout=20.0).get('success')}")
    restart = a.process_restart_verified(TARGET, wait=60.0)
    print(
        f"R  restart verified: {restart.get('restarted')} pid {restart.get('pid_before')} -> {restart.get('pid_after')}"
    )
    t0 = time.time()
    time.sleep(WINDOW_S)
    na, nb = ca.since(t0), cb.since(t0)
    print(f"R  records from new incarnation in {WINDOW_S:.0f}s: A={na} B={nb}")
    a.observability_untail(TARGET, timeout=20.0)
    a.close()
    b.close()
    if nb_before == 0:
        print("R  INCONCLUSIVE: B ничего не получал и до снятия — B==0 ничего не доказывает")
        return None
    return bool(restart.get("restarted")) and na > 0 and nb == 0


def pair_rst() -> bool:
    e = _driver()
    esub = e._subscriber
    foreign = f"probe44.foreign.{int(time.time())}"
    print(f"S  E tail (own address {esub}): {e.observability_tail(TARGET, level='DEBUG', timeout=20.0).get('success')}")
    own: dict = {}
    ctl_sensor: dict = {}
    q = None
    try:
        ctl = e.observability_tail(TARGET, subscriber=foreign, level="DEBUG", timeout=20.0)
        print(f"S  control tail (foreign address {foreign}): {ctl.get('success')}")
        time.sleep(1.5)
        _rst(e)
        time.sleep(3.0)
        q = _driver()
        own = _leaf(q.send_command(TARGET, "observability.tail.unsubscribe", {"subscriber": esub}, timeout=15.0))
        # Датчик контроля — это же и уборка контроля.
        ctl_sensor = _leaf(
            q.send_command(TARGET, "observability.tail.unsubscribe", {"subscriber": foreign}, timeout=15.0)
        )
    finally:
        if not ctl_sensor:  # датчик не дошёл — снять контроль всё равно, чтобы не оставить сироту
            try:
                q = q or _driver()
                q.send_command(TARGET, "observability.tail.unsubscribe", {"subscriber": foreign}, timeout=15.0)
            except Exception as exc:  # noqa: BLE001 — уборка зонда
                print(f"S  cleanup of control failed: {exc}")
        if q is not None:
            q.close()
    print(f"S  sensor own address after RST: success={own.get('success')} (ожидаем False — снято сервером)")
    print(f"S  sensor control after RST: success={ctl_sensor.get('success')} (ожидаем True — чужой адрес жив)")
    return own.get("success") is False and ctl_sensor.get("success") is True


def main() -> int:
    print(f"probe 4.4: port={PORT} target={TARGET}")
    r = pair_restart()
    s = pair_rst()
    r_word = "INCONCLUSIVE" if r is None else ("PASS" if r else "FAIL")
    print(f"VERDICT R(restart)={r_word} S(rst)={'PASS' if s else 'FAIL'}")
    return 0 if (r is True and s) else 1


if __name__ == "__main__":
    sys.exit(main())
