# -*- coding: utf-8 -*-
"""Авторские hazard-тесты CloseCoordinator (Task 1.1, раунд 2): модальность прогресса и сторож модалок.

Режим без присмотра (``INSPECTOR_GUI_UNATTENDED=1``) ставит сторож ``unattended.install_modal_watchdog``:
каждые ``interval_ms`` он берёт ``QApplication.activeModalWidget()`` и зовёт ``reject()``. Окно-модальный
прогресс остановки попадал бы под него на каждом тике ожидания (WARNING «modal_closed» в журнал gui).
Поэтому без присмотра прогресс немодальный, а с оператором — окно-модальный.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from multiprocess_prototype.frontend import unattended
from multiprocess_prototype.frontend.shutdown.close_coordinator import CloseCoordinator, CloseState

_TIMEOUT = {"success": False, "error": "timeout"}  # PM молчит: опросы приходят, ответа нет


class _Fx:
    """Фейковые эффекты координатора + управляемые часы."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.ask_calls = 0
        self.force_calls = 0
        self.quit_calls = 0

    def clock(self) -> float:
        return self.now

    def ask(self, _on_answer: Any) -> Any:
        self.ask_calls += 1

        class _Handle:
            def close(self) -> None:
                pass

        return _Handle()

    def force(self) -> None:
        self.force_calls += 1

    def quit(self) -> None:
        self.quit_calls += 1


@pytest.fixture
def make_coord(qtbot: Any):
    made: list[CloseCoordinator] = []

    def _make(
        *, unattended_mode: bool, response: dict[str, Any] | None = None
    ) -> tuple[CloseCoordinator, _Fx, QWidget]:
        window = QWidget()
        qtbot.addWidget(window)
        window.show()
        fx = _Fx()
        reply = copy.deepcopy(response if response is not None else _TIMEOUT)
        coord = CloseCoordinator(
            window,
            confirm_discard=lambda: True,
            send_shutdown=lambda: {"success": True},
            poll_status=lambda _timeout: copy.deepcopy(reply),
            ignore_names=frozenset({"gui", "ProcessManager"}),
            ask_force_stop=fx.ask,
            force_stop=fx.force,
            quit_app=fx.quit,
            on_shutdown_sent=lambda: None,
            unattended=unattended_mode,
            clock=fx.clock,
            poll_interval_ms=20,
            no_answer_s=2.0,
        )
        made.append(coord)
        return coord, fx, window

    yield _make
    for coord in made:
        coord.commit_close()  # закрыть прогресс; таймер опроса стоп
    QThreadPool.globalInstance().waitForDone(3000)


def _progress(qtbot: Any, window: QWidget) -> QProgressDialog:
    dialogs = window.findChildren(QProgressDialog)
    assert len(dialogs) == 1
    qtbot.waitUntil(dialogs[0].isVisible, timeout=2000)
    return dialogs[0]


def test_unattended_progress_is_not_active_modal(qtbot: Any, make_coord: Any) -> None:
    """(1) Без присмотра: диалог виден, STOPPING, но activeModalWidget() — None."""
    coord, _fx, window = make_coord(unattended_mode=True)
    coord.request_close()
    dialog = _progress(qtbot, window)
    qtbot.wait(60)

    assert coord.state is CloseState.STOPPING
    assert dialog.isVisible() is True
    assert QApplication.activeModalWidget() is None
    assert dialog.windowModality() == Qt.WindowModality.NonModal


def test_attended_progress_is_window_modal(qtbot: Any, make_coord: Any) -> None:
    """(2) С оператором: диалог окно-модальный (страж: правка (1) не стала безусловной)."""
    coord, _fx, window = make_coord(unattended_mode=False)
    coord.request_close()
    dialog = _progress(qtbot, window)

    assert coord.state is CloseState.STOPPING
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    assert QApplication.activeModalWidget() is dialog


def test_real_unattended_watchdog_never_hits_progress(
    qtbot: Any, make_coord: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(3) Настоящий сторож модалок без присмотра: за 600+ мс ожидания ни одной записи modal_closed;
    вопрос о принудительной остановке не открывается, force — без вопроса."""
    logged: list[str] = []
    monkeypatch.setattr(unattended, "_UNATTENDED", True)
    monkeypatch.setattr(unattended, "_answers", [])
    monkeypatch.setattr(unattended, "_log", lambda msg, **_kw: logged.append(msg))
    timer = unattended.install_modal_watchdog(QApplication.instance(), interval_ms=50)
    assert timer is not None
    try:
        coord, fx, window = make_coord(unattended_mode=True)
        coord.request_close()
        dialog = _progress(qtbot, window)
        qtbot.wait(650)  # >= 13 тиков сторожа

        assert [m for m in logged if "unattended.modal_closed" in m] == []
        assert unattended.auto_answers() == ()
        assert dialog.isVisible() is True
        assert coord.state is CloseState.STOPPING

        fx.now += 2.0  # тишина no_answer_s: без присмотра — force, вопроса нет
        qtbot.waitUntil(lambda: fx.force_calls == 1, timeout=2000)
        qtbot.wait(150)
        assert fx.ask_calls == 0
        assert fx.force_calls == 1
        assert [m for m in logged if "unattended.modal_closed" in m] == []
    finally:
        timer.stop()
        timer.deleteLater()


def test_progress_hidden_after_commit_close_from_stopping(qtbot: Any, make_coord: Any) -> None:
    """(4) commit_close из STOPPING прячет прогресс: после закрытия на экране не остаётся диалога."""
    coord, fx, window = make_coord(unattended_mode=False)
    coord.request_close()
    dialog = _progress(qtbot, window)
    assert coord.state is CloseState.STOPPING

    coord.commit_close()

    assert coord.state is CloseState.CLOSING
    assert fx.quit_calls == 1
    assert dialog.isVisible() is False
    qtbot.wait(50)
    assert [d for d in window.findChildren(QProgressDialog) if d.isVisible()] == []


def test_progress_shows_k_of_n_children(qtbot: Any, make_coord: Any) -> None:
    """(5) «k из N»: 3 ребёнка вне ignore_names, 1 остановлен → «1 из 3» (gui и PM не считаются)."""
    response = {
        "success": True,
        "processes": {
            "gui": {"alive": True},
            "ProcessManager": {"alive": True},
            "worker_a": {"alive": False},
            "worker_b": {"alive": True},
            "worker_c": {"alive": True},
        },
    }
    coord, _fx, window = make_coord(unattended_mode=False, response=response)
    coord.request_close()
    dialog = _progress(qtbot, window)

    qtbot.waitUntil(lambda: " из " in dialog.labelText(), timeout=2000)

    assert dialog.labelText() == "Остановка системы… 1 из 3"
    assert coord.state is CloseState.STOPPING
