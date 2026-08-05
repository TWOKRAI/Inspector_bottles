# -*- coding: utf-8 -*-
"""Ф6.х.3 — ВЕСЬ класс ``QueueRegistry`` слышен, а не только детекторы потерь.

Ревью 2026-08-03: Ф6.8 оживила видом ``_loss_logger`` три точки потерь, но в том
же классе остались 12 вызовов мёртвой плоскости ``self._log_*`` —
``initialize() failed``, ``send_to_queue() failed``, ``Queue not found`` уходили
в никуда. Полкласса слышно, полкласса нет — хуже, чем ничего: читатель лога
верит, что молчание означает отсутствие событий.

Харнес — настоящий ``LoggerManager`` с файлом (по образцу
``test_evict_visibility``): дубль доказал бы форму вызова, а сломана была
именно доставка.
"""

from __future__ import annotations

from pathlib import Path
from queue import Full, Queue
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.shared_resources_module.queues.core.manager import QueueRegistry


@pytest.fixture
def logger_to_file(tmp_path: Path):
    config: Dict[str, Any] = {
        "app_name": "plane",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
        "scopes": {
            "SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
            "BUSINESS": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
            "DEBUG": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
        },
    }
    mgr = LoggerManager(manager_name="PlaneProbe", config=config)
    mgr.initialize()
    yield mgr, tmp_path / "a.log"
    mgr.shutdown()


class _NoQueueRegistry(QueueRegistry):
    """Реестр без единой очереди — ``get_queue`` всегда ``None``."""

    def get_queue(self, process_name: str, queue_type: str):  # type: ignore[override]
        return None


class _ExplodingQueue(Queue):
    """Очередь, падающая на чтении не-``Empty`` исключением."""

    def get_nowait(self):  # type: ignore[override]
        raise RuntimeError("транспорт сломан")


class _ExplodingReadRegistry(QueueRegistry):
    def get_queue(self, process_name: str, queue_type: str):  # type: ignore[override]
        return _ExplodingQueue()


class TestMissingQueueIsAudible:
    def test_missing_queue_writes_and_counts(self, logger_to_file) -> None:
        """Недоставленный груз назван в файле процесса и сосчитан."""
        _, log_file = logger_to_file
        reg = _NoQueueRegistry(manager_name="Plane")

        assert reg.send_to_queue("gui", "data", {"x": 1}) is False

        assert reg._stats["queue_missing"] == 1  # тот же доступ, что у соседей (test_evict_visibility)
        written = log_file.read_text(encoding="utf-8")
        assert "Queue 'data' not found for 'gui'" in written, f"потеря груза не дошла до плоскости логов: {written!r}"

    def test_throttle_limits_lines_but_not_the_count(self, logger_to_file) -> None:
        """Hot-path: счётчик растёт на каждый вызов, запись — раз в окно."""
        _, log_file = logger_to_file
        reg = _NoQueueRegistry(manager_name="Plane")

        for _ in range(100):
            reg.send_to_queue("gui", "data", {"x": 1})

        assert reg._stats["queue_missing"] == 100
        written = log_file.read_text(encoding="utf-8")
        assert written.count("Queue 'data' not found") == 1, "троттлинг не ограничил записи — шторм на hot-path"


class TestFailurePathsAreAudible:
    def test_receive_failure_is_written(self, logger_to_file) -> None:
        """Падение транспорта на чтении — строка в файле, а не тишина."""
        _, log_file = logger_to_file
        reg = _ExplodingReadRegistry(manager_name="Plane")

        assert reg.receive_from_queue("gui", "data") is None

        written = log_file.read_text(encoding="utf-8")
        assert "receive_from_queue('gui', 'data') failed" in written, f"сбой чтения проглочен: {written!r}"
        assert "транспорт сломан" in written


class _SilentlyFullQueue(Queue):
    """Очередь, падающая исключением БЕЗ текста — как настоящая ``mp.Queue``.

    ``queue.Full`` штатно поднимается без аргументов, поэтому ``str(exc)`` у неё
    пустая строка. Это не выдумка теста: именно так выглядел живой шторм.
    """

    def put_nowait(self, item):  # type: ignore[override]
        raise Full()

    def full(self):  # type: ignore[override]
        return False  # мимо ветки drop_oldest — интересует именно путь исключения


class _SilentlyFullRegistry(QueueRegistry):
    def get_queue(self, process_name: str, queue_type: str):  # type: ignore[override]
        return _SilentlyFullQueue()


class _SilentlyExplodingQueue(Queue):
    def get_nowait(self):  # type: ignore[override]
        raise RuntimeError()


class _SilentlyExplodingReadRegistry(QueueRegistry):
    def get_queue(self, process_name: str, queue_type: str):  # type: ignore[override]
        return _SilentlyExplodingQueue()


class TestFailureNamesItsCause:
    """Ревью Ф3 (Б-6, 2026-08-05): в живом шторме строка выглядела так —

    ``send_to_queue('gui', 'system') failed:`` и НИЧЕГО после двоеточия.

    Причина: ``%s`` от исключения без аргументов даёт пустую строку. Оператор
    видел следствие («не доставлено») без причины — класс «проглоченный сбой»:
    хуже, чем отсутствие записи, потому что запись есть и она пустая.
    Гарантия: сбой обязан назвать СВОЙ КЛАСС даже когда текста у него нет.
    """

    def test_send_failure_without_text_still_names_the_class(self, logger_to_file) -> None:
        _, log_file = logger_to_file
        reg = _SilentlyFullRegistry(manager_name="Plane")

        assert reg.send_to_queue("gui", "data", {"x": 1}) is False

        written = log_file.read_text(encoding="utf-8")
        assert "send_to_queue('gui', 'data') failed" in written, f"сбой отправки проглочен: {written!r}"
        assert "Full" in written, f"причина сбоя не названа — следствие без причины: {written!r}"

    def test_receive_failure_without_text_still_names_the_class(self, logger_to_file) -> None:
        _, log_file = logger_to_file
        reg = _SilentlyExplodingReadRegistry(manager_name="Plane")

        assert reg.receive_from_queue("gui", "data") is None

        written = log_file.read_text(encoding="utf-8")
        assert "receive_from_queue('gui', 'data') failed" in written, f"сбой чтения проглочен: {written!r}"
        assert "RuntimeError" in written, f"причина сбоя не названа — следствие без причины: {written!r}"
