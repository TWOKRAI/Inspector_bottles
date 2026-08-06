"""Очередь класса "observability": роняет старейшее и МОЛЧИТ при этом (Ф7.3).

Хвост записей (``log.record`` / ``observability.record``) съехал с never-drop
system-почты на свой класс груза. Два свойства, ради которых задача и делалась:

1. **Переполнение хвоста не блокирует управление** — drop_oldest вместо
   ``system_evict_blocked``, на обоих положениях ``FW_QOS_PROFILES``.
2. **Пути потери хвоста не пишут записей** — иначе потеря записи порождает новую
   запись в тот же хвост (петля Б-6: 97 066 отказов доставки за ~25 минут).
   Взамен потеря видна счётчиками — молчания нет, есть молчание В ЛОГАХ.

Второе свойство проверяется НАБЛЮДАЕМЫМ эффектом (перехват вызовов настоящего
``_loss_logger``), а не именем метода: спай на имя сторожил бы имя, а не свойство.
"""

import logging
import queue as _queue

import pytest

from ..queues import QueueRegistry
from ..queues.core import manager as manager_module
from ..state.process_data import ProcessDataKeys
from ..state.process_state_registry import ProcessStateRegistry

OBS = ProcessDataKeys.QUEUE_OBSERVABILITY


class _RecordingLogger:
    """Вид логгера, считающий ЛЮБУЮ запись (не важно, каким уровнем)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _add(self, level: str, msg: str, *args, **kwargs) -> None:
        self.records.append((level, msg % args if args else msg))

    def debug(self, msg, *args, **kwargs):
        self._add("DEBUG", msg, *args)

    def info(self, msg, *args, **kwargs):
        self._add("INFO", msg, *args)

    def warning(self, msg, *args, **kwargs):
        self._add("WARNING", msg, *args)

    def error(self, msg, *args, **kwargs):
        self._add("ERROR", msg, *args)

    def critical(self, msg, *args, **kwargs):
        self._add("CRITICAL", msg, *args)


@pytest.fixture
def silent_probe(monkeypatch):
    """Подменить единственный живой лог-канал файла на счётчик записей."""
    probe = _RecordingLogger()
    monkeypatch.setattr(manager_module, "_loss_logger", probe)
    return probe


def _registry(qos_profiles: bool, qtype: str, maxsize: int = 1, prefill: int = 1):
    """QueueRegistry с процессом 'gui' и его очередью ``qtype`` (предзаполненной)."""
    psr = ProcessStateRegistry()
    psr.register_process("gui")
    q = _queue.Queue(maxsize=maxsize)
    for i in range(prefill):
        q.put({"old": i})
    psr.add_queue("gui", qtype, q)
    reg = QueueRegistry(process_state_registry=psr, qos_profiles=qos_profiles)
    reg.initialize()
    # initialize() пишет INFO — это шум установки стенда, а не поведение под тестом.
    _drop_setup_records()
    return reg, q


def _drop_setup_records() -> None:
    """Забыть записи, сделанные при постройке стенда (``initialize``)."""
    probe = getattr(manager_module._loss_logger, "records", None)
    if probe is not None:
        probe.clear()


class TestObservabilityQueueDropsOldest:
    @pytest.mark.parametrize("qos_profiles", [False, True])
    def test_full_tail_evicts_not_blocks(self, qos_profiles, silent_probe):
        """Полная очередь хвоста → drop_oldest: доставка проходит, управление не
        блокируется. Свой счётчик, а не ``data_evicted``: «теряем диагностику» и
        «теряем кадры» — разные аварии, и различать их надо снаружи."""
        reg, q = _registry(qos_profiles, OBS)

        ok = reg.send_to_queue("gui", OBS, {"command": "log.record", "n": 1})

        assert ok is True
        assert reg.observability_evicted == 1
        assert reg.data_evicted == 0
        assert reg.system_evict_blocked == 0
        assert q.qsize() == 1
        assert q.get_nowait()["n"] == 1

    @pytest.mark.parametrize("qos_profiles", [False, True])
    def test_eviction_writes_no_log_record(self, qos_profiles, silent_probe):
        """Вытеснение хвоста НЕ пишет ни одной записи — иначе петля самоусиления."""
        reg, _q = _registry(qos_profiles, OBS)

        reg.send_to_queue("gui", OBS, {"command": "log.record"})

        assert silent_probe.records == []

    def test_data_eviction_still_speaks(self, silent_probe):
        """Контраст: у data-очереди вытеснение по-прежнему ГОВОРИТ (throttled WARNING).
        Без этой пары «молчит» нельзя отличить от «сломали логирование целиком»."""
        reg, _q = _registry(False, "data")

        reg.send_to_queue("gui", "data", {"type": "data"})

        assert reg.data_evicted == 1
        assert [lvl for lvl, _ in silent_probe.records] == ["WARNING"]

    def test_per_victim_breakdown(self, silent_probe):
        """Пер-жертвенный ключ — «где» переполняется, а не только «сколько»."""
        reg, _q = _registry(False, OBS)

        reg.send_to_queue("gui", OBS, {"command": "log.record"})

        assert reg.get_stats()["queues"][f"observability_evicted.gui.{OBS}"] == 1


class TestObservabilitySendFailureIsCountedNotLogged:
    @pytest.mark.parametrize("qos_profiles", [False, True])
    def test_full_after_evict_race(self, qos_profiles, silent_probe):
        """Гонка «после вытеснения очередь снова полна» → put падает.

        Воспроизводится очередью, которая на ``get_nowait`` отдаёт элемент, но
        остаётся полной — ровно то, что даёт второй отправитель между вытеснением
        и put. Свойство: счётчик растёт, записи нет, ``errors`` не засоряется
        (под штормом он перестал бы отличать поломку транспорта от обилия
        диагностики — этой слепотой Б-6 и запомнился).
        """

        class _AlwaysFull(_queue.Queue):
            def full(self):
                return True

            def put_nowait(self, item):
                raise _queue.Full()

        psr = ProcessStateRegistry()
        psr.register_process("gui")
        q = _AlwaysFull(maxsize=1)
        q.put({"old": 0})
        psr.add_queue("gui", OBS, q)
        reg = QueueRegistry(process_state_registry=psr, qos_profiles=qos_profiles)
        reg.initialize()
        _drop_setup_records()

        ok = reg.send_to_queue("gui", OBS, {"command": "log.record"})

        assert ok is False
        assert reg.observability_send_failed == 1
        assert silent_probe.records == []
        assert reg.get_stats()["queues"]["errors"] == 0

    def test_data_send_failure_still_speaks(self, silent_probe):
        """Контраст: отказ put в data-очередь по-прежнему пишет ERROR и растит ``errors``."""

        class _AlwaysFull(_queue.Queue):
            def full(self):
                return False

            def put_nowait(self, item):
                raise _queue.Full()

        psr = ProcessStateRegistry()
        psr.register_process("gui")
        psr.add_queue("gui", "data", _AlwaysFull(maxsize=1))
        reg = QueueRegistry(process_state_registry=psr)
        reg.initialize()
        _drop_setup_records()

        ok = reg.send_to_queue("gui", "data", {"type": "data"})

        assert ok is False
        assert [lvl for lvl, _ in silent_probe.records] == ["ERROR"]
        assert reg.get_stats()["queues"]["errors"] == 1


class TestNameIsShared:
    def test_router_literal_matches_canonical_constant(self):
        """Роутер дублирует имя очереди литералом (как ``delta_dispatcher`` для state).
        Тест — единственное, что удерживает две копии вместе."""
        from ....modules.router_module.core.router_manager import QUEUE_OBSERVABILITY

        assert QUEUE_OBSERVABILITY == ProcessDataKeys.QUEUE_OBSERVABILITY

    def test_qos_profile_is_droppable(self):
        """Профиль хвоста — best_effort/drop_oldest. Если он станет never-drop,
        расщепление обессмыслится: очередь снова начнёт душить отправителя."""
        from ..qos import qos_for

        assert qos_for(ProcessDataKeys.QUEUE_OBSERVABILITY).never_drop is False


def test_probe_itself_can_see_records(silent_probe):
    """Страж стража: перехват действительно ловит записи. Без этого тесты
    «записей нет» проходили бы и при сломанном перехвате (молчащий детектор
    ничего не доказывает)."""
    manager_module._loss_logger.error("проверка перехвата %d", 1)

    assert silent_probe.records == [("ERROR", "проверка перехвата 1")]


def test_std_logger_module_is_not_stdlib_root():
    """Контроль допущения: файл логирует своим видом, а не stdlib-root."""
    assert not isinstance(manager_module._loss_logger, logging.Logger)
