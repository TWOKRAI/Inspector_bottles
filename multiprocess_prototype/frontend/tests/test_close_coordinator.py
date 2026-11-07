# -*- coding: utf-8 -*-
"""Слепая приёмка gui-graceful-close 1.1: «крестик ждёт остановки системы» (CloseCoordinator).

Тесты построены ТОЛЬКО из критериев приёмки (блок ПОВЕДЕНИЕ A-H брифа) и интерфейса заглушки
``multiprocess_prototype/frontend/shutdown/close_coordinator.py``. Устройство реализации не читалось.

Что проверяется (наблюдаемый эффект, а не имена внутренних вызовов):

* A/B. Крестик: ``CONFIRMING`` -> вопрос -> ``send_shutdown`` ровно один раз -> ``STOPPING``; «Отмена» и сбои;
  повторный крестик вне ``RUNNING`` ничего не делает.
* C. Опрос: ``poll_status(1.0)`` вне главного потока, не более одного запроса в полёте, результат в главном потоке;
  «все процессы остановлены» только по успешному непустому ответу, ``ignore_names`` не ждём.
* D. Сторож тишины на фейковых часах: ``clock() - last >= no_answer_s``, ``last = max(t_send, t_last_success,
  t_wait_click, t_force)``; вопрос, «Остановить», «Подождать», хвост после force, ``unattended``.
* E. ``MainWindow.closeEvent`` с координатором (настоящее окно, настоящая ``TopologySession``).
* F/G/H. ``backend_gone`` / safety-тик, рестарт UI, диалог прогресса.

Правила файла: ожидаемые значения - литералы; фейки внедряются вызовами; ``poll_status`` идёт на реальном пуле
``QThreadPool.globalInstance()``, блокирующий фейк держит ``threading.Event``, teardown его освобождает.
Время - только фейковые часы; отрицательные утверждения («не спросили», «не отправили») ждут несколько тиков
таймера (``poll_interval_ms=20``), поэтому они могут быть лишь слабее, но не ложно-красными.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
from PySide6.QtCore import QSettings, Qt, QThreadPool
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QProgressDialog, QPushButton, QWidget
from pytestqt.exceptions import TimeoutError as QtTimeoutError

from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.shutdown.close_coordinator import CloseCoordinator, CloseState
from multiprocess_prototype.frontend.windows.main_window import MainWindow

_DIALOG_TARGET = "multiprocess_prototype.frontend.widgets.dialogs.confirm_unsaved_changes"
_PM = "ProcessManager"
_POLL_MS = 20  # интервал опроса/тика в тестах; реальный по умолчанию 250
_TIMEOUT = {"success": False, "error": "timeout"}


def _procs(alive: dict[str, bool | None]) -> dict[str, Any]:
    """Успешный ответ по форме критерия C: ``{"success": True, "processes": {имя: {"alive": ..}}}``."""
    return {"success": True, "processes": {name: {"alive": v, "pid": 1} for name, v in alive.items()}}


_ALIVE = _procs({_PM: True, "worker_a": True})  # все живы (PM в ignore_names)
_DEAD = _procs({_PM: True, "worker_a": False})  # дети мертвы, PM жив (его не ждём)


# ---------------------------------------------------------------------------
# Фейки
# ---------------------------------------------------------------------------


class FakeClock:
    """Управляемые часы: тест сам двигает ``now``."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeHandle:
    """Ручка открытого вопроса: считает вызовы ``close()``."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class PollCall(NamedTuple):
    timeout: Any
    thread: int


class Env:
    """Набор внедряемых фейков + счётчики эффектов. Координатор строится из них в ``make_env``."""

    def __init__(self, window: QWidget, **ctor_overrides: Any) -> None:
        self.window = window
        self.clock = FakeClock()
        self.log: list[str] = []
        # confirm_discard
        self.confirm_calls = 0
        self.confirm_result = True
        self.confirm_raises: Exception | None = None
        self.confirm_hook: Callable[[], None] | None = None
        self.confirm_fn: Callable[[], bool] | None = None  # полная подмена (проводка на настоящее окно)
        # send_shutdown / on_shutdown_sent
        self.send_calls = 0
        self.send_raises: Exception | None = None
        self.sent_calls = 0
        # force_stop / quit_app
        self.force_calls = 0
        self.quit_calls = 0
        self.quit_threads: list[int] = []
        # ask_force_stop
        self.handles: list[FakeHandle] = []
        self.on_answers: list[Callable[[bool], None]] = []
        # poll_status (вызывается на потоке пула)
        self.poll_gate = threading.Event()
        self.poll_gate.set()  # по умолчанию не блокирует; .clear() - PM «молчит», .set() освобождает
        self.script: list[dict[str, Any]] = []  # одноразовые ответы по порядку
        self.default_response: dict[str, Any] = copy.deepcopy(_ALIVE)
        self.poll_calls: list[PollCall] = []
        self.poll_done = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

        kwargs: dict[str, Any] = dict(
            confirm_discard=self._confirm,
            send_shutdown=self._send,
            poll_status=self._poll,
            ignore_names=frozenset({_PM}),
            ask_force_stop=self._ask,
            force_stop=self._force,
            quit_app=self._quit,
            on_shutdown_sent=self._sent,
            clock=self.clock,
            poll_interval_ms=_POLL_MS,
            no_answer_s=2.0,
        )
        kwargs.update(ctor_overrides)
        self.coord = CloseCoordinator(window, **kwargs)

    # -- внедряемые вызовы --

    def _confirm(self) -> bool:
        self.confirm_calls += 1
        self.log.append("confirm")
        if self.confirm_hook is not None:
            self.confirm_hook()
        if self.confirm_raises is not None:
            raise self.confirm_raises
        if self.confirm_fn is not None:
            return self.confirm_fn()
        return self.confirm_result

    def _send(self) -> dict:
        self.send_calls += 1
        self.log.append("send")
        if self.send_raises is not None:
            raise self.send_raises
        return {"success": True}

    def _sent(self) -> None:
        self.sent_calls += 1
        self.log.append("sent")

    def _force(self) -> None:
        self.force_calls += 1
        self.log.append("force")

    def _quit(self) -> None:
        self.quit_calls += 1
        self.quit_threads.append(threading.get_ident())
        self.log.append("quit")

    def _ask(self, on_answer: Callable[[bool], None]) -> FakeHandle:
        handle = FakeHandle()
        self.handles.append(handle)
        self.on_answers.append(on_answer)
        self.log.append("ask")
        return handle

    def _poll(self, timeout: Any = None, *_a: Any, **_kw: Any) -> dict:
        with self._lock:
            self.poll_calls.append(PollCall(timeout, threading.get_ident()))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            self.poll_gate.wait(15)  # ограничено: зависший тест не вешает пул навсегда
            with self._lock:
                response = self.script.pop(0) if self.script else self.default_response
            return copy.deepcopy(response)
        finally:
            with self._lock:
                self.in_flight -= 1
                self.poll_done += 1

    # -- помощники теста --

    @property
    def ask_count(self) -> int:
        return len(self.handles)

    def answer(self, stop: bool) -> None:
        """Оператор ответил на последний вопрос: True - «Остановить», False - «Подождать»."""
        self.on_answers[-1](stop)

    def settle(self, qtbot: Any, polls: int = 3) -> None:
        """Дождаться ``polls`` завершённых опросов и доставки последнего результата в главный поток."""
        target = self.poll_done + polls
        _wait(qtbot, lambda: self.poll_done >= target, f"завершения {polls} опросов poll_status")
        qtbot.wait(60)

    def release(self) -> None:
        self.poll_gate.set()
        self.script.clear()
        self.default_response = copy.deepcopy(_TIMEOUT)


def _wait(qtbot: Any, cond: Callable[[], bool], what: str, timeout: int = 2000) -> None:
    """``qtbot.waitUntil`` с понятным провалом: красный по ПОВЕДЕНИЮ («не дождались ...»), а не по TimeoutError."""
    try:
        qtbot.waitUntil(cond, timeout=timeout)
    except QtTimeoutError:
        pytest.fail(f"не дождались: {what} (за {timeout} мс)")


@pytest.fixture
def make_env(qtbot: Any):
    """Фабрика окружения: ``make_env(window=None, **ctor_overrides) -> Env``; teardown освобождает блокирующий poll."""
    envs: list[Env] = []

    def _make(window: QWidget | None = None, **ctor_overrides: Any) -> Env:
        if window is None:
            window = QWidget()
            qtbot.addWidget(window)
        env = Env(window, **ctor_overrides)
        envs.append(env)
        return env

    yield _make
    for env in envs:
        env.release()  # блокирующий фейк обязан быть освобождён, иначе поток пула повиснет
    QThreadPool.globalInstance().waitForDone(3000)


def _main_window(qtbot: Any, tmp_path: Any) -> MainWindow:
    """Настоящее главное окно; геометрия пишется во временный ini, а не в QSettings владельца."""
    window = MainWindow()
    qtbot.addWidget(window)
    window._settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    return window


def _spy_unsaved(monkeypatch: pytest.MonkeyPatch, choice: str) -> list[dict[str, Any]]:
    """Подменить диалог «несохранённые правки»: вернуть ``choice``, записать каждый показ (в тест не лезет модалка)."""
    shown: list[dict[str, Any]] = []

    def _fake(parent: Any, *, allow_save: bool = True, text: str = "") -> str:
        shown.append({"allow_save": allow_save, "text": text})
        return choice

    monkeypatch.setattr(_DIALOG_TARGET, _fake)
    return shown


def _dirty_window(
    qtbot: Any,
    tmp_path: Any,
    request: pytest.FixtureRequest,
    make_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
) -> tuple[MainWindow, Env, TopologySession, list[dict[str, Any]]]:
    """Настоящие объекты: MainWindow + грязная TopologySession + координатор, чей confirm_discard - настоящий
    ``confirm_discard_topology_changes`` окна (как проводит composition root)."""
    window = _main_window(qtbot, tmp_path)
    session = TopologySession()
    session.mark_edited()
    assert session.dirty is True
    window.set_topology_session(session, None)
    request.addfinalizer(session.reset)  # иначе teardown qtbot закроет окно и встанет модальный диалог
    shown = _spy_unsaved(monkeypatch, choice)
    env = make_env(window)
    env.confirm_fn = lambda: window.confirm_discard_topology_changes(reason="Сохранить их перед выходом?")
    window.set_close_coordinator(env.coord)
    return window, env, session, shown


def _close_event() -> QCloseEvent:
    event = QCloseEvent()
    event.accept()
    return event


# ---------------------------------------------------------------------------
# A. Крестик в RUNNING
# ---------------------------------------------------------------------------


def test_x_on_running_ignores_event_and_sends_shutdown_once(qtbot: Any, make_env: Any, tmp_path: Any) -> None:
    """Крестик на настоящем окне: событие игнорируется, вопрос один раз, shutdown один раз, STOPPING, прогресс."""
    window = _main_window(qtbot, tmp_path)
    env = make_env(window)
    window.set_close_coordinator(env.coord)
    event = _close_event()

    window.closeEvent(event)

    assert event.isAccepted() is False, "closeEvent с координатором обязан сделать event.ignore()"
    assert env.coord.state is CloseState.STOPPING
    assert (env.confirm_calls, env.send_calls, env.sent_calls) == (1, 1, 1)
    assert env.log == ["confirm", "send", "sent"]
    assert env.quit_calls == 0
    assert len(window.findChildren(QProgressDialog)) >= 1, "должен быть показан диалог прогресса"


def test_x_on_running_ignores_event_and_sends_shutdown_once_send_failure(qtbot: Any, make_env: Any) -> None:
    """Сбой send_shutdown: приложение всё равно закрывается (quit_app, CLOSING), on_shutdown_sent НЕ вызван."""
    env = make_env()
    env.send_raises = RuntimeError("router closed")

    env.coord.request_close()  # исключение наружу не выходит

    assert env.send_calls == 1
    assert env.quit_calls == 1
    assert env.coord.state is CloseState.CLOSING
    assert env.sent_calls == 0, "on_shutdown_sent не вызывается, если shutdown не ушёл"


@pytest.mark.parametrize("mode", ["cancel", "raises"])
def test_cancel_in_save_prompt_keeps_system_running(qtbot: Any, make_env: Any, mode: str) -> None:
    """«Отмена» (False) или исключение confirm_discard: RUNNING, ничего не отправлено, опрос не начат."""
    env = make_env()
    if mode == "cancel":
        env.confirm_result = False
    else:
        env.confirm_raises = RuntimeError("dialog failed")

    env.coord.request_close()

    assert env.coord.state is CloseState.RUNNING
    assert env.confirm_calls == 1
    assert (env.send_calls, env.sent_calls, env.quit_calls, env.ask_count) == (0, 0, 0, 0)
    qtbot.wait(120)  # несколько тиков: опрос в RUNNING не идёт
    assert env.poll_calls == []
    # RUNNING настоящий: следующий крестик снова работает
    env.confirm_raises = None
    env.confirm_result = True
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING
    assert (env.send_calls, env.sent_calls) == (1, 1)


def test_safety_tick_during_confirm_prevents_send(qtbot: Any, make_env: Any) -> None:
    """Пока открыт вопрос, пришёл on_safety_tick(True): после confirm_discard send_shutdown НЕ вызывается."""
    env = make_env()
    env.confirm_hook = lambda: env.coord.on_safety_tick(True)

    env.coord.request_close()

    assert env.confirm_calls == 1
    assert env.coord.state is CloseState.CLOSING
    assert env.quit_calls == 1
    assert (env.send_calls, env.sent_calls, env.ask_count) == (0, 0, 0)


# ---------------------------------------------------------------------------
# B. Повторный крестик вне RUNNING
# ---------------------------------------------------------------------------


def test_second_x_in_stopping_is_ignored_without_resend(qtbot: Any, make_env: Any, tmp_path: Any) -> None:
    window = _main_window(qtbot, tmp_path)
    env = make_env(window)
    window.set_close_coordinator(env.coord)
    first = _close_event()
    window.closeEvent(first)
    assert env.coord.state is CloseState.STOPPING

    second = _close_event()
    third = _close_event()
    window.closeEvent(second)
    window.closeEvent(third)
    env.coord.request_close()

    assert second.isAccepted() is False and third.isAccepted() is False
    assert env.coord.state is CloseState.STOPPING
    assert env.confirm_calls == 1, "второго вопроса быть не должно"
    assert (env.send_calls, env.sent_calls) == (1, 1), "повторной отправки shutdown быть не должно"
    assert env.quit_calls == 0


@pytest.mark.parametrize("state", ["confirming", "closing"])
def test_x_outside_running_is_ignored(qtbot: Any, make_env: Any, state: str) -> None:
    """request_close() в CONFIRMING (вложенный крестик во время вопроса) и в CLOSING ничего не делает."""
    env = make_env()
    if state == "confirming":
        env.confirm_hook = lambda: env.coord.request_close()  # крестик, пока вопрос открыт
        env.coord.request_close()
        assert env.confirm_calls == 1, "вложенный крестик не задаёт второй вопрос"
        assert env.send_calls == 1, "и не отправляет shutdown второй раз"
    else:
        env.coord.backend_gone()
        assert env.coord.state is CloseState.CLOSING
        env.coord.request_close()
        assert env.confirm_calls == 0
        assert env.send_calls == 0
        assert env.quit_calls == 1


# ---------------------------------------------------------------------------
# C. Опрос и «все процессы остановлены»
# ---------------------------------------------------------------------------


def test_quit_app_called_only_after_all_children_dead(qtbot: Any, make_env: Any) -> None:
    env = make_env()
    env.default_response = _procs({_PM: True, "worker_a": True, "worker_b": True})
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING

    env.settle(qtbot, 3)
    assert env.quit_calls == 0, "все дети живы - выходить рано"

    env.default_response = _procs({_PM: True, "worker_a": False, "worker_b": True})
    env.settle(qtbot, 3)
    assert env.quit_calls == 0, "один ребёнок мёртв, другой жив - ждать (any вместо all недопустим)"
    assert env.coord.state is CloseState.STOPPING

    # worker_b: alive None - не ждём; PM жив, но лежит в ignore_names - не ждём
    env.default_response = _procs({_PM: True, "worker_a": False, "worker_b": None})
    _wait(qtbot, lambda: env.quit_calls == 1, "quit_app после остановки всех детей")
    assert env.coord.state is CloseState.CLOSING
    qtbot.wait(100)
    assert env.quit_calls == 1, "quit_app ровно один раз"


@pytest.mark.parametrize(
    "response",
    [
        {"success": True, "processes": {}},
        {"success": True},
        {"processes": {"worker_a": {"alive": False}}},
        {"success": False, "error": "timeout", "processes": {"worker_a": {"alive": False}}},
    ],
    ids=["empty_processes", "no_processes_key", "no_success_key", "success_false"],
)
def test_empty_or_unsuccessful_response_is_not_all_dead(qtbot: Any, make_env: Any, response: dict) -> None:
    """Пустой processes / ответ без success / success False не засчитываются как «все мертвы»."""
    env = make_env()
    env.default_response = response
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING

    env.settle(qtbot, 4)

    assert env.quit_calls == 0
    assert env.coord.state is CloseState.STOPPING


# ---------------------------------------------------------------------------
# F. backend_gone / safety-тик; E. closeEvent в CLOSING (настоящие объекты)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", ["backend_gone", "safety_tick_true"])
def test_backend_gone_never_prompts(
    qtbot: Any,
    make_env: Any,
    tmp_path: Any,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    trigger: str,
) -> None:
    """Бэкенд пропал при грязной сессии: сразу CLOSING и quit_app, ни одного вопроса; окно закрывается без диалога."""
    window, env, session, shown = _dirty_window(qtbot, tmp_path, request, make_env, monkeypatch, "cancel")

    if trigger == "backend_gone":
        env.coord.backend_gone()
    else:
        env.coord.on_safety_tick(True)

    assert env.coord.state is CloseState.CLOSING
    assert env.quit_calls == 1
    assert env.confirm_calls == 0
    assert (env.send_calls, env.ask_count) == (0, 0)
    event = _close_event()
    window.closeEvent(event)  # quit_app закрывает окно: closeEvent в CLOSING
    assert event.isAccepted() is True
    assert shown == [], "confirm_unsaved_changes не должен вызываться, когда бэкенда уже нет"


def test_safety_tick_false_never_commits(qtbot: Any, make_env: Any) -> None:
    env = make_env()
    env.coord.on_safety_tick(False)
    assert env.coord.state is CloseState.RUNNING
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING
    env.coord.on_safety_tick(False)
    qtbot.wait(100)
    assert env.coord.state is CloseState.STOPPING
    assert env.quit_calls == 0


def test_safety_tick_true_in_stopping_does_not_interrupt_wait(qtbot: Any, make_env: Any) -> None:
    env = make_env()
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING

    env.coord.on_safety_tick(True)
    qtbot.wait(100)

    assert env.coord.state is CloseState.STOPPING, "в STOPPING safety-тик ожидание не прерывает"
    assert env.quit_calls == 0
    assert (env.confirm_calls, env.ask_count) == (1, 0)
    # ожидание живо: дети умерли - выходим как обычно
    env.default_response = _DEAD
    _wait(qtbot, lambda: env.quit_calls == 1, "quit_app после остановки детей")


def test_close_event_in_closing_does_not_ask_again(
    qtbot: Any, make_env: Any, tmp_path: Any, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Один вопрос за закрытие: «Не сохранять» -> STOPPING -> дети умерли -> CLOSING -> closeEvent без вопроса."""
    window, env, session, shown = _dirty_window(qtbot, tmp_path, request, make_env, monkeypatch, "discard")
    env.default_response = _DEAD

    first = _close_event()
    window.closeEvent(first)  # крестик: игнор + вопрос «Не сохранять»
    assert first.isAccepted() is False
    assert len(shown) == 1
    _wait(qtbot, lambda: env.coord.state is CloseState.CLOSING, "переход в CLOSING")
    assert env.quit_calls == 1

    second = _close_event()
    window.closeEvent(second)  # закрытие после quit_app

    assert second.isAccepted() is True, "в CLOSING окно закрывается"
    assert len(shown) == 1, "второго вопроса о несохранённых правках быть не должно"
    assert session.dirty is True, "«Не сохранять» не снимает dirty"
    assert window._settings.contains("mainwindow/geometry"), "геометрия сохраняется при закрытии"


