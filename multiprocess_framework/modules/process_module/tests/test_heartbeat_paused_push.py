# -*- coding: utf-8 -*-
"""Task 1.2c (system-run-state) — внеочередной heartbeat при смене ``paused`` (слепые acceptance-тесты).

Факт стенда: процесс считает снимок готовности каждые 0,5 с, но в PM он попадает только с обычным heartbeat
(по умолчанию раз в 5 с). PM узнаёт о смене ``paused`` через ~3-5 с вместо <= 1 с.

Наблюдаемые требования (поведение, не устройство):

1. Большой ``heartbeat_interval`` (30 с): после ``run_event.clear()`` в очередь сообщений приходит heartbeat с
   ``readiness.paused == True`` не позже 1,5 с; после ``set()`` — с ``paused == False`` не позже 1,5 с.
2. Без смены ``paused`` внеочередных heartbeat нет: за 3 с спокойной работы не больше одного (стартового).
3. Антидребезг: 20 переключений события за 1 с дают не больше 3 heartbeat за эту секунду; после затишья
   последний heartbeat несёт актуальное ``paused``.
4. Сбой отправки внеочередного heartbeat не роняет воркер снимка: ``at`` растёт, снимок следует за событием.
5. Обычный heartbeat по интервалу идёт как раньше (0,2 с -> >= 4 сообщений за 1,3 с, ``readiness`` в каждом).
6. Процесс без плагинов (``paused`` по событию, без оркестратора) тоже даёт внеочередной heartbeat.

Стенд — настоящие процессы под ``run_process_function`` в daemon-потоке (образец —
``test_readiness_hazards.test_acceptance_chain_paused_flag_reaches_received_heartbeat_message``): настоящий
``GenericProcess`` / ``ProcessModule`` -> настоящий ``ProcessHeartbeat`` -> spawn-очередь; подменён только
``send_message`` процесса-наследника (кладёт heartbeat в очередь теста). Ожидания — циклы с дедлайном,
выход процесса — с join-дедлайном.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, ProcessModulePlugin

_THIS = "multiprocess_framework.modules.process_module.tests.test_heartbeat_paused_push"
_JOIN_S = 30.0

#: Граница требования 1: номинально 0,05 (сверка) + 0,5 (снимок) + запас от мигания стенда.
_PUSH_DEADLINE_S = 1.5
#: Большой интервал: обычный heartbeat за время теста не наступит, всё внеочередное — наблюдаемо.
_LONG_INTERVAL_S = 30.0

SHARED: dict[str, Any] = {}


class PpPlugin(ProcessModulePlugin):
    """Плагин без собственной готовности: процесс с оркестратором, ``readiness()`` по умолчанию пуст."""

    name = "pp_plugin"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items


class _CaptureHeartbeats:
    """Подмена ``send_message``: heartbeat -> очередь теста (или сбой по флагу), остальное — как у процесса."""

    def send_message(self, target: str, message: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(message, dict) and message.get("command") == "heartbeat":
            SHARED["attempts"].append(message)  # попытка отправки — до возможного сбоя
            if SHARED.get("fail_send"):
                raise RuntimeError("сбой отправки heartbeat (тест)")
            out = SHARED.get("queue")
            if out is not None:
                out.put(message)
            return True
        return super().send_message(target, message, *args, **kwargs)  # type: ignore[misc]


class PpPluginProcess(_CaptureHeartbeats, GenericProcess):
    """Настоящий ``GenericProcess`` с плагином (есть оркестратор и воркер ``run_watch``)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


