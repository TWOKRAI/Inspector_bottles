# -*- coding: utf-8 -*-
"""Live-тест: watch на реальном сокете НЕ заводит контура автоподписки (Task 5.11.h).

**Что тут было раньше.** Файл назывался ``test_applier_thread_close_live.py`` и
доказывал закрытие A.2: ``close()`` гасит daemon-поток ``backend-ctl-resub``,
который иначе навсегда висел в ``q.get()`` (``DriverSession.reset()`` зовёт
``close()``, а не ``unwatch()``, — зомби-поток на каждый реконнект MCP-сессии).

**Почему тест сменился, а не просто удалён.** Task 5.11.h снесла сам контур:
переподписку свежих инкарнаций делает брокер на оркестраторе, у которого есть
сигнал «поднялась новая». Утечка A.2 закрыта не гашением потока, а отсутствием
потока — но именно это и надо сторожить: вернуть applier обратно значит вернуть и
дедлок-путь, вокруг которого он строился, и утечку, которую A.2 чинил.

Проверяется на ЖИВОМ сокете, а не на фейке: у фейка нет reader-потока, и
конструкция, которую applier обходил, там не воспроизводится вовсе.

Собственный порт 8786 (≥8770; ловушка «двух бэкендов» — свой порт изолирует, см.
backend_ctl/AGENTS.md, project_concurrent_backends_trap).
"""

from __future__ import annotations

import threading

import pytest

from backend_ctl.driver import BackendDriver, _leaf_result
from backend_ctl.harness import BackendHarness

_PORT = 8786


@pytest.fixture(scope="module")
def applier_backend():
    """Свой headless-бэкенд для watch-тестов на уникальном порту."""
    harness = BackendHarness(with_base=True, port=_PORT)
    harness.start()
    try:
        yield harness
    finally:
        harness.stop()


def _resub_threads() -> list:
    return [t for t in threading.enumerate() if t.name == "backend-ctl-resub"]


@pytest.mark.harness_smoke
def test_live_watch_starts_no_applier_thread(applier_backend) -> None:
    """watch_like_gui на реальном сокете → потока автоподписки НЕТ вовсе."""
    drv = BackendDriver(port=_PORT)
    drv.connect()
    try:
        summary = drv.watch_like_gui()
        assert summary.get("success") is True, f"watch_like_gui не success: {summary}"

        assert _resub_threads() == [], "контур автоподписки воскрешён на живом сокете"
        assert not hasattr(drv._watch, "_resub_thread")
        # Хвост включён ОДНИМ намерением брокеру, а не циклом по процессам.
        obs = summary.get("observability") or {}
        assert obs.get("success") is not False, f"брокер не принял намерение: {obs}"

        drv.close()
        assert drv._watch._watch_active is False, "close() обязан снять активность профиля"
        drv.close()  # идемпотентность
    finally:
        drv.close()


@pytest.mark.harness_smoke
def test_live_reconnect_cycles_leak_nothing(applier_backend) -> None:
    """N реконнект-циклов на реальном сокете — ни одного потока автоподписки.

    Регресс A.2 (зомби-поток на каждый реконнект) теперь невозможен структурно;
    тест сторожит именно структуру, а не аккуратность гашения.
    """
    for _ in range(5):
        drv = BackendDriver(port=_PORT)
        drv.connect()
        summary = drv.watch_like_gui()
        assert summary.get("success") is True, f"watch_like_gui не success: {summary}"
        drv.close()

    alive = _resub_threads()
    assert alive == [], f"потоки автоподписки после реконнект-циклов: {alive}"

    # Имя теста обещает «leak nothing» — значит и на СЕРВЕРНОЙ стороне тоже.
    # Замечание ревью Fable (находка 4): прежняя версия сторожила только клиентские
    # потоки, при этом сама оставляла по мёртвому намерению на каждый цикл. Теперь
    # разрыв соединения снимает намерение (5.11-R1), и это здесь же и проверяется.
    probe = BackendDriver(port=_PORT)
    probe.connect()
    try:
        snap = _leaf_result(probe.send_command("ProcessManager", "introspect.observability", timeout=15.0))
        broker = snap.get("broker") or {}
        assert broker.get("count", 0) == 0, f"мёртвые намерения после реконнект-циклов: {broker}"
    finally:
        probe.close()
