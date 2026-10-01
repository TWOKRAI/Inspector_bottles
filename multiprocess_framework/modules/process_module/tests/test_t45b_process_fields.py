# -*- coding: utf-8 -*-
"""Task 4.5b — приёмочные RED-тесты полей процесса: ядра CPU, EMA времени плагина, ёмкость очередей.

Написаны ДО реализации, только по контракту лида (без чтения кода и тестов автора):

  * ``heartbeat/cpu_clock.py::CpuClock`` — ``seconds_total()``, ``method``, ``sample()``;
  * ``PluginRunner.plugin_ms()`` — EMA (alpha 0.1) времени ТОЛЬКО ``process()``/``produce()``;
  * ``ProcessHeartbeat._publish_telemetry_to_tree`` кладёт ``state["cpu"]`` и
    ``state["plugin_ms"]`` под гейтом метрик ``cpu`` / ``plugin_ms``;
  * ``introspect.status`` -> ``cpu``; ``introspect.queues`` -> ``queues`` и ``chain_queue``.

Эталон нагрузки — НЕ psutil (на Windows он тик-сэмплирует и занижал/завышал нагрузку
на порядки): эталон — стенное время известного busy-потока. Ожидаемые значения —
литералы, а не пересчёт из проверяемого кода.

Всё, что может зависнуть (busy-поток), идёт в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import multiprocessing
import queue
import sys
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics


# ====================================================================== #
#  Помощники                                                              #
# ====================================================================== #


def _busy_thread(seconds: float) -> threading.Thread:
    """Daemon-поток, честно крутящий CPU ровно ``seconds`` стенного времени."""

    def _spin() -> None:
        deadline = time.perf_counter() + seconds
        x = 0
        while time.perf_counter() < deadline:
            x += 1

    return threading.Thread(target=_spin, daemon=True)


def _burn(seconds: float) -> None:
    """Синхронно крутить CPU в текущем потоке ``seconds`` стенного времени."""
    deadline = time.perf_counter() + seconds
    x = 0
    while time.perf_counter() < deadline:
        x += 1


class _FakePlugin:
    """Минимальный плагин: process()/produce() спят ``delay`` секунд."""

    def __init__(self, name: str, delay: float = 0.01, *, enabled: bool = True, raises: bool = False) -> None:
        self.name = name
        self.enabled = enabled
        self._delay = delay
        self._raises = raises
        self.inputs: list = []
        self.outputs: list = []

    def process(self, items: list[dict]) -> list[dict]:
        time.sleep(self._delay)
        if self._raises:
            raise RuntimeError("плагин упал")
        return items

    def produce(self) -> list[dict]:
        time.sleep(self._delay)
        return [{"v": 1}]


def _runner() -> PluginRunner:
    # validate_ports=False: не зависеть от env FW_PORT_VALIDATE
    return PluginRunner(validate_ports=False)


# ====================================================================== #
#  CpuClock                                                               #
# ====================================================================== #


class TestCpuClock:
    def test_t45b_cpu_clock_first_sample_is_none(self) -> None:
        from multiprocess_framework.modules.process_module.heartbeat.cpu_clock import CpuClock

        assert CpuClock().sample() is None

    def test_t45b_cpu_clock_busy_thread_reads_about_one_core(self) -> None:
        """Один busy-поток 1.0 с между двумя sample() -> ~1 ядро (0.9..1.1)."""
        from multiprocess_framework.modules.process_module.heartbeat.cpu_clock import CpuClock

        clock = CpuClock()
        clock.sample()  # праймим: первый вызов -> None
        t = _busy_thread(1.0)
        t.start()
        t.join(timeout=10.0)
        assert not t.is_alive(), "busy-поток завис"
        cores = clock.sample()
        assert cores is not None
        assert 0.9 <= cores <= 1.1, f"cores={cores}"

    def test_t45b_cpu_clock_idle_reads_near_zero(self) -> None:
        """0.5 с сна (нет нагрузки) -> заметно меньше 0.15 ядра."""
        from multiprocess_framework.modules.process_module.heartbeat.cpu_clock import CpuClock

        clock = CpuClock()
        clock.sample()
        time.sleep(0.5)
        cores = clock.sample()
        assert cores is not None
        assert cores < 0.15, f"cores={cores}"

    def test_t45b_cpu_clock_method_by_platform(self) -> None:
        """Windows -> 'cycles' (QueryProcessCycleTime), POSIX -> 'process_time'."""
        from multiprocess_framework.modules.process_module.heartbeat.cpu_clock import CpuClock

        expected = "cycles" if sys.platform == "win32" else "process_time"
        assert CpuClock().method == expected

    def test_t45b_cpu_clock_seconds_total_is_monotonic(self) -> None:
        """seconds_total() не убывает, растёт под нагрузкой и это float."""
        from multiprocess_framework.modules.process_module.heartbeat.cpu_clock import CpuClock

        clock = CpuClock()
        readings = []
        for _ in range(10):
            _burn(0.02)
            readings.append(clock.seconds_total())
        assert all(isinstance(r, float) for r in readings)
        assert all(b >= a for a, b in zip(readings, readings[1:])), readings
        # якорь: часы не константа — 10 x 20 мс нагрузки дали заметный прирост (>= 0.1 с)
        assert readings[-1] - readings[0] >= 0.1, readings


# ====================================================================== #
#  PluginRunner.plugin_ms()                                               #
# ====================================================================== #


class TestPluginRunnerMs:
    def test_t45b_plugin_ms_ema_of_process_call(self) -> None:
        """process() спит 10 мс, 20 вызовов -> EMA в 9..13 мс."""
        runner = _runner()
        plugin = _FakePlugin("det", 0.01)
        for _ in range(20):
            runner.call_process(plugin, [{"i": 1}])
        assert 9.0 <= runner.plugin_ms()["det"] <= 13.0

    def test_t45b_plugin_ms_alpha_is_a_tenth_first_sample_seeds(self) -> None:
        """Первый вызов 30 мс, ещё 19 по 10 мс.

        EMA alpha=0.1, первый сэмпл = начальное значение: 10 + 20 * 0.9**19 ≈ 12.7..13.5.
        Среднее арифметическое дало бы ~11, «последний сэмпл» ~10, alpha=0.2 ~10.8,
        alpha=0.05 ~17.7 — окно 12.3..14.3 отличает alpha=0.1 от них всех.
        """
        runner = _runner()
        slow_first = _FakePlugin("det", 0.03)
        runner.call_process(slow_first, [{"i": 1}])
        fast = _FakePlugin("det", 0.01)
        for _ in range(19):
            runner.call_process(fast, [{"i": 1}])
        assert 12.3 <= runner.plugin_ms()["det"] <= 14.3

    def test_t45b_plugin_ms_excludes_pre_hook_time(self) -> None:
        """pre-хук спит 20 мс, process() 10 мс -> EMA не выше 13 (хук не считается)."""
        runner = _runner()
        runner.add_pre_hook(lambda plugin, method, inputs: time.sleep(0.02))
        plugin = _FakePlugin("det", 0.01)
        for _ in range(20):
            runner.call_process(plugin, [{"i": 1}])
        ms = runner.plugin_ms()["det"]
        assert 9.0 <= ms <= 13.0, ms

    def test_t45b_plugin_ms_covers_produce(self) -> None:
        """produce() источника в 10 мс тоже пишется, и хук не портит цифру."""
        runner = _runner()
        runner.add_pre_hook(lambda plugin, method, inputs: time.sleep(0.02))
        source = _FakePlugin("cam", 0.01)
        for _ in range(20):
            runner.call_produce(source)
        ms = runner.plugin_ms()["cam"]
        assert 9.0 <= ms <= 13.0, ms

    def test_t45b_plugin_ms_disabled_plugin_records_nothing(self) -> None:
        """Bypass (enabled=False): имя отсутствует; здоровый сосед в снимке есть (не пустой словарь)."""
        runner = _runner()
        off = _FakePlugin("off", 0.01, enabled=False)
        live = _FakePlugin("live", 0.01)
        for _ in range(5):
            runner.call_process(off, [{"i": 1}])
            runner.call_process(live, [{"i": 1}])
        snapshot = runner.plugin_ms()
        assert "live" in snapshot
        assert "off" not in snapshot

    def test_t45b_plugin_ms_raising_plugin_records_nothing(self) -> None:
        """Плагин, бросивший исключение, не пишет время; сосед пишет."""
        runner = _runner()
        bad = _FakePlugin("bad", 0.01, raises=True)
        live = _FakePlugin("live", 0.01)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                runner.call_process(bad, [{"i": 1}])
            runner.call_process(live, [{"i": 1}])
        snapshot = runner.plugin_ms()
        assert "live" in snapshot
        assert "bad" not in snapshot

    def test_t45b_plugin_ms_returns_a_copy(self) -> None:
        """Мутация снимка не меняет раннер."""
        runner = _runner()
        runner.call_process(_FakePlugin("det", 0.005), [{"i": 1}])
        first = runner.plugin_ms()
        assert set(first) == {"det"}
        kept = first["det"]
        first["det"] = 12345.0
        first["intruder"] = 1.0
        second = runner.plugin_ms()
        assert set(second) == {"det"}
        assert second["det"] == kept


# ====================================================================== #
#  Публикация в дерево (ProcessHeartbeat)                                 #
# ====================================================================== #


class _Proxy:
    def __init__(self) -> None:
        self.merged: list[tuple[str, dict]] = []

    def set(self, path: str, value: object) -> None: ...

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))


class _StubRunner:
    def plugin_ms(self) -> dict[str, float]:
        return {"detector": 12.36, "stitcher": 3.04}


class _HbServices:
    """Фейк сервисов сердцебиения (по образцу test_telemetry_gate._FakeServices)."""

    def __init__(self, proxy: _Proxy, *, plugin_runner: object = None) -> None:
        self._state_proxy = proxy
        self.router_manager = None
        self.name = "proc"
        self._health_state = None
        self.plugin_runner = plugin_runner

    def get_config(self, key: str, default=None):
        return default

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...


def _workers() -> dict:
    return {"w0": {"status": "running", "effective_hz": 10.0, "cycle_duration_ms": 5.0}}


def _tick(hb: ProcessHeartbeat, proxy: _Proxy, allowed) -> dict:
    """Один тик публикации; вернуть ``state`` из последнего merge."""
    before = len(proxy.merged)
    hb._publish_telemetry_to_tree(_workers(), allowed)
    assert len(proxy.merged) == before + 1, "тик обязан дать ровно один merge"
    return proxy.merged[-1][1].get("state", {})


class TestHeartbeatPublish:
    def test_t45b_publish_cpu_and_plugin_ms_after_two_ticks(self) -> None:
        proxy = _Proxy()
        hb = ProcessHeartbeat(_HbServices(proxy, plugin_runner=_StubRunner()))
        first = _tick(hb, proxy, None)
        assert "cpu" not in first, "на первом тике ядер ещё нет (нужна дельта)"
        _burn(0.1)
        second = _tick(hb, proxy, None)
        cores = second["cpu"]["cores"]
        assert isinstance(cores, float)
        assert cores > 0.0
        assert round(cores, 2) == cores, "ядра — 2 знака после запятой"
        assert second["plugin_ms"] == {"detector": 12.4, "stitcher": 3.0}

    def test_t45b_publish_cpu_and_plugin_ms_are_gated_by_metric_names(self) -> None:
        """Пара «зелёный контроль + выключенная»: без первой половины отсутствие ничего не доказывает."""
        proxy = _Proxy()
        hb = ProcessHeartbeat(_HbServices(proxy, plugin_runner=_StubRunner()))
        _tick(hb, proxy, None)
        _burn(0.1)
        control = _tick(hb, proxy, None)
        assert "cpu" in control and "plugin_ms" in control  # контроль: без гейта поля есть

        allowed = {"fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm"}
        _burn(0.1)
        gated = _tick(hb, proxy, allowed)
        assert "fps" in gated  # гейт пропустил остальное
        assert "cpu" not in gated
        assert "plugin_ms" not in gated


# ====================================================================== #
#  Каталог метрик                                                         #
# ====================================================================== #


def test_t45b_catalog_declares_cpu_and_plugin_ms() -> None:
    names = set(gated_metrics())
    assert "cpu" in names
    assert "plugin_ms" in names


# ====================================================================== #
#  introspect.status / introspect.queues                                  #
# ====================================================================== #


class _CmdManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _IntrospectServices:
    """IProcessServices-фейк (по образцу test_introspect_commands._FakeServices)."""

    def __init__(self, *, queues=None, chain_queue="__absent__") -> None:
        self.command_manager = _CmdManager()
        self.router_manager = None
        self.worker_manager = None
        self._orchestrator = None
        self.queues = queues
        self.shared_resources = None
        self.name = "preprocessor"
        self._current_process_status = "running"
        if chain_queue != "__absent__":
            self.chain_queue = chain_queue

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...


def _commands(**kw) -> _CmdManager:
    svc = _IntrospectServices(**kw)
    BuiltinCommands(svc)._register_introspect_commands()
    return svc.command_manager


@pytest.fixture
def data_queue():
    q = multiprocessing.Queue(maxsize=50)  # как DEFAULT_QUEUES["data"] = {"maxsize": 50}
    yield q
    q.close()
    q.cancel_join_thread()


class TestIntrospectQueuesCapacity:
    def test_t45b_introspect_queues_reports_maxsize(self, data_queue) -> None:
        cm = _commands(queues={"data": data_queue}, chain_queue=queue.Queue(maxsize=6))
        result = cm.dispatch("introspect.queues")
        assert result["success"] is True
        assert result["queues"]["data"]["maxsize"] == 50
        assert result["chain_queue"]["maxsize"] == 6

    def test_t45b_introspect_queues_reports_size_and_keeps_queue_sizes(self, data_queue) -> None:
        chain = queue.Queue(maxsize=6)
        for i in range(3):
            chain.put(i)
        cm = _commands(queues={"data": data_queue}, chain_queue=chain)
        result = cm.dispatch("introspect.queues")
        assert result["chain_queue"]["size"] == 3
        assert result["queues"]["data"]["size"] == 0
        assert result["queue_sizes"] == {"data": 0}  # прежний ключ не сломан

    def test_t45b_introspect_queues_chain_queue_is_none_without_chain(self, data_queue) -> None:
        cm = _commands(queues={"data": data_queue})  # у сервисов нет chain_queue вовсе
        result = cm.dispatch("introspect.queues")
        assert result["success"] is True
        assert result["queues"]["data"]["maxsize"] == 50  # якорь: секция queues живая
        assert "chain_queue" in result
        assert result["chain_queue"] is None


class TestIntrospectStatusCpu:
    def test_t45b_introspect_status_has_cpu_block(self) -> None:
        cm = _commands()
        result = cm.dispatch("introspect.status")
        assert result["success"] is True
        cpu = result["cpu"]
        assert set(cpu) == {"cores", "seconds_total", "method"}
        assert cpu["method"] in ("cycles", "process_time")
        assert isinstance(cpu["seconds_total"], float)
        assert cpu["seconds_total"] > 0.0  # процесс pytest уже прожил секунды CPU
        assert cpu["cores"] is None or isinstance(cpu["cores"], float)
