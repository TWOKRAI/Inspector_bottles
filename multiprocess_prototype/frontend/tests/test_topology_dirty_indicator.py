# -*- coding: utf-8 -*-
"""RS-4 qt-тесты: индикатор «граф ≠ живая система» + проводка сессии + closeEvent.

Проверяет полный контур composition root (как в app.py):
  * EventBus TopologyReplaced → session.mark_edited (dirty+diverged);
  * EventBus RecipeActivated → session.mark_activated (снимает оба);
  * session.add_change_callback → MainWindow.set_topology_indicators;
  * MainWindow.closeEvent при dirty → подтверждение (Cancel не закрывает).

Ключевая приёмка (C-3): undo после apply → индикатор расхождения виден; после
повторного apply — снят.

Refs: plans/2026-07-06_constructor-master/plan.md (RS-4),
      docs/audits/2026-07-12_recipe-lifecycle-audit.md (C-3/C-5)
"""

from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import RecipeActivated, TopologyReplaced
from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.windows.main_window import MainWindow


def _wire(window: MainWindow, bus: EventBus, session: TopologySession, save_fn=None) -> None:
    """Повторить проводку app.py: EventBus → session → индикаторы окна."""
    bus.subscribe(TopologyReplaced, lambda _e: session.mark_edited())
    bus.subscribe(RecipeActivated, lambda _e: session.mark_activated())
    window.set_topology_session(session, save_fn)
    session.add_change_callback(lambda: window.set_topology_indicators(session.dirty, session.diverged))


# ---------------------------------------------------------------------------
# Индикатор diverged: undo после apply → виден; после повторного apply — снят
# ---------------------------------------------------------------------------


def test_diverged_indicator_after_undo_then_cleared_by_apply(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    bus = EventBus()
    session = TopologySession()
    _wire(window, bus, session)

    # Правка графа (dispatch публикует TopologyReplaced) → оба индикатора видны.
    # isHidden() (а не isVisible()) — устойчиво к непоказанному окну в headless-тесте:
    # setVisible(False) → isHidden()==True; setVisible(True) → isHidden()==False.
    bus.publish(TopologyReplaced(reason="topology_changed"))
    assert window._topo_dirty_label.isHidden() is False
    assert window._topo_diverged_label.isHidden() is False
    assert "живая система" in window._topo_diverged_label.text()

    # Apply (граф → живая система) снимает расхождение; dirty держится (в файл не писали).
    session.mark_applied()
    assert window._topo_diverged_label.isHidden() is True
    assert window._topo_dirty_label.isHidden() is False

    # Undo/правка ПОСЛЕ apply → редактор снова разошёлся с живой системой.
    bus.publish(TopologyReplaced(reason="topology_changed"))
    assert window._topo_diverged_label.isHidden() is False

    # Повторный apply — индикатор расхождения снят.
    session.mark_applied()
    assert window._topo_diverged_label.isHidden() is True


def test_recipe_activated_clears_both_indicators(qtbot) -> None:
    """Активация рецепта (RecipeActivated после TopologyReplaced) оставляет сессию чистой."""
    window = MainWindow()
    qtbot.addWidget(window)
    bus = EventBus()
    session = TopologySession()
    _wire(window, bus, session)

    # Имитация порядка событий активации в domain: TopologyReplaced, затем RecipeActivated.
    bus.publish(TopologyReplaced(reason="recipe:cup"))
    bus.publish(RecipeActivated(slug="cup"))

    assert session.dirty is False
    assert session.diverged is False
    assert window._topo_dirty_label.isHidden() is True
    assert window._topo_diverged_label.isHidden() is True


def test_indicators_hidden_initially(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window._topo_dirty_label.isHidden() is True
    assert window._topo_diverged_label.isHidden() is True


# ---------------------------------------------------------------------------
# closeEvent: подтверждение при dirty
# ---------------------------------------------------------------------------


def test_close_with_dirty_cancel_ignores_event(qtbot, monkeypatch) -> None:
    """dirty + «Отмена» в диалоге закрытия → окно НЕ закрывается (event.ignore())."""
    window = MainWindow()
    qtbot.addWidget(window)
    session = TopologySession()
    session.mark_edited()
    window.set_topology_session(session, None)

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)

    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert event.isAccepted() is False, "Cancel должен отменить закрытие"


def test_close_with_dirty_discard_accepts_event(qtbot, monkeypatch) -> None:
    """dirty + «Не сохранять» → окно закрывается (правки отброшены)."""
    window = MainWindow()
    qtbot.addWidget(window)
    session = TopologySession()
    session.mark_edited()
    window.set_topology_session(session, None)

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Discard)

    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert event.isAccepted() is True


def test_close_with_dirty_save_invokes_save_fn(qtbot, monkeypatch) -> None:
    """dirty + «Сохранить» → вызывается save_fn; при успехе окно закрывается."""
    window = MainWindow()
    qtbot.addWidget(window)
    session = TopologySession()
    session.mark_edited()
    calls: list[bool] = []

    def _save() -> bool:
        calls.append(True)
        return True

    window.set_topology_session(session, _save)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Save)

    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert calls == [True]
    assert event.isAccepted() is True


def test_close_with_dirty_save_failure_keeps_window(qtbot, monkeypatch) -> None:
    """dirty + «Сохранить», но save_fn упал (валидация) → окно НЕ закрывается, ошибка показана."""
    window = MainWindow()
    qtbot.addWidget(window)
    session = TopologySession()
    session.mark_edited()

    def _save_fail() -> bool:
        raise RuntimeError("дубли имён процессов")

    window.set_topology_session(session, _save_fail)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Save)
    crit: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: crit.append(a[2] if len(a) > 2 else ""))

    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert event.isAccepted() is False, "провал сохранения не должен закрывать окно"
    assert crit, "ошибка сохранения должна быть показана"


def test_close_when_clean_no_dialog(qtbot, monkeypatch) -> None:
    """Без dirty диалог закрытия не показывается — окно закрывается сразу."""
    window = MainWindow()
    qtbot.addWidget(window)
    session = TopologySession()  # clean
    window.set_topology_session(session, None)

    called = {"exec": False}

    def _boom(self):
        called["exec"] = True
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", _boom)

    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert called["exec"] is False
    assert event.isAccepted() is True


def test_close_without_session_accepts(qtbot) -> None:
    """Без сессии (None) closeEvent работает как раньше — окно закрывается."""
    window = MainWindow()
    qtbot.addWidget(window)
    event = QCloseEvent()
    event.accept()
    window.closeEvent(event)
    assert event.isAccepted() is True
