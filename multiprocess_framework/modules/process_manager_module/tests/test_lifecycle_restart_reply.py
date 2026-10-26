# -*- coding: utf-8 -*-
"""Task 1.9b — ответ на ``process.restart`` не приходит раньше, чем жив новый инстанс (закрытие вопроса стенда L-9).

Стенд L-9 (investigator, 2026-10-26, п. A): в логе PM штамп ответа на рестарт #2/#3 камеры оказался раньше строки
``restarted``. Здесь та же проверка на настоящем PM и настоящем spawn-ребёнке ``slow`` (стоп 3,0 с, ``Rig`` из
``test_lifecycle_fifo_acceptance``) через обе двери: прямую (``process.restart`` с ``request_id``) и вложенную
(``process.command`` с ``cmd=process.restart`` — её использует ``backend_ctl.driver.process_restart_verified`` через
``system_command``, ``driver.py:1254`` -> ``build_system_command_message``). Содержимое ответа — как сегодня:
``{"success": True, "process_name": "slow"}`` (``_cmd_process_restart``).

Новый инстанс: pid ``slow`` в реестре сменился и процесс жив; ``instance_restarts`` вырос на 1. Ожидаемые значения —
литералы. Всё, что может блокироваться, ждёт с дедлайном (poller в daemon-потоке).
"""

from __future__ import annotations

import threading
import time

import pytest

from .test_lifecycle_fifo_acceptance import STOP_LONG_S, Rig
from .test_lifecycle_fifo_hazards import rig  # noqa: F401  (фикстура)

POLL_S = 0.02  # шаг опроса «новый инстанс жив»
POLL_SKEW_S = 0.05  # допуск на шаг опроса зонда ответов (0,02 с) и poller'а (0,02 с)


class NewIncarnationWatcher:
    """Daemon-поток: момент (``monotonic``), когда у ``name`` в реестре другой pid и процесс жив."""

    def __init__(self, harness: Rig, name: str) -> None:
        self._rig = harness
        self._name = name
        self.old_pid = harness.pm._process_registry.get_process_by_name(name).pid
        self.t_alive: float | None = None
        self._quit = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="new-incarnation-watcher")
        self._thread.start()

    def _alive_now(self) -> bool:
        proc = self._rig.pm._process_registry.get_process_by_name(self._name)
        pid = None if proc is None else proc.pid
        return bool(pid and pid != self.old_pid and proc.is_alive())

    def _run(self) -> None:
        while not self._quit.is_set():
            try:
                if self._alive_now():
                    self.t_alive = time.monotonic()
                    return
            except Exception:  # noqa: BLE001 — реестр в момент замены
                pass
            time.sleep(POLL_S)

    def alive_now(self) -> bool:
        return self._alive_now()

    def stop(self) -> None:
        self._quit.set()
        self._thread.join(2.0)


@pytest.mark.parametrize("nested", [False, True], ids=["direct-door", "process.command-door"])
def test_restart_reply_not_before_new_incarnation_alive(rig: Rig, nested: bool) -> None:  # noqa: F811
    """``process.restart slow`` (стоп 3,0 с): ответ приходит после того, как новый инстанс жив; ``success: True``,
    ``process_name: slow``; ``instance_restarts`` вырос на 1."""
    before = rig.instance_restarts("slow")
    watcher = NewIncarnationWatcher(rig, "slow")
    try:
        sent = rig.send("process.restart", {"process_name": "slow"}, nested=nested)
        reply = rig.wait_reply(sent)
        assert reply is not None, "ответ на process.restart не пришёл за дедлайн"
        new_alive_at_reply = watcher.alive_now()  # сразу после прихода ответа (шаг ожидания 5 мс)
        deadline = time.monotonic() + 30.0
        while watcher.t_alive is None and time.monotonic() < deadline:
            time.sleep(POLL_S)
    finally:
        watcher.stop()

    latency = reply.t_arrival - sent.t_send
    assert watcher.t_alive is not None, "новый инстанс slow не появился за 30 с"
    assert latency >= STOP_LONG_S, f"ответ за {latency:.2f} с — раньше конца стопа slow (3,0 с)"
    assert new_alive_at_reply, (
        f"ответ пришёл на {latency:.2f} с, а новый инстанс slow ещё не жив "
        f"(появился на {watcher.t_alive - sent.t_send:.2f} с)"
    )
    assert reply.t_arrival + POLL_SKEW_S >= watcher.t_alive, (
        f"ответ ({latency:.2f} с) раньше нового инстанса ({watcher.t_alive - sent.t_send:.2f} с)"
    )
    assert reply.success is True, f"ответ не успех: {reply.message}"
    result = reply.result
    assert isinstance(result, dict) and result.get("success") is True and result.get("process_name") == "slow", result
    assert rig.instance_restarts("slow") == before + 1
