# -*- coding: utf-8 -*-
"""Hazard-тесты механизма дренажа headless-презентации (план D8).

Что может сломаться ИМЕННО здесь — по устройству, а не по спеке:

* воркер не создан или создан не запущенным → не дренирует никто, а снаружи
  процесс выглядит живым (очередь наполняется, отправители получают отказ);
* цикл читает не ту очередь → либо не дренирует, либо ворует system-трафик у
  ``message_processor`` (команды перестают отвечать);
* одиночный отказ ``receive`` убивает поток → дренаж умирает молча, и «дренирует»
  снаружи неотличимо от «умер»: очередь наполняется в обоих случаях;
* цикл не слышит ``stop_event`` → останов виснет.

Цикл гоняется в ДЕМОН-потоке с дедлайном на ``join``: тест, который висит вместо
падения, хуже отсутствующего — он прячет регрессию за таймаутом.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_prototype.frontend.headless_process import (
    DRAIN_WORKER,
    HeadlessGuiProcess,
)

#: Дедлайн ожидания потока. Дренаж опрашивает очередь с таймаутом 0.1 с —
#: одного порядка с ним, но с запасом на планировщик Windows (15.6 мс сетка).
_JOIN_DEADLINE = 5.0


class _RecordingWorkerManager:
    """Дубль менеджера воркеров, который ПОМНИТ, что у него просили создать.

    Умеет отказывать: если ``create_worker`` не позвали, ``created`` останется
    пустым — дубль, который всегда успешен, не проверял бы ничего.
    """

    def __init__(self) -> None:
        self.created: list = []

    def create_worker(self, name, fn, config, auto_start=False):
        self.created.append({"name": name, "fn": fn, "config": config, "auto_start": auto_start})
        return object()


class _Router:
    """Дубль роутера: записывает аргументы ``receive``, умеет бросать и БЛОКИРУЕТ.

    Блокировка на ``timeout`` — не украшение, а верность оригиналу: настоящий
    ``RouterManager.receive(timeout=0.1)`` ждёт на пустой очереди. Первая редакция
    дубля отвечала мгновенно, и цикл дренажа крутился без сна — под инъекцией
    «цикл не слышит stop_event» это давало не красный тест, а разгон по памяти
    (список вызовов рос безостановочно). Дубль, ведущий себя не как оригинал,
    превращает инъекцию в негодную.
    """

    def __init__(self, raises: int = 0) -> None:
        self.calls: list = []
        self._raises = raises

    def receive(self, **kwargs):
        self.calls.append(kwargs)
        time.sleep(float(kwargs.get("timeout") or 0.0))
        if self._raises > 0:
            self._raises -= 1
            raise RuntimeError("очередь недоступна")
        return []


def _make_process(*, worker_manager=None, router=None) -> HeadlessGuiProcess:
    """Собрать процесс БЕЗ тяжёлого ``__init__`` — судятся его собственные методы.

    Полный ``ProcessModule.__init__`` поднимает менеджеры, очереди и потоки; для
    свойств дренажа это лишний стенд, а не более честный.
    """
    proc = object.__new__(HeadlessGuiProcess)
    proc.name = "gui"
    proc.config = {}
    proc._orchestrator = None
    proc.worker_manager = worker_manager
    proc.router_manager = router
    proc.logged = []
    proc.tracked = []
    proc._log_info = lambda msg, **kw: proc.logged.append(("info", msg))
    proc._log_error = lambda msg, **kw: proc.logged.append(("error", msg))
    proc._track_error = lambda exc, **kw: proc.tracked.append(exc)
    return proc


class TestDrainWorkerCreation:
    def test_drain_worker_is_created_and_started(self) -> None:
        """Без auto_start воркер существовал бы, но не дренировал."""
        wm = _RecordingWorkerManager()
        proc = _make_process(worker_manager=wm)

        proc._init_application_threads()

        assert [w["name"] for w in wm.created] == [DRAIN_WORKER]
        assert wm.created[0]["auto_start"] is True
        assert wm.created[0]["fn"] == proc._drain_loop

    def test_absent_worker_manager_is_loud(self) -> None:
        """Некому дренировать — обязан быть ERROR, иначе снаружи это выглядит
        как работающий приёмник при наполняющейся очереди."""
        proc = _make_process(worker_manager=None)

        proc._init_application_threads()

        errors = [msg for level, msg in proc.logged if level == "error"]
        assert errors, "отсутствие worker_manager прошло молча"
        assert "дренир" in errors[0], errors[0]


class TestDrainLoop:
    def _run_loop(self, proc, *, stop_after: float = 0.35):
        """Погонять цикл в демон-потоке и снять его по дедлайну."""
        stop_event = threading.Event()
        pause_event = threading.Event()
        thread = threading.Thread(target=proc._drain_loop, args=(stop_event, pause_event), daemon=True)
        thread.start()
        time.sleep(stop_after)
        stop_event.set()
        thread.join(_JOIN_DEADLINE)
        return thread

    def test_loop_reads_only_the_data_queue(self) -> None:
        """system/state/observability дренирует ``message_processor``; забрать их
        сюда — увести команды из-под обработчика."""
        proc = _make_process(router=_Router())

        self._run_loop(proc)

        assert proc.router_manager.calls, "цикл не сделал ни одного receive"
        for call in proc.router_manager.calls:
            assert call["channel_types"] == ["data"], call
            assert call["return_messages"] is False, call

    def test_loop_stops_on_stop_event(self) -> None:
        """Иначе останов процесса виснет на этом потоке."""
        proc = _make_process(router=_Router())

        thread = self._run_loop(proc)

        assert not thread.is_alive(), f"цикл не вышел за {_JOIN_DEADLINE} с после stop_event"

    def test_single_receive_failure_does_not_kill_the_drain(self) -> None:
        """Один отказ — не смерть дренажа: после него receive продолжается."""
        proc = _make_process(router=_Router(raises=1))

        self._run_loop(proc, stop_after=0.5)

        assert len(proc.router_manager.calls) > 1, "после отказа цикл не продолжился"

    def test_receive_failure_is_reported_not_swallowed(self) -> None:
        """«Дренирует» и «умер» обязаны различаться снаружи."""
        proc = _make_process(router=_Router(raises=1))

        self._run_loop(proc, stop_after=0.5)

        assert proc.tracked, "отказ receive проглочен молча"
        assert isinstance(proc.tracked[0], RuntimeError)

    def test_pause_event_suspends_reading(self) -> None:
        """На паузе очередь не читается — иначе пауза ничего не значит."""
        proc = _make_process(router=_Router())
        stop_event, pause_event = threading.Event(), threading.Event()
        pause_event.set()
        thread = threading.Thread(target=proc._drain_loop, args=(stop_event, pause_event), daemon=True)
        thread.start()
        time.sleep(0.3)
        paused_calls = len(proc.router_manager.calls)
        pause_event.clear()
        time.sleep(0.3)
        stop_event.set()
        thread.join(_JOIN_DEADLINE)

        assert paused_calls == 0, f"на паузе сделано {paused_calls} чтений"
        assert len(proc.router_manager.calls) > 0, "после снятия паузы чтение не возобновилось"


class TestNoQtDependency:
    def test_module_imports_without_qt(self) -> None:
        """Headless-воплощение обязано подниматься там, где Qt нет вовсе:
        импорт модуля не должен тянуть PySide6.
        """
        import subprocess
        import sys

        code = (
            "import sys;"
            "sys.modules['PySide6'] = None;"
            "import multiprocess_prototype.frontend.headless_process as m;"
            "print(m.HeadlessGuiProcess.__name__)"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2000:]
        assert "HeadlessGuiProcess" in result.stdout


if __name__ == "__main__":  # pragma: no cover — Windows spawn-guard
    pytest.main([__file__])
