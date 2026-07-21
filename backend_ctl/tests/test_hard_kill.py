# -*- coding: utf-8 -*-
"""Тесты кросс-платформенного ``_hard_kill_pid`` харнесса (Ф7 G.7 Фаза 2 fault-injection).

Windows не имеет ``signal.SIGKILL`` → ``os.kill`` бросает ``AttributeError``; хелпер
обязан упасть на ``psutil.Process(pid).kill()`` (TerminateProcess). Без этого фикса
``harness.kill_child`` (и live fault-тесты) не работают на Windows. Чистые юнит-кейсы
с мок-инъекцией — без запуска процессов.
"""

from __future__ import annotations

import psutil

import backend_ctl.harness as h


def test_posix_sigkill_path(monkeypatch):
    """POSIX: os.kill(pid, SIGKILL) вызван; psutil не трогается."""
    calls = []
    monkeypatch.setattr(h.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(h.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    logs: list[str] = []
    h._hard_kill_pid(1234, log=logs.append, name="victim")
    assert calls == [(1234, 9)]
    assert any("SIGKILL" in m for m in logs)


def test_windows_fallback_to_psutil(monkeypatch):
    """Windows: os.kill → AttributeError (нет SIGKILL) → psutil.Process(pid).kill()."""

    def _no_sigkill(pid, sig):
        raise AttributeError("module 'signal' has no attribute 'SIGKILL'")

    monkeypatch.setattr(h.os, "kill", _no_sigkill)
    killed: dict = {}

    class FakeProc:
        def __init__(self, pid):
            killed["pid"] = pid

        def kill(self):
            killed["called"] = True

    monkeypatch.setattr(psutil, "Process", FakeProc)
    logs: list[str] = []
    h._hard_kill_pid(4321, log=logs.append, name="victim")
    assert killed == {"pid": 4321, "called": True}
    assert any("psutil" in m for m in logs)


def test_already_dead_is_not_error(monkeypatch):
    """Уже мёртвый (ProcessLookupError) — не ошибка, psutil-путь не трогается."""

    def _dead(pid, sig):
        raise ProcessLookupError("no such process")

    monkeypatch.setattr(h.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(h.os, "kill", _dead)
    touched = {"psutil": False}
    monkeypatch.setattr(psutil, "Process", lambda pid: touched.__setitem__("psutil", True))
    logs: list[str] = []
    h._hard_kill_pid(999, log=logs.append)
    assert touched["psutil"] is False
    # Строка лога ASCII-only ОСОЗНАННО (см. _hard_kill_pid): консоль Windows в cp1251
    # не кодирует не-latin символы, и UnicodeEncodeError уронил бы вызывающего уже
    # ПОСЛЕ kill. Не «чинить» обратно на русский — тест проверяет фактический контракт.
    assert any("already dead" in m for m in logs)
