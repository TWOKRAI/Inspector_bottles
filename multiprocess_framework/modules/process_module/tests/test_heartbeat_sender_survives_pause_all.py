# -*- coding: utf-8 -*-
"""Пауза процесса не имеет права глушить его признак жизни.

Живая находка (флап ``unresponsive ↔ running`` каждые ~5 с после ``worker.pause_all``):
``heartbeat_sender`` создавался без ``worker_type``, то есть как APPLICATION, и
``pause_all_workers(exclude_system=True)`` паузил его вместе с прикладными воркерами.
Дальше по цепочке: heartbeat молчит → ``ProcessMonitor._check_heartbeat_timeout``
объявляет процесс UNRESPONSIVE (статус ``paused`` он проверяет НАМЕРЕННО, полагаясь
ровно на то, что признак жизни продолжает идти) → супервизия рестартит живой процесс.

Три места в коде утверждали как факт, что этот воркер SYSTEM и потому не паузится
(``worker_manager.py:259-261``, ``process_monitor.py:911`` и докстринг проверки
таймаута) — и ни одно не было подкреплено регистрацией. Тест сторожит не имя типа,
а НАБЛЮДАЕМЫЙ эффект: воркер не поставлен на паузу.

Пара обязательна. Первое плечо (SYSTEM переживает паузу) в одиночку зелено и на
сломанном ``pause_all``, который не паузит вообще никого, — поэтому второе плечо
показывает, что стенд умеет ловить паузу.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ThreadPriority,
    WorkerManager,
)

_HEARTBEAT = "heartbeat_sender"
_APPLICATION = "app_worker"


class _Services:
    """Минимальный носитель: ровно то, что читает ``ProcessHeartbeat.start()``."""

    def __init__(self, worker_manager: WorkerManager) -> None:
        self.name = "proc"
        self.worker_manager = worker_manager
        self.heartbeats: list[dict] = []
        # Большой интервал: воркер должен СУЩЕСТВОВАТЬ и быть запущенным, но такт
        # за время теста сработать не обязан — иначе тест начал бы зависеть от сна.
        self._config = {"heartbeat_interval": 3600.0}

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def send_message(self, target: str, message: dict) -> bool:
        self.heartbeats.append(message)
        return True

    def log_info(self, msg: str, **kw) -> None: ...

    def log_debug(self, msg: str, **kw) -> None: ...

    def log_warning(self, msg: str, **kw) -> None: ...

    def log_error(self, msg: str, **kw) -> None: ...


def _idle_loop(stop_event, pause_event) -> None:
    """Тело прикладного воркера: живёт до стопа.

    Сигнатура — контракт ``WorkerLifecycle._worker_wrapper`` (``target(stop_event,
    pause_event)``). Без неё поток падает с TypeError, и стенд проверял бы паузу
    на мёртвом воркере: записи реестра и ``pause_event`` переживают падение потока,
    поэтому ассерты остались бы зелёными, а живого воркера в тесте бы не было.
    """
    stop_event.wait(timeout=30.0)


def _is_paused(wm: WorkerManager, name: str) -> bool:
    """Наблюдаемый эффект паузы — взведённый ``pause_event`` (см. pause_worker)."""
    info = wm._worker_registry.get(name)
    assert info is not None, f"воркер {name!r} не зарегистрирован — стенд собран неверно"
    return bool(info["pause_event"].is_set())


@pytest.fixture()
def wired() -> tuple:
    """Реальный WorkerManager + реальный ProcessHeartbeat.start() + прикладной воркер."""
    wm = WorkerManager(manager_name="wm_pause_all")
    wm.initialize()
    svc = _Services(wm)
    ProcessHeartbeat(svc).start()
    wm.create_worker(
        _APPLICATION,
        _idle_loop,
        ThreadConfig(priority=ThreadPriority.BACKGROUND),
        auto_start=True,
    )
    try:
        yield wm, svc
    finally:
        wm.stop_all_workers()


class TestHeartbeatSenderSurvivesPauseAll:
    def test_pause_all_pauses_application_worker_and_spares_heartbeat(self, wired) -> None:
        """Первое плечо: ``worker.pause_all`` глушит прикладной воркер, но не признак жизни."""
        wm, _ = wired

        wm.pause_all_workers(exclude_system=True)

        assert _is_paused(wm, _APPLICATION), "прикладной воркер обязан встать на паузу"
        assert not _is_paused(wm, _HEARTBEAT), (
            "heartbeat_sender поставлен на паузу вместе с прикладными — процесс замолчит, "
            "и супервизия объявит его UNRESPONSIVE при живом процессе"
        )

    def test_pause_all_without_exclusion_pauses_both(self, wired) -> None:
        """Второе плечо: стенд УМЕЕТ ловить паузу heartbeat'а.

        Без него первое плечо оставалось бы зелёным на ``pause_all``, который не
        паузит никого вовсе, — то есть проверяло бы отсутствие механизма, а не
        исключение из него.
        """
        wm, _ = wired

        wm.pause_all_workers(exclude_system=False)

        assert _is_paused(wm, _APPLICATION)
        assert _is_paused(wm, _HEARTBEAT), (
            "при exclude_system=False пауза обязана дойти и до heartbeat_sender — "
            "иначе стенд не различает 'исключён' и 'пауза не работает'"
        )

    def test_resume_all_returns_application_worker(self, wired) -> None:
        """Симметрия: resume снимает паузу с того, кого pause её поставил."""
        wm, _ = wired
        wm.pause_all_workers(exclude_system=True)

        wm.resume_all_workers(exclude_system=True)

        assert not _is_paused(wm, _APPLICATION)
        assert not _is_paused(wm, _HEARTBEAT)
