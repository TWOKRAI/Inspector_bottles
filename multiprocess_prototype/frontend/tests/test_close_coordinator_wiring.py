# -*- coding: utf-8 -*-
"""Авторские тесты проводки CloseCoordinator в composition root (Task 1.1, раунд 3).

Настоящие объекты: ``app._build_close_coordinator`` + настоящий ``MainWindow``. Фейки — только IPC
(``command_sender``, ``process_manager_proxy``), процесс и ``app`` (``quit`` — счётчик, без выхода из цикла).

* Конверт ответа ``supervision.status``: ``CommandSender.request_system_command`` отдаёт его как есть
  (полезная нагрузка PM — в ``result``). Форма снята вживую ревьюером (scratchpad ``probe_envelope.py``):
  верхние ключи command, queue_type, request_id, result, sender, success, targets, type; в ``result`` —
  epoch, processes, success.
* Крестик, который сразу приводит в ``CLOSING`` (сбой ``send_shutdown``; бэкенд ушёл во время вопроса):
  ``quit_app`` зовёт ``window.close()`` внутри ``closeEvent`` — окно всё равно должно закрыться.
* ``ignore_names``: ``gui`` (своё имя) и ``ProcessManager`` (PM отдаёт о себе ``alive: True``) не ждём.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSettings, QThreadPool

from multiprocess_prototype.frontend import app as gui_app
from multiprocess_prototype.frontend.shutdown import CloseState
from multiprocess_prototype.frontend.windows.main_window import MainWindow


def _envelope(processes: dict[str, Any], *, outer: bool = True, inner: bool = True) -> dict[str, Any]:
    """Конверт ответа PM в форме, снятой вживую."""
    return {
        "type": "response",
        "command": "process.command.response",
        "sender": "ProcessManager",
        "targets": ["gui"],
        "queue_type": "system",
        "request_id": "req-1",
        "success": outer,
        "result": {"success": inner, "epoch": 1, "processes": processes},
    }


_LIVE_DEAD = {  # живая форма: дети console_sink и ticker вышли, PM жив
    "ProcessManager": {"alive": True, "pid": 101},
    "console_sink": {"alive": False, "pid": None},
    "ticker": {"alive": False, "pid": None},
}


class _Rig:
    """Настоящие окно и координатор; фейковые процесс, IPC и ``app``."""

    def __init__(self, qtbot: Any, tmp_path: Any, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.process = MagicMock()
        self.process.name = "gui"
        self.process.shutdown_sent = False
        self.process._restart_ui = False
        self.process._get_system_stop_event.return_value = None
        self.sender = MagicMock()
        self.sender.request_system_command.side_effect = lambda *_a, **_kw: copy.deepcopy(self.reply)
        self.proxy = MagicMock()
        self.app = MagicMock()  # app.quit — счётчик
        self.window = MainWindow()
        qtbot.addWidget(self.window)
        self.window._settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
        self.window.show()
        qtbot.waitExposed(self.window)
        self.coord = gui_app._build_close_coordinator(self.app, self.process, self.window, self.sender, self.proxy)
        self.window.set_close_coordinator(self.coord)


@pytest.fixture
def rig(qtbot: Any, tmp_path: Any):
    made: list[_Rig] = []

    def _make(reply: dict[str, Any]) -> _Rig:
        r = _Rig(qtbot, tmp_path, reply)
        made.append(r)
        return r

    yield _make
    for r in made:
        r.coord.commit_close()  # teardown: окно закрывается в CLOSING без вопроса
    QThreadPool.globalInstance().waitForDone(3000)


def _wait(qtbot: Any, cond: Any, timeout: int = 2000) -> None:
    qtbot.waitUntil(cond, timeout=timeout)


# ---------------------------------------------------------------------------
# П. 1: конверт ответа supervision.status
# ---------------------------------------------------------------------------


def test_live_envelope_children_dead_quits_once(qtbot: Any, rig: Any) -> None:
    """Живой конверт, дети мертвы, PM жив → крестик закрывает окно, app.quit ровно один раз."""
    r = rig(_envelope(copy.deepcopy(_LIVE_DEAD)))

    r.window.close()  # крестик
    assert r.coord.state is CloseState.STOPPING
    _wait(qtbot, lambda: r.app.quit.call_count == 1)
    qtbot.wait(100)

    assert r.app.quit.call_count == 1
    assert r.coord.state is CloseState.CLOSING
    assert r.window.isVisible() is False
    assert r.proxy.shutdown_system.call_count == 1
    assert r.process.shutdown_sent is True
    assert r.sender.request_system_command.call_args.args[0] == {"cmd": "supervision.status"}


@pytest.mark.parametrize("which", ["inner_success_false", "outer_success_false"])
def test_envelope_without_success_is_not_all_dead(qtbot: Any, rig: Any, which: str) -> None:
    """Контроль: внутренний success False или внешний success False не засчитываются как «все мертвы»."""
    reply = _envelope(
        copy.deepcopy(_LIVE_DEAD), inner=(which != "inner_success_false"), outer=(which != "outer_success_false")
    )
    r = rig(reply)

    r.window.close()
    _wait(qtbot, lambda: r.sender.request_system_command.call_count >= 4)
    qtbot.wait(60)

    assert r.app.quit.call_count == 0
    assert r.coord.state is CloseState.STOPPING
    assert r.window.isVisible() is True


def test_ignore_names_are_own_name_and_process_manager(qtbot: Any, rig: Any) -> None:
    """П. 3: в ответе живы только gui и ProcessManager → их не ждём, окно закрывается."""
    processes = {
        "gui": {"alive": True, "pid": 7},
        "ProcessManager": {"alive": True, "pid": 101},
        "worker": {"alive": False, "pid": None},
    }
    r = rig(_envelope(processes))

    r.window.close()
    _wait(qtbot, lambda: r.app.quit.call_count == 1)

    assert r.coord.state is CloseState.CLOSING
    assert r.window.isVisible() is False


# ---------------------------------------------------------------------------
# П. 2: крестик сразу приводит в CLOSING — окно закрывается тем же closeEvent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["send_shutdown_fails", "backend_gone_during_confirm"])
def test_x_that_commits_at_once_hides_window(qtbot: Any, rig: Any, path: str) -> None:
    r = rig(_envelope(copy.deepcopy(_LIVE_DEAD)))
    if path == "send_shutdown_fails":
        r.proxy.shutdown_system.side_effect = RuntimeError("router closed")
    else:

        def _confirm_with_safety_tick(**_kw: Any) -> bool:
            r.coord.on_safety_tick(True)  # бэкенд ушёл, пока открыт вопрос
            return True

        r.window.confirm_discard_topology_changes = _confirm_with_safety_tick

    r.window.close()  # крестик: quit_app зовёт window.close() внутри closeEvent

    assert r.coord.state is CloseState.CLOSING
    assert r.app.quit.call_count == 1
    assert r.window.isVisible() is False, "окно должно закрыться тем же крестиком"
    assert r.window._settings.contains("mainwindow/geometry")
