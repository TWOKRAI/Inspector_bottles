# -*- coding: utf-8 -*-
"""
Задача 0.11b (M-4, минимум): запись метрики ДРУГОГО вида под существующим
ключом не пропадает молча.

ПЕРЕХОДНЫЙ файл: после задачи 1.2 вид входит в ключ серии, серии разных видов
раздельны и ``metric_kind_conflicts == 0`` у пары counter/timing — 1.2
переписывает этот файл.

Ключ серии (имя + теги) не менялся. «Вид» — ``MetricType`` записи. Запись другого
вида под занятым ключом отвергается: первая серия нетронута, счётчик
``metric_kind_conflicts`` растёт на КАЖДЫЙ конфликт, голос (WARNING) звучит не
чаще окна на ключ и только после выхода из ``_metrics_lock``.

Логгер подаётся через ``managers={"logger": MagicMock()}``: без слота ``logger``
``log_windowed`` молчит, а ``caplog`` не годится — порт пишет через
``get_std_logger``.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from ...logger_module.configs import LoggerChannelSchema, LoggerManagerConfig, LoggerScopeSchema
from ...logger_module.core.logger_manager import LoggerManager
from .. import StatsManager
from ..observation.observation_manager import ObservationManager
from ...channel_routing_module.interfaces import IChannel

#: Дедлайн hazard-тестов: поток, не успевший за него, считается зависшим.
_JOIN_DEADLINE_S = 5.0


class _CapturingChannel(IChannel):
    """Канал-шпион: копит снапшоты окна такими, какими их видит канал."""

    def __init__(self, name: str = "capture"):
        self._name = name
        self.received = []

    @property
    def name(self):
        return self._name

    def write(self, data):
        self.received.append(data)
        return {"status": "ok"}

    def close(self):
        pass


def _make_manager(logger=None, name: str = "KindConflictTest", **config) -> tuple[StatsManager, MagicMock]:
    """Менеджер с mock-логгером в слоте 'logger'.

    ``aggregation_interval == flush_interval``, чтобы посторонний WARNING про
    «пол темпа» не засорял список вызовов логгера.
    """
    mock_logger = logger if logger is not None else MagicMock()
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "channels": {},
            "aggregation_interval": 1.0,
            "flush_interval": 1.0,
            **config,
        },
        managers={"logger": mock_logger},
    )
    assert mgr.initialize() is True, "менеджер не инициализировался — сценарий недостоверен"
    return mgr, mock_logger


@pytest.fixture
def make_manager():
    """Фабрика менеджеров; на выходе все остановлены (иначе поток aggregation-window-timer течёт между тестами)."""
    made = []

    def make(*args, **kwargs):
        mgr, logger = _make_manager(*args, **kwargs)
        made.append(mgr)
        return mgr, logger

    yield make
    for mgr in made:
        mgr.shutdown()


def _conflicts(mgr: StatsManager):
    return mgr.get_stats().get("metric_kind_conflicts")


def test_timing_under_counter_counted(make_manager):
    mgr, _ = make_manager()
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    mgr.record_timing("x", 0.7)
    assert _conflicts(mgr) == 2


def test_counter_under_timing_counted(make_manager):
    mgr, _ = make_manager()
    mgr.record_timing("y", 0.5)
    mgr.record_metric("y")
    assert _conflicts(mgr) == 1


def test_one_warning_per_window(make_manager):
    mgr, logger = make_manager()
    mgr.record_metric("x")
    mgr.record_metric("y")
    mgr.record_timing("x", 0.5)
    mgr.record_timing("x", 0.7)
    mgr.record_timing("y", 0.5)
    assert logger.warning.call_count == 2


def test_conflict_not_emitted_after_flush(make_manager):
    mgr, _ = make_manager()
    # Канал-шпион стоит как tap: tap видит СЫРУЮ эмиссию. Через ``register_channel``
    # конфликтную запись не увидеть — окно агрегации держит вид первой серии и
    # в снапшоте тайминг под ``x`` не показывает (проверено на HEAD).
    spy = _CapturingChannel()
    mgr.add_tap(spy, min_level="DEBUG")
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    mgr.flush()
    emitted = [(r.get("name"), r.get("type")) for r in spy.received]
    assert ("x", "counter") in emitted, f"первая серия не дошла до шпиона — сценарий недостоверен: {emitted}"
    assert ("x", "timing") not in emitted


def test_first_series_kept(make_manager):
    mgr, _ = make_manager()
    mgr.record_metric("x")
    mgr.record_timing("x", 0.5)
    assert mgr.get_metric("x") == {"name": "x", "type": "counter", "tags": {}, "count": 1.0}


def test_live_ceiling_refusal_is_not_a_conflict(make_manager):
    """``rec is None`` (потолок живого слоя) — не конфликт: серии «b» в справочнике нет, сравнивать не с чем."""
    mgr, _ = make_manager(max_series=1)
    mgr.record_metric("a")
    mgr.record_metric("b")
    assert mgr.get_stats()["series_dropped"] == 1, "потолок не сработал — сценарий недостоверен"
    mgr.record_timing("b", 0.5)
    assert _conflicts(mgr) == 0
    mgr.record_timing("a", 0.5)
    assert _conflicts(mgr) == 1
    assert {m["name"] for m in mgr.get_all_metrics().values()} == {"a"}


def test_warning_that_records_metric_does_not_deadlock(make_manager):
    """Голос идёт через логгер, а логгер пишет метрику: под ``_metrics_lock`` это цикл на себя."""
    holder = {}
    logger = MagicMock()
    logger.warning.side_effect = lambda *a, **k: holder["mgr"].record_metric("other")
    mgr, _ = make_manager(logger=logger)
    holder["mgr"] = mgr
    mgr.record_metric("x")

    worker = threading.Thread(target=lambda: mgr.record_timing("x", 0.5), daemon=True)
    worker.start()
    worker.join(_JOIN_DEADLINE_S)

    assert not worker.is_alive(), "запись конфликта повисла: голос звучит под _metrics_lock"
    assert logger.warning.call_count == 1
    assert mgr.get_metric("other") is not None


def test_concurrent_conflicts_counted(make_manager):
    mgr, _ = make_manager()
    mgr.record_metric("x")
    threads_n, per_thread = 8, 50

    def hammer():
        for _ in range(per_thread):
            mgr.record_timing("x", 0.1)

    threads = [threading.Thread(target=hammer, daemon=True) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_JOIN_DEADLINE_S)

    assert not any(t.is_alive() for t in threads), "потоки не завершились за дедлайн"
    assert _conflicts(mgr) == 400


class _YieldingInt(int):
    """``int``, у которого ``+`` проходит через вызов Python: точка переключения потока между чтением и записью."""

    def __add__(self, other):
        value = int(self)
        time.sleep(0)
        return _YieldingInt(value + int(other))


def test_concurrent_conflicts_counted_with_forced_thread_switch(make_manager):
    """``+= 1`` на голом ``int`` в CPython 3.12 не прерывается между чтением и записью, и счёт без лока
    проходит обычный тест на 400. Здесь переключение потока между ними форсировано: потеря инкремента
    (счётчик вне ``_metrics_lock``) даёт меньше 400.

    Приватное имя ``_metric_kind_conflicts`` — только для НАЧАЛЬНОГО значения; результат читается
    публично через ``get_stats``.
    """
    mgr, _ = make_manager()
    mgr._metric_kind_conflicts = _YieldingInt(0)
    mgr.record_metric("x")

    def hammer():
        for _ in range(50):
            mgr.record_timing("x", 0.1)

    threads = [threading.Thread(target=hammer, daemon=True) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(_JOIN_DEADLINE_S)

    assert not any(t.is_alive() for t in threads), "потоки не завершились за дедлайн"
    assert _conflicts(mgr) == 400


def test_real_objects_port_attached_and_real_logger(tmp_path):
    """Боевая проводка: порт наблюдений подключён (дорога через порт), логгер настоящий, строка — в файле."""
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="kindconflict",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"common": LoggerChannelSchema(type="file", enabled=True, file_path="common.log", rotate=False)},
            default_level="DEBUG",
            scopes={"SYSTEM": LoggerScopeSchema(channels=["common"])},
        )
    )
    mgr, _ = _make_manager(logger=logger)
    port = ObservationManager(manager_name="ObservationManager", process=None)
    try:
        assert port.initialize() is True
        assert mgr.attach_observation_port(port) is True
        mgr.record_metric("x")
        mgr.record_timing("x", 0.5)
        mgr.record_timing("x", 0.7)
        logger.flush()
    finally:
        mgr.shutdown()
        port.shutdown()
        logger.shutdown()

    assert _conflicts(mgr) == 2
    assert mgr.get_metric("x") == {"name": "x", "type": "counter", "tags": {}, "count": 1.0}
    assert mgr.observation_bypasses == {}, "числа пошли мимо порта — сценарий недостоверен"
    lines = [ln for ln in (tmp_path / "common.log").read_text(encoding="utf-8").splitlines() if "другого вида" in ln]
    assert len(lines) == 1, lines
