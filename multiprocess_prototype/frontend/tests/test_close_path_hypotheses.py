"""H1 гипотезы gui-graceful-close (task 0.1): что Qt делает при closeEvent с event.ignore() и app.quit().

Тесты фиксируют поведение Qt как есть. Ответ — литерал в assert; «зелёный» здесь значит «ответ записан»,
а не «гипотеза подтверждена». Дедлайн 2,0 с — отдельный QTimer (тест в daemon-потоке нельзя: Qt на главном).
"""

import time

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.windows.main_window import MainWindow

DEADLINE_MS = 2000


class _CountingWindow(QMainWindow):
    """Окно, чей closeEvent считает вызовы и отменяет закрытие."""

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt-имя
        self.close_calls += 1
        event.ignore()


def _run_exec_with_deadline(app: QApplication) -> dict:
    """app.exec() + QApplication.quit() из singleShot(0); дедлайн 2,0 с вторым таймером."""
    result = {"deadline_fired": False, "exec_seconds": None}

    def _deadline() -> None:
        result["deadline_fired"] = True
        QCoreApplication.exit(0)

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(_deadline)
    deadline.start(DEADLINE_MS)
    QTimer.singleShot(0, app.quit)

    t0 = time.monotonic()
    app.exec()
    result["exec_seconds"] = time.monotonic() - t0
    deadline.stop()
    return result


def test_h1a_close_ignored_then_app_quit_closeevent_count(qapp):
    """H1a: closeEvent вызван при app.quit(); exec() не возвращается при ignore() — измерено."""
    win = _CountingWindow()
    win.show()

    outcome = _run_exec_with_deadline(qapp)
    print(
        f"\nH1a close_calls={win.close_calls} deadline_fired={outcome['deadline_fired']} "
        f"exec_seconds={outcome['exec_seconds']:.3f}"
    )
    win.hide()
    win.deleteLater()

    # Литералы — ответ, записан после прогона (см. отчёт smoke-h1h2, раздел «Замеры»).
    # Замер 2026-11-02, PySide6 6.10.3: closeEvent 1 раз; exec() не вернулся, сработал дедлайн 2,000 с.
    assert win.close_calls == 1
    assert outcome["deadline_fired"] is True


def test_h1b_real_mainwindow_dirty_session_confirm_called_after_quit(qapp, monkeypatch):
    """H1b: настоящий MainWindow с dirty TopologySession — confirm_unsaved_changes вызван после app.quit()."""
    import multiprocess_prototype.frontend.widgets.dialogs as dialogs

    calls: list[tuple] = []

    def _fake_confirm(*args, **kwargs):
        calls.append((args, kwargs))
        return "cancel"  # «Отмена» → окно не закрывается, как при реальном выборе пользователя

    monkeypatch.setattr(dialogs, "confirm_unsaved_changes", _fake_confirm)

    win = MainWindow()
    session = TopologySession()
    session.mark_edited()
    win.set_topology_session(session, save_fn=None)
    win.show()

    outcome = _run_exec_with_deadline(qapp)
    print(
        f"\nH1b confirm_calls={len(calls)} deadline_fired={outcome['deadline_fired']} "
        f"exec_seconds={outcome['exec_seconds']:.3f}"
    )
    win.hide()
    win.deleteLater()

    # Замер 2026-11-02, PySide6 6.10.3: confirm_unsaved_changes 1 раз; exec() не вернулся, дедлайн 2,000 с.
    assert len(calls) == 1
    assert outcome["deadline_fired"] is True
