"""MainWindow — главное окно: AppHeader + ImagePanel-placeholder + TabWidget + StatusBar."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPoint, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets.chrome.app_header import AppHeaderWidget
from ..widgets.chrome.error_banner import ErrorBannerWidget
from .config import MainWindowConfig

# Высоты chrome (UI-настройки видимой плотности интерфейса)
# ВАЖНО: QSS темы (themes/innotech_theme/main.qss) задаёт min/max-height для
# QWidget#AppHeader — фактическая высота берётся оттуда. Здесь дублируем для
# виджетов без темы; держим значения синхронно с QSS.
HEADER_HEIGHT_PX = 60  # высота шапки AppHeader (было 96 в QSS, /1.6)
TAB_FONT_SCALE = 1.0 / 1.2  # масштаб шрифта виджета вкладок (ужимает табы в 1.2×)

# Поведение кнопки «Скрыть»
HIDE_LONG_PRESS_MS = 280  # удержание ≥ этого порога → drag-режим вместо клика
# Минимальная высота вкладок в drag-режиме = высота полосы tabBar (см.
# `_tab_bar_only_height`). Утянуть ниже нельзя: иначе сама кнопка «Скрыть»
# (живёт в cornerWidget tabBar'а) исчезнет, и вернуть вкладки будет нечем.


class HideToggleButton(QPushButton):
    """Кнопка с двумя жестами:

    • короткое нажатие (≤ ``HIDE_LONG_PRESS_MS``) → ``clicked`` (обычный toggle);
    • удержание дольше порога → ``dragStarted`` + ``dragMoved(dy)`` на движение
      курсора (dy положительное при движении вверх — «вытягиваем» вкладки);
    • отпускание после drag → ``dragFinished``; ``clicked`` в этом случае не
      эмитится.

    Управление кликом и нажатым состоянием выполнено вручную (без super()
    в mouse-event'ах), чтобы избежать гонок между QPushButton-логикой
    и нашим drag-состоянием.
    """

    dragStarted = Signal()
    dragMoved = Signal(int)
    dragFinished = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._press_global: QPoint | None = None
        self._drag_active = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(HIDE_LONG_PRESS_MS)
        self._hold_timer.timeout.connect(self._activate_drag)

    def _activate_drag(self) -> None:
        if self._press_global is None:
            return
        self._drag_active = True
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.dragStarted.emit()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            self._drag_active = False
            self.setDown(True)
            self._hold_timer.start()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_active and self._press_global is not None:
            dy = self._press_global.y() - e.globalPosition().toPoint().y()
            self.dragMoved.emit(dy)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(e)
            return
        self._hold_timer.stop()
        was_drag = self._drag_active
        self._drag_active = False
        self._press_global = None
        self.setDown(False)
        if was_drag:
            self.unsetCursor()
            self.dragFinished.emit()
        else:
            inside = self.rect().contains(e.position().toPoint())
            if inside:
                self.clicked.emit()
        e.accept()


class MainWindow(QMainWindow):
    """Главное окно Inspector v2.

    Layout (сверху вниз):
      1. AppHeaderWidget  — бренд + статус  (фиксированная высота 60 px)
      2. ImagePanel placeholder (stretch=1) — заменяется через set_image_panel()
      3. QTabWidget        — вкладки управления
    StatusBar: fps + latency.
    """

    def __init__(self, config: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Парсинг конфига (dict at boundary → Pydantic внутри)
        cfg = MainWindowConfig(**(config or {}))
        self.setWindowTitle(cfg.window.title)
        self.setMinimumSize(cfg.window.min_width, cfg.window.min_height)
        self.resize(cfg.window.min_width, cfg.window.min_height)

        # Центральный виджет с вертикальным layout
        central = QWidget()
        self.setCentralWidget(central)
        self._layout = QVBoxLayout(central)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # 1. Header (фиксированная высота — HEADER_HEIGHT_PX)
        self._header = AppHeaderWidget()
        self._header.setFixedHeight(HEADER_HEIGHT_PX)
        self._layout.addWidget(self._header)

        # 1.5. Баннер ошибок/предупреждений (скрыт по умолчанию)
        self._error_banner = ErrorBannerWidget()
        self._layout.addWidget(self._error_banner)

        # 2. Image panel placeholder — будет заменён реальным ImagePanel
        self._image_panel_placeholder = QWidget()
        self._image_panel_placeholder.setObjectName("ImagePanelPlaceholder")
        self._image_panel_placeholder.setMinimumHeight(200)
        self._layout.addWidget(self._image_panel_placeholder, stretch=1)
        self._image_panel: QWidget | None = None

        # 3. TabWidget
        self._tab_widget = QTabWidget()
        # Шрифт виджета вкладок ужат в TAB_FONT_SCALE раз → весь tab_widget
        # (включая tabBar и контент страниц) визуально компактнее.
        _tab_font = self._tab_widget.font()
        _tab_font.setPointSizeF(max(6.0, _tab_font.pointSizeF() * TAB_FONT_SCALE))
        self._tab_widget.setFont(_tab_font)
        # Запретить растягивание табов — заголовки прижаты к левому краю.
        self._tab_widget.tabBar().setExpanding(False)
        self._tabs_visible = True
        # Запомненная пользовательская высота (drag-режим). None → авто.
        self._tab_preferred_height: int | None = None
        # Когда drag-режим «зашёл» в зону image_panel, мы временно прячем панель.
        # Этот флаг помогает корректно вернуть её при показе вкладок.
        self._image_panel_hidden_by_drag = False
        self._layout.addWidget(self._tab_widget)

        # Угловой виджет: только кнопка «Скрыть».
        # Undo/Redo переехали в каждую вкладку (через StandardTabLayout) —
        # см. docs/plan: lauout-cozy-sphinx.md. Ctrl+Z / Ctrl+Y по-прежнему
        # подвешены к окну в set_action_bus().
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        corner_layout.setSpacing(2)

        self._toggle_btn = HideToggleButton("▲")
        self._toggle_btn.setToolTip(
            "Клик — скрыть/показать вкладки.\nУдержание + движение вверх/вниз — плавная регулировка высоты."
        )
        self._toggle_btn.setFixedSize(36, 40)
        self._toggle_btn.clicked.connect(self._toggle_tabs)
        # Drag-сигналы: запоминаем стартовую высоту, во время drag меняем её,
        # на отпускании фиксируем как _tab_preferred_height.
        self._drag_start_h: int = 0
        self._toggle_btn.dragStarted.connect(self._on_drag_started)
        self._toggle_btn.dragMoved.connect(self._on_drag_moved)
        self._toggle_btn.dragFinished.connect(self._on_drag_finished)

        corner_layout.addWidget(self._toggle_btn)
        self._tab_widget.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        # StatusBar
        self._dirty_label = QLabel("")
        self._dirty_label.setObjectName("DirtyLabel")
        self._dirty_label.setVisible(False)
        self.statusBar().addWidget(self._dirty_label)

        self._fps_label = QLabel("FPS: —")
        self._latency_label = QLabel("Latency: —")
        self._frames_label = QLabel("Frames: —")
        self.statusBar().addPermanentWidget(self._fps_label)
        self.statusBar().addPermanentWidget(self._latency_label)
        self.statusBar().addPermanentWidget(self._frames_label)

        # Счётчик кадров для расчёта FPS
        self._frame_count = 0

        # ActionBus (Phase 11) — устанавливается через set_action_bus()
        self._action_bus = None

        # Восстановить позицию и размер окна из прошлой сессии
        self._settings = QSettings("INNOTECH", "Inspector")
        self._restore_geometry()

    # -- Сохранение/восстановление геометрии окна --

    def _restore_geometry(self) -> None:
        """Восстановить позицию и размер из QSettings."""
        geometry = self._settings.value("mainwindow/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
            # Проверка: окно может оказаться за пределами экранов
            if QApplication.instance() is not None:
                screen = QApplication.screenAt(self.pos())
                if screen is None:
                    # Экран не найден — центрируем на primary
                    self.resize(self.size())

    def _save_geometry(self) -> None:
        """Сохранить позицию и размер в QSettings."""
        self._settings.setValue("mainwindow/geometry", self.saveGeometry())

    def closeEvent(self, event) -> None:
        """Сохранить геометрию при закрытии окна."""
        self._save_geometry()
        super().closeEvent(event)

    # -- Properties --

    @property
    def header(self) -> AppHeaderWidget:
        """Виджет заголовка (AppHeaderWidget)."""
        return self._header

    @property
    def tab_widget(self) -> QTabWidget:
        """Виджет вкладок."""
        return self._tab_widget

    @property
    def error_banner(self) -> ErrorBannerWidget:
        """Виджет баннера ошибок/предупреждений."""
        return self._error_banner

    # -- Image panel --

    def set_image_panel(self, widget: QWidget) -> None:
        """Заменить placeholder реальным ImagePanel.

        Новый виджет встраивается на то же место в layout (stretch=1).
        """
        idx = self._layout.indexOf(self._image_panel_placeholder)
        self._layout.removeWidget(self._image_panel_placeholder)
        self._image_panel_placeholder.deleteLater()
        self._layout.insertWidget(idx, widget, stretch=1)
        self._image_panel = widget

    # -- ActionBus (Phase 11) --

    def set_action_bus(self, bus: object) -> None:
        """Установить ActionBus и привязать Ctrl+Z / Ctrl+Y shortcuts.

        Сами кнопки Undo/Redo живут внутри каждой вкладки (через
        ``StandardTabLayout.enable_undo_redo``); здесь — только глобальные
        горячие клавиши на уровне окна.
        """
        self._action_bus = bus

        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.activated.connect(self._on_undo)
        self._undo_shortcut = undo_shortcut  # prevent GC

        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.activated.connect(self._on_redo)
        self._redo_shortcut = redo_shortcut  # prevent GC

    def _on_undo(self) -> None:
        """Отменить последнее действие."""
        if self._action_bus is None:
            return
        action = self._action_bus.undo()
        if action:
            self.statusBar().showMessage(f"Отменено: {action.description}", 3000)

    def _on_redo(self) -> None:
        """Повторить отменённое действие."""
        if self._action_bus is None:
            return
        action = self._action_bus.redo()
        if action:
            self.statusBar().showMessage(f"Повторено: {action.description}", 3000)

    # -- Toggle tabs --

    def _max_tab_height(self) -> int:
        """Максимально допустимая высота вкладок: всё пространство ниже шапки."""
        status_h = self.statusBar().sizeHint().height() if self.statusBar() else 0
        return max(0, self.height() - self._header.height() - status_h)

    def _show_tabs_full(self) -> None:
        """Показать вкладки в режиме «авто» (растяжение по содержимому).

        Не трогаем видимость дочерних страниц — этим управляет сам QTabWidget,
        иначе при следующем переключении остаются артефакты от скрытых страниц.
        """
        self._tab_widget.setMinimumHeight(0)
        self._tab_widget.setMaximumHeight(16777215)
        self._tab_widget.setVisible(True)
        if self._image_panel_hidden_by_drag and self._image_panel is not None:
            self._image_panel.setVisible(True)
            self._image_panel_hidden_by_drag = False
        # Принудительный re-layout, чтобы убрать визуальные остатки.
        self._tab_widget.updateGeometry()
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def _tab_bar_only_height(self) -> int:
        """Высота, при которой видна только полоса tabBar + cornerWidget."""
        tab_bar_h = self._tab_widget.tabBar().sizeHint().height()
        corner_h = self._toggle_btn.sizeHint().height()
        return max(tab_bar_h, corner_h) + 4

    def _collapse_to_tab_bar(self) -> None:
        """Свернуть до полосы tabBar (контент скрыт, кнопка «Показать» видна).

        Это поведение короткого клика по умолчанию — пользователь всегда
        может вернуть вкладки обратно. Полное исчезновение возможно только
        через drag-режим.
        """
        self._tab_widget.setVisible(True)
        self._tab_widget.setFixedHeight(self._tab_bar_only_height())
        if self._image_panel_hidden_by_drag and self._image_panel is not None:
            self._image_panel.setVisible(True)
            self._image_panel_hidden_by_drag = False
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def _hide_tabs_fully(self) -> None:
        """Полностью скрыть QTabWidget (вызывается только из drag-режима).

        Использовать с осторожностью: после полного скрытия кнопка «Скрыть»
        тоже исчезает (она внутри cornerWidget tab_widget'а). Возврат —
        только через drag, начатый на самом tabBar… которого тоже нет.
        Поэтому из короткого клика этот метод НЕ вызывается.
        """
        self._tab_widget.setVisible(False)
        if self._image_panel_hidden_by_drag and self._image_panel is not None:
            self._image_panel.setVisible(True)
            self._image_panel_hidden_by_drag = False
        if self.centralWidget() is not None:
            self.centralWidget().update()

    def _apply_tab_height(self, h: int) -> None:
        """Применить произвольную высоту виджета вкладок (drag-режим).

        Высота клампится в диапазоне ``[tab_bar_only_h, max_h]``:

        • снизу — высота полосы tabBar (полностью спрятать нельзя, иначе
          сама кнопка «Скрыть» исчезнет и вернуть вкладки будет нечем);
        • сверху — всё свободное пространство до шапки; в этой точке
          image_panel перекрыт и временно скрывается.
        """
        min_h = self._tab_bar_only_height()
        max_h = self._max_tab_height()
        h = max(min_h, min(h, max_h))

        self._tab_widget.setVisible(True)
        self._tab_widget.setFixedHeight(h)

        # Если вкладки «доехали» до самой шапки — image_panel перекрыт, прячем.
        if self._image_panel is not None:
            should_hide_panel = h >= max_h - 1
            if should_hide_panel and self._image_panel.isVisible():
                self._image_panel.setVisible(False)
                self._image_panel_hidden_by_drag = True
            elif not should_hide_panel and self._image_panel_hidden_by_drag:
                self._image_panel.setVisible(True)
                self._image_panel_hidden_by_drag = False

    def _toggle_tabs(self) -> None:
        """Короткий клик «Скрыть/Показать».

        Сворачивает контент вкладок, оставляя полосу tabBar с кнопкой (чтобы
        можно было раскрыть обратно). Полное скрытие — только через
        удержание кнопки + drag вниз до 0 (см. ``_on_drag_*``).
        """
        self._tabs_visible = not self._tabs_visible
        if self._tabs_visible:
            if self._tab_preferred_height is not None:
                self._apply_tab_height(self._tab_preferred_height)
            else:
                self._show_tabs_full()
            self._toggle_btn.setText("▲")
        else:
            self._collapse_to_tab_bar()
            self._toggle_btn.setText("▼")

    # -- Drag-режим (удержание кнопки «Скрыть») --

    def _on_drag_started(self) -> None:
        """Начало drag: запомнить стартовую высоту виджета вкладок.

        Виджет всегда видим в drag-режиме (полное скрытие исключено
        нижним клампом в ``_apply_tab_height``). Если до drag вкладки
        были свёрнуты до tabBar — стартуем с этой минимальной высоты.
        """
        if not self._tab_widget.isVisible():
            self._tab_widget.setVisible(True)
            self._tab_widget.setFixedHeight(self._tab_bar_only_height())
        self._drag_start_h = self._tab_widget.height()

    def _on_drag_moved(self, dy: int) -> None:
        """Движение во время drag. ``dy`` положителен при движении вверх."""
        new_h = self._drag_start_h + dy
        self._apply_tab_height(new_h)

    def _on_drag_finished(self) -> None:
        """Конец drag: зафиксировать новую высоту как preferred.

        Если высота на отпускании равна минимальной (tabBar-only) — это
        эквивалент короткого клика «Скрыть»: помечаем как невидимые,
        но физически tabBar остаётся (с кнопкой возврата).
        """
        h = self._tab_widget.height()
        min_h = self._tab_bar_only_height()
        if h <= min_h + 1:
            self._tabs_visible = False
            self._tab_preferred_height = None
            self._toggle_btn.setText("▼")
        else:
            self._tabs_visible = True
            self._tab_preferred_height = h
            self._toggle_btn.setText("▲")

    # -- Live bindings (Phase 12) --

    def connect_bindings(self, bindings: object) -> None:
        """Подключить StatusBar к live state_delta через GuiStateBindings.

        Args:
            bindings: GuiStateBindings (принимает object для обратной совместимости).
        """
        if bindings is None or not hasattr(bindings, "bind"):
            return

        bindings.bind(
            "system.fps",
            self._fps_label,
            "text",
            formatter=lambda v: f"FPS: {v:.1f}" if isinstance(v, (int, float)) else "FPS: —",
        )
        bindings.bind(
            "system.latency_ms",
            self._latency_label,
            "text",
            formatter=lambda v: f"Latency: {v:.0f} ms" if isinstance(v, (int, float)) else "Latency: —",
        )
        bindings.bind(
            "system.total_frames",
            self._frames_label,
            "text",
            formatter=lambda v: f"Frames: {v}" if isinstance(v, (int, float)) else "Frames: —",
        )

        # Привязка баннера к системным ошибкам и предупреждениям.
        # Fallback в GuiStateBindings (getattr + callable) вызывает
        # show_error(value) / show_warning(value) напрямую.
        bindings.bind(
            "system.error",
            self._error_banner,
            "show_error",
        )
        bindings.bind(
            "system.warning",
            self._error_banner,
            "show_warning",
        )

    # -- Обратная совместимость (старый API) --

    def add_tab(self, widget: QWidget, title: str) -> int:
        """Добавить таб. Возвращает индекс вкладки."""
        return self._tab_widget.addTab(widget, title)

    def set_dirty_indicator(self, dirty: bool) -> None:
        """Показать/скрыть индикатор несохранённых изменений в StatusBar."""
        self._dirty_label.setVisible(dirty)
        self._dirty_label.setText("Изменения не сохранены" if dirty else "")

    def update_status(self, fps: float, latency_ms: float = 0.0) -> None:
        """Обновить StatusBar и header: fps и latency."""
        self._fps_label.setText(f"FPS: {fps:.1f}")
        self._latency_label.setText(f"Latency: {latency_ms:.1f} ms")
        # Дублируем ключевые метрики в header
        self._header.update_status(f"FPS: {fps:.1f} | Latency: {latency_ms:.1f} ms")

    def increment_frame_count(self) -> None:
        """Инкремент счётчика кадров (вызывается при каждом frame)."""
        self._frame_count += 1

    def reset_frame_count(self) -> int:
        """Сбросить счётчик и вернуть значение (для расчёта fps раз в секунду)."""
        count = self._frame_count
        self._frame_count = 0
        return count