# ---------------------------------------------------------------------------
# C/D. Опрос и сторож тишины (фейковые часы)
# ---------------------------------------------------------------------------


def _stop_started(env: Env) -> float:
    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING
    return env.clock.now  # t_send


def _case_no_answer_asks_operator_then_sets_event(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()  # PM молчит: ни одного результата, сторож работает по тикам
    t_send = _stop_started(env)
    env.clock.now = t_send + 1.99
    qtbot.wait(150)
    assert env.ask_count == 0, "тишина 1.99 с < 2.0 с: вопроса ещё нет"
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.ask_count == 1, "ask_force_stop после 2.0 с тишины")
    assert env.force_calls == 0, "пока оператор не ответил, force не вызывается"
    qtbot.wait(150)
    assert env.ask_count == 1, "пока вопрос открыт, повторно не спрашиваем"
    env.answer(True)
    assert env.force_calls == 1
    assert env.coord.state is CloseState.STOPPING
    qtbot.wait(150)
    assert env.quit_calls == 0, "после «Остановить» ожидание детей продолжается"


def _case_wait_resets_2s(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()
    t_send = _stop_started(env)
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.ask_count == 1, "первый вопрос")
    env.answer(False)  # «Подождать»: t_wait_click = clock()
    t_wait = env.clock.now
    qtbot.wait(150)
    assert env.ask_count == 1, "сразу после «Подождать» вопрос не повторяется (тишина считается от клика)"
    env.clock.now = t_wait + 1.99
    qtbot.wait(150)
    assert env.ask_count == 1
    env.clock.now = t_wait + 2.0
    _wait(qtbot, lambda: env.ask_count == 2, "второй вопрос через 2.0 с после «Подождать»")
    assert env.force_calls == 0
    assert env.quit_calls == 0


