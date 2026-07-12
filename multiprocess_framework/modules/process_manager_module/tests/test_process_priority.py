"""
Тесты для ProcessPriority.

Проверяют управление приоритетами процессов.
"""

import time
from multiprocessing import Process

from ..core.process_priority import ProcessPriority


def _dummy_target() -> None:
    time.sleep(2)


class TestProcessPriority:
    """Тесты ProcessPriority."""

    def test_register_priority(self) -> None:
        """register_priority() сохраняет приоритет."""
        priority = ProcessPriority()
        priority.register_priority("TestProcess", "high")

        assert priority.get_priority("TestProcess") == "high"

    def test_get_priority_default(self) -> None:
        """get_priority() возвращает default для неизвестного процесса."""
        priority = ProcessPriority()
        result = priority.get_priority("UnknownProcess", default="normal")

        assert result == "normal"

    def test_apply_priority_returns_bool(self) -> None:
        """apply_priority() возвращает bool (StubPlatform возвращает False)."""
        priority = ProcessPriority()
        priority.register_priority("TestProcess", "normal")

        process = Process(target=_dummy_target, name="TestProcess")
        process.start()
        time.sleep(0.05)

        result = priority.apply_priority(process, delay=0.01)

        assert isinstance(result, bool)

        process.terminate()
        process.join(timeout=1.0)

    def test_priority_with_logger(self) -> None:
        """ProcessPriority с logger работает."""
        logger = type("MockLogger", (), {"_log_info": lambda *a, **k: None, "_log_warning": lambda *a, **k: None})()
        priority = ProcessPriority(logger=logger)
        priority.register_priority("TestProcess", "high")

        assert priority.get_priority("TestProcess") == "high"


class _RecordingLogger:
    """Логгер-счётчик уровней для проверки one-shot priority-шума (Ж-5)."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.debugs: list[str] = []
        self.infos: list[str] = []

    def _log_warning(self, msg, **kw):
        self.warnings.append(msg)

    def _log_debug(self, msg, **kw):
        self.debugs.append(msg)

    def _log_info(self, msg, **kw):
        self.infos.append(msg)


class _FailingPlatform:
    """Платформа, для которой установка приоритета всегда не удаётся."""

    def apply_priority(self, process, priority_name) -> bool:
        return False


class _FakeProc:
    def __init__(self, name):
        self.name = name


class TestPriorityNoiseDedupByReasonZh5:
    """Ж-5 (RS-3): «Failed to set priority» — WARNING один раз НА УРОВЕНЬ, дальше debug."""

    def test_repeated_same_level_warn_once_then_debug(self) -> None:
        logger = _RecordingLogger()
        priority = ProcessPriority(logger=logger, platform_adapter=_FailingPlatform())

        # 5 отказов одного уровня 'normal' (как N процессов на каждый switch)
        for i in range(5):
            assert priority.set_priority(_FakeProc(f"p{i}"), "normal") is False

        # WARNING ровно один; остальные ушли в debug (шум подавлен, факт сохранён)
        assert len(logger.warnings) == 1
        assert len(logger.debugs) == 4

    def test_new_priority_level_surfaces_new_warning(self) -> None:
        """Новая причина (другой priority_name) НЕ давится глобальным флагом."""
        logger = _RecordingLogger()
        priority = ProcessPriority(logger=logger, platform_adapter=_FailingPlatform())

        priority.set_priority(_FakeProc("a"), "normal")  # WARNING #1 (normal)
        priority.set_priority(_FakeProc("b"), "normal")  # debug (повтор normal)
        priority.set_priority(_FakeProc("c"), "realtime")  # WARNING #2 (новый уровень)
        priority.set_priority(_FakeProc("d"), "realtime")  # debug (повтор realtime)

        assert len(logger.warnings) == 2  # по одному на каждый уровень
        assert len(logger.debugs) == 2
