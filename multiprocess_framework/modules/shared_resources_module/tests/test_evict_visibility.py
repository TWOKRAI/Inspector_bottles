# -*- coding: utf-8 -*-
"""Ф6.8 — вытеснение из очереди перестаёт быть невидимым.

Находка Н-2 живого прогона (2026-08-03): 246 вытеснений кадров, ноль строк в
логах. Детектор СУЩЕСТВОВАЛ (throttled WARNING) и был **мёртв по построению**:

  1. штатная плоскость (``self._log_*``) у ``QueueRegistry`` не подключена ни в
     одном процессе — ни один продовый вызов не передаёт logger, а ``_registry``
     не переживает pickle при spawn;
  2. запасной путь вёл в ``logging.getLogger(__name__)``, у которого в процессах
     фреймворка нет ни одного хендлера, — то есть тоже в никуда.

Плюс **атрибуция была перевёрнута**: ``data_evicted`` считается у ОТПРАВИТЕЛЯ, а
вытесняется очередь ПОЛУЧАТЕЛЯ, и запись жертву не называла. «246 у points»
читалось как «переполнена очередь points», хотя points переполнял чужую.

Заявленные свойства:

  A. вытеснение доходит до процессного ``LoggerManager`` (запись в файле);
  B. в записи назван ПОЛУЧАТЕЛЬ, чья очередь переполнена;
  C. пер-жертвенный счётчик отделяет «сколько» от «где»;
  D. троттлинг ограничивает записи, но НЕ учёт;
  E. блокировка вытеснения из never-drop очереди видна тем же путём.
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.shared_resources_module.queues.core.manager import QueueRegistry


@pytest.fixture
def logger_to_file(tmp_path: Path):
    """Настоящий процессный LoggerManager, пишущий в файл.

    Не дубль: проверяется именно то, что запись ДОЕЗЖАЕТ до плоскости логов
    процесса. Дубль доказал бы форму вызова — а сломано было как раз то, что
    вызов никуда не приходил.
    """
    config: Dict[str, Any] = {
        "app_name": "evict",
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
    mgr = LoggerManager(manager_name="EvictProbe", config=config)
    mgr.initialize()
    yield mgr, tmp_path / "a.log"
    mgr.shutdown()


class _FullQueueRegistry(QueueRegistry):
    """Реестр, у которого очередь получателя всегда полна и всегда одна и та же."""

    def __init__(self, queue: Queue, **kwargs: Any) -> None:
        super().__init__(manager_name="EvictRegistry", **kwargs)
        self._fixed_queue = queue

    def get_queue(self, process_name: str, queue_type: str):  # type: ignore[override]
        return self._fixed_queue


def _full_queue(size: int = 1) -> Queue:
    """Полная очередь — на stdlib ``queue.Queue``, а НЕ ``multiprocessing.Queue``.

    У ``multiprocessing.Queue`` питатель асинхронный: сразу после
    ``get_nowait()`` + ``put_nowait()`` и ``full()``, и сам ``put`` какое-то
    время ведут себя недетерминированно — на 200 попытках счётчик вытеснений
    давал то 164, то 178, а одиночный ``send_to_queue`` то проходил, то падал
    с ``Full`` в зависимости от того, что гонялось в прогоне до него. Тест с
    плавающим результатом не отличает регресс от собственной флейковости.

    Проверяемое свойство — учёт и запись у ``QueueRegistry``, а не семантика
    ``multiprocessing``; интерфейс у обеих очередей один. Тот же приём в
    соседнем ``test_never_drop_loss_visibility.py``.
    """
    q: Queue = Queue(maxsize=size)
    for i in range(size):
        q.put_nowait(f"старое-{i}")
    assert q.full(), "очередь обязана быть полной детерминированно"
    return q


class TestEvictionReachesTheLogPlane:
    def test_eviction_is_written_and_names_the_victim(self, logger_to_file) -> None:
        """A + B — запись доезжает до файла и называет ПОЛУЧАТЕЛЯ, а не отправителя."""
        mgr, log_file = logger_to_file
        reg = _FullQueueRegistry(_full_queue())

        assert reg.send_to_queue("seg", "data", "новый кадр") is True
        mgr.flush()

        written = log_file.read_text(encoding="utf-8")
        assert "seg" in written, f"жертва не названа: {written!r}"
        assert "ПОЛУЧАТЕЛЯ" in written, f"запись не отличает жертву от отправителя: {written!r}"

    def test_never_drop_block_is_written_too(self, logger_to_file) -> None:
        """E — блокировка вытеснения из system-очереди идёт тем же живым путём."""
        mgr, log_file = logger_to_file
        reg = _FullQueueRegistry(_full_queue())

        reg.remove_old_if_full(reg._fixed_queue, "system", victim_process="pult")
        mgr.flush()

        written = log_file.read_text(encoding="utf-8")
        assert "pult" in written and "system" in written, f"блокировка невидима: {written!r}"


class TestVictimAttribution:
    def test_per_victim_counter_separates_where_from_how_many(self) -> None:
        """C — общий счётчик отвечает «сколько», пер-жертвенный «где»."""
        reg = _FullQueueRegistry(_full_queue())

        reg.send_to_queue("seg", "data", "кадр-1")
        reg.send_to_queue("lines", "data", "кадр-2")
        reg.send_to_queue("seg", "data", "кадр-3")

        stats = reg._stats
        assert stats["data_evicted"] == 3, "общий счётчик обязан остаться прежним по смыслу"
        assert stats["data_evicted.seg.data"] == 2
        assert stats["data_evicted.lines.data"] == 1

    def test_counter_survives_unknown_victim(self) -> None:
        """Прямой вызов без имени жертвы не роняет учёт — только теряет адрес."""
        reg = _FullQueueRegistry(_full_queue())

        reg.remove_old_if_full(reg._fixed_queue, "data")

        assert reg._stats["data_evicted"] == 1
        assert reg._stats["data_evicted.?.data"] == 1


class TestThrottling:
    def test_storm_is_counted_fully_but_written_sparsely(self, logger_to_file) -> None:
        """D — троттлируется ЗАПИСЬ, а не учёт.

        Пара обязательна: счётчик без ограничения записи вернул бы 645 МБ, а
        ограничение записи без полного счётчика — потерянную арифметику потерь.
        """
        mgr, log_file = logger_to_file
        reg = _FullQueueRegistry(_full_queue())

        for i in range(200):
            reg.send_to_queue("seg", "data", f"кадр-{i}")
        mgr.flush()

        assert reg._stats["data_evicted"] == 200, "учёт пострадал от троттлинга"
        lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if "drop_oldest" in ln]
        assert 1 <= len(lines) <= 3, f"шторм записей: {len(lines)} строк на 200 вытеснений"