def _case_answer_while_question_open(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()
    env.script = [copy.deepcopy(_ALIVE)]  # первый освобождённый опрос вернёт успех, дальше - таймауты
    env.default_response = copy.deepcopy(_TIMEOUT)
    t_send = _stop_started(env)
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.ask_count == 1, "вопрос")
    handle = env.handles[0]
    assert handle.close_calls == 0
    env.poll_gate.set()  # блокированный опрос возвращает успешный ответ
    _wait(qtbot, lambda: handle.close_calls == 1, "закрытие ручки вопроса при успешном ответе")
    qtbot.wait(150)
    assert handle.close_calls == 1
    assert env.ask_count == 1 and env.force_calls == 0, "это «Подождать»: ни force, ни нового вопроса сразу"
    t_ok = env.clock.now  # часы не двигались: успех пришёл в этот момент
    env.clock.now = t_ok + 1.99
    qtbot.wait(150)
    assert env.ask_count == 1, "тишина считается от успешного ответа, а не от отправки"
    env.clock.now = t_ok + 2.0
    _wait(qtbot, lambda: env.ask_count == 2, "новый вопрос после следующей тишины 2.0 с")


def _case_timeout_is_not_an_answer(env: Env, qtbot: Any) -> None:
    env.default_response = copy.deepcopy(_TIMEOUT)  # результаты приходят, но это таймауты
    t_send = _stop_started(env)
    env.clock.now = t_send + 1.99
    env.settle(qtbot, 3)
    assert env.ask_count == 0
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.ask_count == 1, "вопрос: таймаут не считается ответом")
    assert env.quit_calls == 0