class PpPlainProcess(_CaptureHeartbeats, ProcessModule):
    """Настоящий ``ProcessModule`` БЕЗ плагинов (форма снимка: ``paused`` по событию)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._run_event = SHARED["event"]
        SHARED["proc"] = self


class _Collector:
    """Фоновый читатель очереди: складывает ``(момент прихода, сообщение)``; ``stop`` останавливает."""

    def __init__(self, out: Any) -> None:
        self._out = out
        self._lock = threading.Lock()
        self._items: list[tuple[float, dict]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="pp-collector")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._out.get(timeout=0.05)
            except Exception:  # noqa: BLE001 — таймаут очереди
                continue
            with self._lock:
                self._items.append((time.monotonic(), msg))

    def items(self) -> list[tuple[float, dict]]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def wait_for(self, predicate: Any, deadline_s: float) -> tuple[bool, float]:
        """Ждать сообщения, подходящего под ``predicate``; вернуть (нашли, сколько секунд ждали)."""
        started = time.monotonic()
        end = started + deadline_s
        while time.monotonic() < end:
            if any(predicate(msg) for _, msg in self.items()):
                return True, time.monotonic() - started
            time.sleep(0.02)
        return any(predicate(msg) for _, msg in self.items()), time.monotonic() - started

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5.0)


def _paused_of(msg: dict) -> Any:
    """``readiness.paused`` сообщения или ``None``, если поля нет (стартовый heartbeat до первого снимка)."""
    readiness = msg.get("readiness")
    return None if not isinstance(readiness, dict) else readiness.get("paused")


def _wait(predicate: Any, deadline_s: float) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _snap() -> dict | None:
    proc = SHARED.get("proc")
    return None if proc is None else proc._readiness_snapshot


class _Stand:
    """Один настоящий процесс + очередь + сборщик; контекстный менеджер гарантирует остановку."""

    def __init__(self, process_cls: str, with_plugin: bool, heartbeat_interval: float) -> None:
        self.event = multiprocessing.Event()
        self.event.set()
        self.out = multiprocessing.get_context("spawn").Queue()
        SHARED.clear()
        SHARED.update({"event": self.event, "proc": None, "queue": self.out, "attempts": [], "fail_send": False})
        plugins = [{"plugin_class": f"{_THIS}.PpPlugin", "plugin_name": "pp_plugin"}] if with_plugin else []
        # ``ProcessHeartbeat.start`` читает ``get_config("heartbeat_interval")`` — ключ верхнего уровня конфига
        cfg: dict[str, Any] = {
            "config": {"plugins": plugins, "chain_targets": []},
            "heartbeat_interval": heartbeat_interval,
        }
        self.own_ready = multiprocessing.Event()
        bundle = {
            "queues": {"data": multiprocessing.Queue()},
            "config": cfg,
            "custom": {"process_config": cfg, "ready_event": self.own_ready},
        }
        self.stop_flag = threading.Event()
        self.collector = _Collector(self.out)
        self.thread = threading.Thread(
            target=run_process_function,
            args=(f"{_THIS}.{process_cls}", "pp_real", self.stop_flag, bundle, None),
            daemon=True,
            name="pp-real-process",
        )
        self.thread.start()

    def warm_up(self, settle_s: float = 1.0) -> None:
        """Дождаться готовности процесса и снимка, дать осесть стартовым сообщениям, очистить сборщик."""
        assert self.own_ready.wait(_JOIN_S), "процесс не объявил готовность"
        assert _wait(lambda: (_snap() or {}).get("ready") is True, 5.0), _snap()
        time.sleep(settle_s)
        self.collector.clear()
        SHARED["attempts"].clear()

    def close(self) -> None:
        self.stop_flag.set()
        self.thread.join(_JOIN_S)
        alive = self.thread.is_alive()
        self.collector.stop()
        self.out.close()
        self.out.cancel_join_thread()
        SHARED.clear()
        assert not alive, "run_process_function не вышел после stop"


@pytest.fixture
def stand_factory():
    """Фабрика стендов; все созданные останавливаются по выходу из теста."""
    made: list[_Stand] = []

    def make(process_cls: str, with_plugin: bool = True, heartbeat_interval: float = _LONG_INTERVAL_S) -> _Stand:
        stand = _Stand(process_cls, with_plugin, heartbeat_interval)
        made.append(stand)
        return stand

    yield make
    for stand in made:
        stand.close()


# --------------------------------------------------------------------------- #
# Требование 1: внеочередной heartbeat при смене paused (интервал 30 с)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_clear_event_pushes_paused_true_heartbeat_with_long_interval(stand_factory) -> None:
    """``run_event.clear()`` при интервале 30 с -> heartbeat с ``readiness.paused == True`` не позже 1,5 с."""
    stand = stand_factory("PpPluginProcess")
    stand.warm_up()

    stand.event.clear()
    found, elapsed = stand.collector.wait_for(lambda m: _paused_of(m) is True, _PUSH_DEADLINE_S)

    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"heartbeat с paused=True не пришёл за {_PUSH_DEADLINE_S} с после clear(); пришло: {got}"
    assert elapsed <= _PUSH_DEADLINE_S, elapsed


@pytest.mark.timeout(120)
def test_set_event_pushes_paused_false_heartbeat_with_long_interval(stand_factory) -> None:
    """``run_event.set()`` после паузы, интервал 30 с -> heartbeat с ``paused == False`` не позже 1,5 с."""
    stand = stand_factory("PpPluginProcess")
    stand.warm_up()
    stand.event.clear()
    # пауза дошла до снимка процесса; затем затишье дольше окна антидребезга — прошлый push осел
    assert _wait(lambda: (_snap() or {}).get("paused") is True, 5.0), "после clear() paused снимка не стал True"
    time.sleep(2.0)
    stand.collector.clear()

    stand.event.set()
    found, elapsed = stand.collector.wait_for(lambda m: _paused_of(m) is False, _PUSH_DEADLINE_S)

    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"heartbeat с paused=False не пришёл за {_PUSH_DEADLINE_S} с после set(); пришло: {got}"
    assert elapsed <= _PUSH_DEADLINE_S, elapsed


# --------------------------------------------------------------------------- #
# Требование 2: без смены paused внеочередных heartbeat нет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_no_paused_change_no_extra_heartbeat(stand_factory) -> None:
    """Интервал 30 с, событие не трогаем: за 3 с после готовности не больше одного heartbeat (стартового)."""
    stand = stand_factory("PpPluginProcess")
    assert stand.own_ready.wait(_JOIN_S), "процесс не объявил готовность"

    time.sleep(3.0)

    heartbeats = [m for _, m in stand.collector.items()]
    assert len(heartbeats) <= 1, (
        f"поток heartbeat без смены paused: {len(heartbeats)} шт., paused={[_paused_of(m) for m in heartbeats]}"
    )


# --------------------------------------------------------------------------- #
# Требование 3: антидребезг
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_flapping_event_is_debounced_and_final_state_delivered(stand_factory) -> None:
    """20 переключений за 1 с (clear/set подряд): <= 3 heartbeat за секунду; после затишья последний — актуальный.

    Серия начинается с ``clear()`` и кончается ``set()`` (чётное число): итоговое ``paused`` = ``False`` отличается
    от пика серии (``True``), так что «последний heartbeat актуален» не выполняется само собой.
    """
    stand = stand_factory("PpPluginProcess")
    stand.warm_up()

    started = time.monotonic()
    for i in range(20):
        (stand.event.clear if i % 2 == 0 else stand.event.set)()
        time.sleep(0.05)
    flaps_end = time.monotonic()
    in_window = [m for t, m in stand.collector.items() if started <= t <= flaps_end]

    assert len(in_window) <= 3, f"дребезг не подавлен: {len(in_window)} heartbeat за {flaps_end - started:.2f} с"

    # затишье: итоговый paused (False) обязан дойти до получателя последним сообщением
    time.sleep(2.5)
    got = [m for _, m in stand.collector.items()]
    assert got, "после серии переключений ни одного heartbeat (итог не доставлен)"
    assert _paused_of(got[-1]) is False, (
        f"последний heartbeat не актуален: paused по порядку = {[_paused_of(m) for m in got]}"
    )


# --------------------------------------------------------------------------- #
# Требование 4: сбой отправки не роняет воркер снимка
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_push_send_failure_does_not_kill_snapshot_worker(stand_factory) -> None:
    """``send_message`` бросает при внеочередной отправке: ``at`` снимка растёт, снимок следует за событием."""
    stand = stand_factory("PpPluginProcess")
    stand.warm_up()
    SHARED["fail_send"] = True

    stand.event.clear()
    # внеочередная отправка действительно была предпринята (и упала) — иначе проверять устойчивость не на чем
    attempted = _wait(lambda: any(_paused_of(m) is True for m in list(SHARED["attempts"])), _PUSH_DEADLINE_S)
    tried = [_paused_of(m) for m in SHARED["attempts"]]
    assert attempted, f"внеочередная отправка не предпринята за {_PUSH_DEADLINE_S} с; попытки: {tried}"

    # воркер снимка пережил сбой: at растёт и после попытки, и снимок видит возврат события
    at_after_failure = _snap()["at"]
    assert _wait(lambda: _snap()["at"] > at_after_failure + 0.4, 3.0), "at не растёт после сбоя отправки"
    assert _snap()["paused"] is True, _snap()
    stand.event.set()
    assert _wait(lambda: _snap()["paused"] is False, 3.0), "снимок перестал следовать за событием после сбоя отправки"
    assert stand.thread.is_alive(), "процесс умер после сбоя отправки"


# --------------------------------------------------------------------------- #
# Требование 5: обычный heartbeat по интервалу идёт как раньше
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_regular_heartbeat_cadence_unchanged(stand_factory) -> None:
    """Интервал 0,2 с: >= 4 сообщений за 1,3 с, поле ``readiness`` в каждом (темп не испорчен внеочередной веткой)."""
    stand = stand_factory("PpPluginProcess", heartbeat_interval=0.2)
    assert stand.own_ready.wait(_JOIN_S), "процесс не объявил готовность"
    found, _ = stand.collector.wait_for(lambda m: _paused_of(m) is False, 15.0)
    assert found, "heartbeat с readiness не пришёл"
    stand.collector.clear()

    time.sleep(1.3)

    steady = [m for _, m in stand.collector.items()]
    assert len(steady) >= 4, f"heartbeat реже 0,2 с: {len(steady)} сообщений за 1,3 с"
    assert all("readiness" in m for m in steady), [sorted(m) for m in steady]


# --------------------------------------------------------------------------- #
# Требование 6: процесс без плагинов
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_process_without_plugins_also_pushes_on_event_change(stand_factory) -> None:
    """Процесс без оркестратора: смена события даёт внеочередной heartbeat (clear -> True, set -> False), <= 1,5 с."""
    stand = stand_factory("PpPlainProcess", with_plugin=False)
    stand.warm_up()
    assert SHARED["proc"]._orchestrator is None, "стенд не «без плагинов»"

    stand.event.clear()
    found, _ = stand.collector.wait_for(lambda m: _paused_of(m) is True, _PUSH_DEADLINE_S)
    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"процесс без плагинов: heartbeat с paused=True не пришёл за {_PUSH_DEADLINE_S} с; пришло: {got}"

    time.sleep(2.0)  # затишье дольше окна антидребезга
    stand.collector.clear()
    stand.event.set()
    found, _ = stand.collector.wait_for(lambda m: _paused_of(m) is False, _PUSH_DEADLINE_S)
    got = [_paused_of(m) for _, m in stand.collector.items()]
    assert found, f"процесс без плагинов: heartbeat с paused=False не пришёл за {_PUSH_DEADLINE_S} с; пришло: {got}"
