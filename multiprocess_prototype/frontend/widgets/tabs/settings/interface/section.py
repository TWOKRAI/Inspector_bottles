"""InterfaceSection — секция «Настройка интерфейса» во вкладке Settings.

Содержит кнопку «Обновить UI» — перезапускает Qt event loop,
полностью пересоздавая главное окно, все табы и тему оформления
без перезапуска самого процесса.

SectionProtocol:
    key         = "interface_settings"
    title       = "Настройка интерфейса"
    widget()    → self
    action_buttons() → []
    on_activated()   → None
    on_deactivated() → None
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_logger = logging.getLogger(__name__)


class InterfaceSection(QWidget):
    """Секция «Настройка интерфейса» — управление UI без перезапуска процесса.

    Реализует SectionProtocol: key, title, widget(), action_buttons(),
    on_activated(), on_deactivated().

    G.5.2: принимает узкий callback `request_ui_restart` (Interface Segregation —
    секция знает только «перезапусти UI», не GuiProcess). Если None —
    кнопка «Обновить UI» показывается, но не выполняет перезапуск (graceful degradation).
    """

    # SectionProtocol — идентификаторы секции
    key: str = "interface_settings"
    title: str = "Настройка интерфейса"

    def __init__(
        self,
        request_ui_restart: "Callable[[], None] | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._request_ui_restart = request_ui_restart
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # === Группа: Управление интерфейсом ===
        group = QGroupBox("Управление интерфейсом")
        group_layout = QVBoxLayout(group)

        desc = QLabel(
            "Пересоздание UI полностью перезапускает графический интерфейс: "
            "главное окно, все вкладки, тема оформления — "
            "без перезапуска приложения и без потери IPC-соединений."
        )
        desc.setWordWrap(True)
        desc.setObjectName("HintLabelLg")
        group_layout.addWidget(desc)

        # Кнопка «Обновить UI»
        btn_row = QHBoxLayout()
        self._btn_rebuild = QPushButton("Обновить UI")
        self._btn_rebuild.setToolTip("Перезапустить графический интерфейс (процесс продолжит работу)")
        self._btn_rebuild.setMinimumWidth(200)
        self._btn_rebuild.setMinimumHeight(36)
        self._btn_rebuild.setProperty("role", "primary")
        self._btn_rebuild.clicked.connect(self._on_rebuild_ui)
        btn_row.addWidget(self._btn_rebuild)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        layout.addWidget(group)

        # === Группа: Полноэкранный режим ===
        fs_group = QGroupBox("Полноэкранный режим")
        fs_layout = QVBoxLayout(fs_group)

        fs_desc = QLabel(
            "Развернуть приложение на весь экран (без рамки окна и панели задач). "
            "Повторное нажатие или клавиша F11 возвращают окно в обычный режим."
        )
        fs_desc.setWordWrap(True)
        fs_desc.setObjectName("HintLabelLg")
        fs_layout.addWidget(fs_desc)

        fs_btn_row = QHBoxLayout()
        self._btn_fullscreen = QPushButton("На весь экран")
        self._btn_fullscreen.setToolTip("Переключить полноэкранный режим (F11)")
        self._btn_fullscreen.setMinimumWidth(200)
        self._btn_fullscreen.setMinimumHeight(36)
        self._btn_fullscreen.setProperty("role", "primary")
        self._btn_fullscreen.clicked.connect(self._on_toggle_fullscreen)
        fs_btn_row.addWidget(self._btn_fullscreen)
        fs_btn_row.addStretch()
        fs_layout.addLayout(fs_btn_row)

        layout.addWidget(fs_group)
        layout.addStretch()

        # Горячая клавиша F11 — работает во всём приложении (ApplicationShortcut)
        self._fs_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fs_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._fs_shortcut.activated.connect(self._on_toggle_fullscreen)

    # ------------------------------------------------------------------
    # SectionProtocol
    # ------------------------------------------------------------------

    def widget(self) -> "InterfaceSection":
        """Вернуть виджет секции (self)."""
        return self

    def action_buttons(self) -> list:
        """Кнопки секции для action-колонки (пустой список)."""
        return []

    def on_activated(self) -> None:
        """Вызывается при переключении на эту секцию."""
        self._sync_fullscreen_label()

    def on_deactivated(self) -> None:
        """Вызывается при уходе с этой секции."""

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------

    def _on_rebuild_ui(self) -> None:
        """Перезапустить UI через injected callback.

        Если callback=None (тесты без runtime) — graceful no-op (G.5.2).
        """
        if self._request_ui_restart is None:
            _logger.warning("[InterfaceSection] request_ui_restart=None — перезапуск UI недоступен")
            return

        _logger.info("[InterfaceSection] Перезапуск UI по запросу пользователя")
        self._request_ui_restart()

    def _on_toggle_fullscreen(self) -> None:
        """Переключить полноэкранный режим главного окна.

        Использует ``self.window()`` — верхнеуровневое окно, содержащее секцию
        (главное окно приложения). Инъекция зависимостей не нужна.
        """
        window = self.window()
        if window is None:
            _logger.warning("[InterfaceSection] window() вернул None — полноэкранный режим недоступен")
            return

        if window.isFullScreen():
            _logger.info("[InterfaceSection] Выход из полноэкранного режима")
            window.showNormal()
        else:
            _logger.info("[InterfaceSection] Вход в полноэкранный режим")
            window.showFullScreen()
        self._sync_fullscreen_label()

    def _sync_fullscreen_label(self) -> None:
        """Обновить подпись кнопки под текущее состояние окна."""
        window = self.window()
        is_fullscreen = bool(window is not None and window.isFullScreen())
        self._btn_fullscreen.setText("Свернуть из полноэкранного" if is_fullscreen else "На весь экран")