def _case_one_request_in_flight(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()
    _stop_started(env)
    _wait(qtbot, lambda: len(env.poll_calls) >= 1, "первый вызов poll_status")
    qtbot.wait(10 * _POLL_MS + 100)  # много интервалов при непришедшем ответе
    assert len(env.poll_calls) == 1, "пока запрос в полёте, новый не посылается"
    assert env.max_in_flight == 1
    env.poll_gate.set()
    _wait(qtbot, lambda: len(env.poll_calls) >= 3, "опрос продолжается после ответа")
    assert env.max_in_flight == 1, "одновременно в полёте не более одного запроса"


def _case_poll_off_main_thread_result_on_main(env: Env, qtbot: Any) -> None:
    env.default_response = copy.deepcopy(_DEAD)
    _stop_started(env)
    _wait(qtbot, lambda: env.quit_calls == 1, "quit_app по результату опроса")
    main = threading.get_ident()
    assert len(env.poll_calls) >= 1
    assert all(call.thread != main for call in env.poll_calls), "poll_status звать вне главного потока"
    assert env.poll_calls[0].timeout == 1.0
    assert env.quit_threads == [main], "результат опроса обрабатывается в главном потоке"


def _case_unattended_sets_event_without_question(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()
    t_send = _stop_started(env)
    env.clock.now = t_send + 1.99
    qtbot.wait(150)
    assert env.force_calls == 0
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.force_calls == 1, "force_stop без вопроса при unattended")
    qtbot.wait(150)
    assert env.force_calls == 1, "force_stop один раз"
    assert env.ask_count == 0, "при unattended вопроса нет"
    assert env.quit_calls == 0


def _case_dead_pm_tail_commits_after_force(env: Env, qtbot: Any) -> None:
    env.poll_gate.clear()  # PM мёртв: ответов нет
    t_send = _stop_started(env)
    env.clock.now = t_send + 2.0
    _wait(qtbot, lambda: env.ask_count == 1, "вопрос")
    env.answer(True)
    assert env.force_calls == 1
    t_force = env.clock.now
    env.clock.now = t_force + 1.99
    qtbot.wait(150)
    assert env.quit_calls == 0 and env.coord.state is CloseState.STOPPING
    env.clock.now = t_force + 2.0
    _wait(qtbot, lambda: env.quit_calls == 1, "commit_close: хвост 2.0 с после force без ответов")
    assert env.coord.state is CloseState.CLOSING
    assert env.ask_count == 1, "после force вопрос больше не задаётся"
    assert env.force_calls == 1


# имя случая -> (kwargs конструктора, тело)
_CASES: dict[str, tuple[dict[str, Any], Callable[[Env, Any], None]]] = {
    "no_answer_asks_operator_then_sets_event": ({}, _case_no_answer_asks_operator_then_sets_event),
    "wait_resets_2s": ({}, _case_wait_resets_2s),
    "answer_while_question_open": ({}, _case_answer_while_question_open),
    "timeout_is_not_an_answer": ({}, _case_timeout_is_not_an_answer),
    "one_request_in_flight": ({}, _case_one_request_in_flight),
    "poll_off_main_thread_result_on_main": ({}, _case_poll_off_main_thread_result_on_main),
    "unattended_sets_event_without_question": ({"unattended": True}, _case_unattended_sets_event_without_question),
    "dead_pm_tail_commits_after_force": ({}, _case_dead_pm_tail_commits_after_force),
}


@pytest.mark.parametrize("case", list(_CASES))
def test_polling_and_force_flow(qtbot: Any, make_env: Any, case: str) -> None:
    ctor_kwargs, body = _CASES[case]
    env = make_env(**ctor_kwargs)
    body(env, qtbot)


# ---------------------------------------------------------------------------
# G. Рестарт UI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["confirmed", "declined", "not_running"])
def test_ui_restart_quits_without_shutdown(qtbot: Any, make_env: Any, case: str) -> None:
    env = make_env()
    if case == "not_running":
        env.coord.request_close()
        assert env.coord.state is CloseState.STOPPING
        env.confirm_calls = 0
        env.send_calls = 0
        env.sent_calls = 0
    if case == "declined":
        env.confirm_result = False

    env.coord.request_restart()

    if case == "confirmed":
        assert env.confirm_calls == 1
        assert env.quit_calls == 1, "рестарт UI = выход из Qt-цикла"
        assert env.send_calls == 0, "рестарт UI не гасит систему"
        assert env.sent_calls == 0
    elif case == "declined":
        assert env.confirm_calls == 1
        assert (env.quit_calls, env.send_calls, env.sent_calls) == (0, 0, 0)
        assert env.coord.state is CloseState.RUNNING
    else:
        assert env.confirm_calls == 0, "вне RUNNING рестарт ничего не делает"
        assert (env.quit_calls, env.send_calls, env.sent_calls) == (0, 0, 0)
        assert env.coord.state is CloseState.STOPPING


# ---------------------------------------------------------------------------
# H. Диалог прогресса
# ---------------------------------------------------------------------------


def test_progress_dialog_has_no_cancel_and_ignores_escape(qtbot: Any, make_env: Any) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    env = make_env(window)

    env.coord.request_close()
    assert env.coord.state is CloseState.STOPPING

    dialogs = window.findChildren(QProgressDialog)
    assert len(dialogs) >= 1, "после запуска остановки у окна есть QProgressDialog"
    dialog = dialogs[0]
    _wait(qtbot, dialog.isVisible, "показ диалога прогресса")
    assert "Остановка системы" in (dialog.windowTitle() + " " + dialog.labelText())
    assert dialog.findChildren(QPushButton) == [], "кнопки отмены нет"

    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    qtbot.wait(100)

    assert dialog.isVisible() is True, "Esc не закрывает диалог остановки"
    assert env.coord.state is CloseState.STOPPING
