# -*- coding: utf-8 -*-
"""
adapters/tests/test_project_holder.py -- тесты ProjectHolder (Task D.3).

Покрывает:
    1. get() возвращает initial Project
    2. set() обновляет текущий Project
    3. Concurrent get/set из 2 потоков — thread-safety, никаких исключений
    4. RLock re-entrant: get() внутри set()-коллбэка не вызывает deadlock

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.3)
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_prototype.adapters.dispatch.project_holder import ProjectHolder
from multiprocess_prototype.domain.entities.project import Project
from multiprocess_prototype.domain.entities.topology import Topology


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def _make_project(**overrides: Any) -> Project:
    """Создать Project с пустой (или переопределённой) topology."""
    defaults: dict[str, Any] = {"topology": Topology()}
    defaults.update(overrides)
    return Project(**defaults)


@pytest.fixture
def project() -> Project:
    """Начальный пустой Project."""
    return _make_project()


@pytest.fixture
def holder(project: Project) -> ProjectHolder:
    """ProjectHolder с начальным Project."""
    return ProjectHolder(initial=project)


# ---------------------------------------------------------------------------
# Тест 1: get() возвращает initial Project
# ---------------------------------------------------------------------------


def test_holder_get_returns_initial(project: Project) -> None:
    """ProjectHolder(p).get() возвращает именно тот объект p, что был передан."""
    holder = ProjectHolder(initial=project)
    assert holder.get() is project


# ---------------------------------------------------------------------------
# Тест 2: set() обновляет текущий Project
# ---------------------------------------------------------------------------


def test_holder_set_updates_current(project: Project) -> None:
    """После set(p2) — get() возвращает p2, а не исходный p."""
    holder = ProjectHolder(initial=project)

    p2 = _make_project()
    holder.set(p2)

    assert holder.get() is p2
    assert holder.get() is not project


# ---------------------------------------------------------------------------
# Тест 3: concurrent get/set из 2 потоков — thread-safety
# ---------------------------------------------------------------------------


def test_holder_thread_safe_concurrent_get_set() -> None:
    """2 потока: writer set'ит 100 раз, reader get'ит 100 раз.

    Никаких исключений, никаких partial reads. Project frozen,
    поэтому reader всегда видит целостный instance.
    """
    initial = _make_project()
    holder = ProjectHolder(initial=initial)

    errors: list[Exception] = []
    iterations = 100

    # Барьер для синхронного старта обоих потоков
    barrier = threading.Barrier(2)

    def writer() -> None:
        barrier.wait()
        for _ in range(iterations):
            new_p = _make_project()
            holder.set(new_p)
            time.sleep(0.0001)

    def reader() -> None:
        barrier.wait()
        for _ in range(iterations):
            try:
                p = holder.get()
                # Project frozen — should always be a valid instance
                assert isinstance(p, Project)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            time.sleep(0.0001)

    t_writer = threading.Thread(target=writer)
    t_reader = threading.Thread(target=reader)

    t_writer.start()
    t_reader.start()
    t_writer.join(timeout=10)
    t_reader.join(timeout=10)

    # Ни один поток не завис (join timeout не истёк)
    assert not t_writer.is_alive(), "writer thread hung"
    assert not t_reader.is_alive(), "reader thread hung"

    # Нет исключений из reader
    assert errors == [], f"reader raised: {errors}"


# ---------------------------------------------------------------------------
# Тест 4: RLock re-entrant — get() внутри set()-коллбэка не deadlock
# ---------------------------------------------------------------------------


def test_holder_reentrant_lock(project: Project) -> None:
    """RLock — re-entrant: внутри set() можно вызвать get() без deadlock.

    Эмулируем сценарий, когда обёртка вокруг set() хочет прочитать
    текущее значение через get() (например, для audit или logging).
    При обычном Lock это вызвало бы deadlock (одним потоком).
    """
    holder = ProjectHolder(initial=project)

    # Держим lock явно (от имени «внешнего» кода), потом вызываем get
    # RLock позволяет повторный захват тем же потоком
    with holder._lock:  # noqa: SLF001 — тест намеренно обращается к приватному
        # Должно НЕ deadlock'нуть (RLock re-entrant)
        current = holder.get()
        assert current is project
