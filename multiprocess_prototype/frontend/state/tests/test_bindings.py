"""Тесты для frontend/state/bindings.py.

Используют pytest-qt (qtbot) для создания реальных Qt-виджетов.
Bridge мокается через MagicMock — важно убедиться, что
set_state_callback был вызван при инициализации GuiStateBindings.

Сообщения синтезируются вызовом bindings._on_state_msg() напрямую.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel, QSpinBox

from multiprocess_prototype.frontend.state.bindings import GuiStateBindings


# ---------------------------------------------------------------------------
# Вспомогательный fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge():
    """Мок DataReceiverBridge с методом set_state_callback."""
    mock = MagicMock()
    return mock


@pytest.fixture
def bindings(bridge):
    """Экземпляр GuiStateBindings с мок-bridge."""
    return GuiStateBindings(bridge)


# ---------------------------------------------------------------------------
# Инициализация
# ---------------------------------------------------------------------------


class TestInit:
    """Проверка инициализации GuiStateBindings."""

    def test_set_state_callback_called_on_init(self, bridge):
        """GuiStateBindings.__init__ должен вызвать bridge.set_state_callback."""
        b = GuiStateBindings(bridge)
        bridge.set_state_callback.assert_called_once_with(b._on_state_msg)


# ---------------------------------------------------------------------------
# Базовые property setters
# ---------------------------------------------------------------------------


class TestPropertySetters:
    """Проверка применения setter-ов при получении state_delta."""

    def test_bind_value_property_updates_spinbox(self, qtbot, bindings):
        """Базовый кейс: prop='value' → spinbox.setValue()."""
        spinbox = QSpinBox()
        qtbot.addWidget(spinbox)

        bindings.bind("processes.cam.state.fps", spinbox, "value")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": 42,
            }
        )

        assert spinbox.value() == 42

    def test_bind_text_property_updates_label(self, qtbot, bindings):
        """prop='text' → label.setText()."""
        label = QLabel()
        qtbot.addWidget(label)

        bindings.bind("services.capture.status", label, "text")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "services.capture.status",
                "value": "running",
            }
        )

        assert label.text() == "running"

    def test_bind_checked_property_updates_checkbox(self, qtbot, bindings):
        """prop='checked' → checkbox.setChecked()."""
        checkbox = QCheckBox()
        qtbot.addWidget(checkbox)
        checkbox.setChecked(False)

        bindings.bind("system.flags.enabled", checkbox, "checked")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "system.flags.enabled",
                "value": True,
            }
        )

        assert checkbox.isChecked() is True


# ---------------------------------------------------------------------------
# Glob-паттерны с несколькими подписчиками
# ---------------------------------------------------------------------------


class TestGlobMultipleSubscribers:
    """Проверка, что glob-паттерн срабатывает на нескольких виджетах."""

    def test_glob_pattern_matches_multiple_subscribers(self, qtbot, bindings):
        """Два виджета на 'processes.*.state.fps' — оба обновляются."""
        label1 = QLabel()
        label2 = QLabel()
        qtbot.addWidget(label1)
        qtbot.addWidget(label2)

        bindings.bind("processes.*.state.fps", label1, "text")
        bindings.bind("processes.*.state.fps", label2, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "25.3",
            }
        )

        assert label1.text() == "25.3"
        assert label2.text() == "25.3"


# ---------------------------------------------------------------------------
# Несовпадающий паттерн
# ---------------------------------------------------------------------------


class TestNoMatch:
    """Несовпадающий путь не должен вызывать setter."""

    def test_no_match_does_not_call_setter(self, qtbot, bindings):
        """Сообщение с path, не совпадающим с pattern — setter не вызывается."""
        label = QLabel("original")
        qtbot.addWidget(label)

        bindings.bind("processes.cam.state.fps", label, "text")
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.config.fps",  # другой сегмент 'config' вместо 'state'
                "value": "updated",
            }
        )

        assert label.text() == "original"


# ---------------------------------------------------------------------------
# Авто-уборка мёртвых виджетов
# ---------------------------------------------------------------------------


class TestDestroyedWidget:
    """После уничтожения виджета подписка должна быть убрана."""

    def test_destroyed_widget_is_pruned(self, qtbot, bindings):
        """После deleteLater() + обработки событий отправка не вызывает ошибок,
        и мёртвый weakref убирается из списка подписок."""
        label = QLabel("initial")
        qtbot.addWidget(label)

        bindings.bind("processes.cam.state.fps", label, "text")
        assert len(bindings._bindings) == 1

        # Уничтожаем виджет
        label.deleteLater()
        # Обрабатываем события Qt — destroyed signal должен прийти
        qtbot.wait(50)

        # Отправляем сообщение — не должно быть исключений
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )
        # Список должен быть очищен (либо через signal, либо через прунинг в _on_state_msg)
        assert len(bindings._bindings) == 0


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    """Formatter применяется до setter."""

    def test_formatter_applied_before_set(self, qtbot, bindings):
        """formatter=lambda v: f'{v:.1f}' → label получает строку '25.3'."""
        label = QLabel()
        qtbot.addWidget(label)

        bindings.bind(
            "processes.cam.state.fps",
            label,
            "text",
            formatter=lambda v: f"{v:.1f}",
        )
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": 25.3,
            }
        )

        assert label.text() == "25.3"


# ---------------------------------------------------------------------------
# Unbind
# ---------------------------------------------------------------------------


class TestUnbind:
    """unbind(handle) удаляет подписку, setter больше не вызывается."""

    def test_unbind_handle_removes_binding(self, qtbot, bindings):
        """После unbind(handle) сообщения не обновляют виджет."""
        label = QLabel("initial")
        qtbot.addWidget(label)

        handle = bindings.bind("processes.cam.state.fps", label, "text")

        # Убеждаемся, что до unbind — работает
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )
        assert label.text() == "updated"

        # Снимаем подписку
        bindings.unbind(handle)

        # Сообщение после unbind не должно изменить виджет
        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "path": "processes.cam.state.fps",
                "value": "should_not_appear",
            }
        )
        assert label.text() == "updated"


# ---------------------------------------------------------------------------
# Игнорирование некорректных сообщений
# ---------------------------------------------------------------------------


class TestIgnoreInvalidMessages:
    """Сообщения без обязательных полей — тихо игнорируются."""

    def test_wrong_data_type_ignored(self, qtbot, bindings):
        """data_type != 'state_delta' → игнорируется."""
        label = QLabel("original")
        qtbot.addWidget(label)
        bindings.bind("processes.cam.state.fps", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "frame_ready",
                "path": "processes.cam.state.fps",
                "value": "updated",
            }
        )

        assert label.text() == "original"

    def test_missing_path_ignored(self, qtbot, bindings):
        """Нет ключа 'path' — игнорируется."""
        label = QLabel("original")
        qtbot.addWidget(label)
        bindings.bind("processes.cam.state.fps", label, "text")

        bindings._on_state_msg(
            {
                "data_type": "state_delta",
                "value": "updated",
            }
        )

        assert label.text() == "original"
