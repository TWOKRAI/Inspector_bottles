"""MainWindow — главное окно: AppHeader + ImagePanel-placeholder + TabWidget + StatusBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from collections.abc import Callable

    from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layout_protocol import (
        UndoRedoController,
    )

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
        self._header.fullscreenToggled.connect(self._toggle_fullscreen)
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
        # подвешены к окну в set_undo_controller() (G.4.4: domain CommandDispatcher).
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

        # RS-4 dirty-контур редактора топологии: два независимых индикатора.
        # «Несохранённые правки графа» (dirty, не в файле) и «граф ≠ живая система»
        # (diverged, не применён к backend). Отдельны от _dirty_label (тот — Settings).
        self._topo_dirty_label = QLabel("")
        self._topo_dirty_label.setObjectName("TopologyDirtyLabel")
        self._topo_dirty_label.setToolTip("В редакторе топологии есть несохранённые в рецепт правки")
        self._topo_dirty_label.setVisible(False)
        self.statusBar().addWidget(self._topo_dirty_label)

        self._topo_diverged_label = QLabel("")
        self._topo_diverged_label.setObjectName("TopologyDivergedLabel")
        self._topo_diverged_label.setToolTip("Граф в редакторе расходится с работающей системой — примените изменения")
        self._topo_diverged_label.setVisible(False)
        self.statusBar().addWidget(self._topo_diverged_label)

        # RS-4: сессия dirty-контура + callback сохранения (для closeEvent-подтверждения).
        # Устанавливаются composition root'ом через set_topology_session(). None → без
        # подтверждения при закрытии (поведение до RS-4).
        self._topology_session: object | None = None
        self._save_topology_fn: "Callable[[], bool] | None" = None

        self._fps_label = QLabel("FPS: —")
        self._latency_label = QLabel("Latency: —")
        self._frames_label = QLabel("Frames: —")
        self.statusBar().addPermanentWidget(self._fps_label)
        self.statusBar().addPermanentWidget(self._latency_label)
        self.statusBar().addPermanentWidget(self._frames_label)

        # Счётчик кадров для расчёта FPS
        self._frame_count = 0

        # Аккумулятор сквозной задержки цепочки (capture→display, мс) за секунду.
        self._chain_latency_sum = 0.0
        self._chain_latency_n = 0

        # Аккумулятор пер-сегментной трассировки кадра (frame-trace) за секунду:
        # label → сумма/счётчик мс. Заполняется только при INSPECTOR_FRAME_TRACE=1
        # (иначе trace пуст). Порядок ключей = порядок появления = ход кадра.
        self._trace_sums: dict[str, float] = {}
        self._trace_counts: dict[str, int] = {}
        self._trace_kinds: dict[str, str] = {}

        # Последняя сводка ветвей fan-in (trace_branches): хранит снимок per-frame,
        # НЕ усредняет — branches — это агрегаты по ветвям за один кадр.
        # Заполняется только при INSPECTOR_FRAME_TRACE=1 + нелинейный пайплайн.
        self._trace_branches_last: list[dict] | None = None

        # G.4.4: источник undo/redo (domain CommandDispatcher) —
        # устанавливается через set_undo_controller()
        self._undo_controller: "UndoRedoController | None" = None

        # F11 — toggle полноэкранного режима. Esc (выход) обрабатывается в
        # keyPressEvent, чтобы не перехватывать Escape у дочерних виджетов
        # (отмена редактирования, закрытие popup) — туда событие доходит,
        # только если его не обработал сфокусированный виджет.
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)

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
        """Подтвердить несохранённые правки графа (RS-4) и сохранить геометрию.

        C-2/C-5: закрытие приложения при dirty-редакторе МОЛЧА теряло применённые-но-
        несохранённые правки топологии. Теперь при dirty спрашиваем: Сохранить /
        Не сохранять / Отмена. «Отмена» → окно не закрывается (event.ignore()).
        """
        if not self._confirm_close_with_dirty():
            event.ignore()
            return
        self._save_geometry()
        super().closeEvent(event)

    def _confirm_close_with_dirty(self) -> bool:
        """Диалог подтверждения при закрытии с несохранёнными правками графа (RS-4).

        Returns:
            True — можно закрывать (нет dirty, либо пользователь сохранил/отказался
            от сохранения); False — закрытие отменено пользователем.
        """
        session = self._topology_session
        if session is None or not getattr(session, "dirty", False):
            return True

        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Несохранённые правки графа")
        box.setText("В редакторе топологии есть несохранённые правки.\nСохранить их перед выходом?")
        buttons = QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        if self._save_topology_fn is not None:
            buttons |= QMessageBox.StandardButton.Save
        box.setStandardButtons(buttons)
        box.button(QMessageBox.StandardButton.Discard).setText("Продолжить без сохранения")
        # Требование владельца: «Сохранить» — кнопка по умолчанию (безопасный исход).
        # Без save_fn (Save недоступна) дефолт — Отмена (не потерять правки случайно).
        if self._save_topology_fn is not None:
            box.setDefaultButton(QMessageBox.StandardButton.Save)
        else:
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        choice = box.exec()

        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save and self._save_topology_fn is not None:
            # Save с домен-валидацией (RS-5): провал (в т.ч. RecipeValidationError) →
            # НЕ закрываем окно, показываем ошибку, состояние/правки сохраняются.
            try:
                ok = self._save_topology_fn()
            except Exception as exc:  # noqa: BLE001 — surface, не роняем на ошибке сохранения
                QMessageBox.critical(self, "Сохранение графа", f"Не удалось сохранить: {exc}")
                return False
            if not ok:
                QMessageBox.critical(
                    self,
                    "Сохранение графа",
                    "Не удалось сохранить граф в активный рецепт — выход отменён.",
                )
                return False
        # «Продолжить без сохранения» или успешный Save → разрешаем закрытие.
        return True

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

    # -- Полноэкранный режим --

    def _toggle_fullscreen(self) -> None:
        """Переключить полноэкранный режим (вход / возврат обратно)."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._header.set_fullscreen_state(self.isFullScreen())

    def _exit_fullscreen(self) -> None:
        """Выйти из полноэкранного режима (Esc). В обычном режиме — no-op."""
        if self.isFullScreen():
            self.showNormal()
            self._header.set_fullscreen_state(False)

    def keyPressEvent(self, event) -> None:
        """Esc выходит из полноэкранного режима, если он активен.

        Событие доходит сюда только когда сфокусированный виджет его не
        обработал — поэтому Escape для отмены редактирования / закрытия
        popup продолжает работать как раньше.
        """
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._exit_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- Undo/Redo (G.4.4: domain CommandDispatcher) --

    def set_undo_controller(self, controller: "UndoRedoController") -> None:
        """Установить источник undo/redo и привязать Ctrl+Z / Ctrl+Y shortcuts.

        G.4.4: глобальные горячие клавиши идут в domain ``CommandDispatcher``
        (``services.commands``) — единая шина undo для всего приложения. Закрывает
        конфликт двух параллельных undo (legacy ActionBus на уровне окна vs domain
        в Pipeline): теперь и кнопки вкладок (``enable_undo_redo``), и Ctrl+Z/Y
        работают с одним источником.
        """
        self._undo_controller = controller

        undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_shortcut.activated.connect(self._on_undo)
        self._undo_shortcut = undo_shortcut  # prevent GC

        redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_shortcut.activated.connect(self._on_redo)
        self._redo_shortcut = redo_shortcut  # prevent GC

    def _on_undo(self) -> None:
        """Отменить последнее действие (domain undo)."""
        if self._undo_controller is None:
            return
        if self._undo_controller.undo():
            self.statusBar().showMessage("Отменено", 3000)

    def _on_redo(self) -> None:
        """Повторить отменённое действие (domain redo)."""
        if self._undo_controller is None:
            return
        if self._undo_controller.redo():
            self.statusBar().showMessage("Повторено", 3000)

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

    def set_topology_indicators(self, dirty: bool, diverged: bool) -> None:
        """RS-4: обновить индикаторы dirty-контура редактора топологии.

        Args:
            dirty: в редакторе есть несохранённые в рецепт правки графа.
            diverged: граф редактора расходится с работающей системой (нужен Apply).
        """
        self._topo_dirty_label.setVisible(dirty)
        self._topo_dirty_label.setText("● Граф: несохранённые правки" if dirty else "")
        self._topo_diverged_label.setVisible(diverged)
        self._topo_diverged_label.setText("⚠ Граф ≠ живая система" if diverged else "")

    def set_topology_session(self, session: object, save_fn: "Callable[[], bool] | None" = None) -> None:
        """RS-4: подключить сессию dirty-контура + callback сохранения (для closeEvent).

        Индикаторы обновляются подпиской ``session.add_change_callback`` на стороне
        composition root (app.py), здесь сессия нужна для подтверждения при закрытии
        приложения с несохранёнными правками (C-2/C-5).

        Args:
            session: TopologySession (structural: имеет ``.dirty``).
            save_fn: сохранить текущий граф в активный рецепт → bool успеха. None →
                в диалоге закрытия вариант «Сохранить» недоступен (только продолжить/отмена).
        """
        self._topology_session = session
        self._save_topology_fn = save_fn

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

    def record_chain_latency(self, ms: float) -> None:
        """Накопить сэмпл сквозной задержки кадра (capture→display, мс)."""
        self._chain_latency_sum += ms
        self._chain_latency_n += 1

    def reset_chain_latency(self) -> float | None:
        """Среднее задержки за период + сброс. None если не было кадров."""
        if self._chain_latency_n == 0:
            return None
        avg = self._chain_latency_sum / self._chain_latency_n
        self._chain_latency_sum = 0.0
        self._chain_latency_n = 0
        return avg

    def record_trace_spans(self, spans: object) -> None:
        """Накопить пер-сегментные времена из trace одного кадра.

        spans — item["trace"] (список спанов transport/process). Каждый спан
        агрегируется по label (transport: «from→to», process: «node:plugin»)
        для усреднения за период. Молча игнорирует не-список / битые спаны.
        """
        if not isinstance(spans, list):
            return
        for span in spans:
            if not isinstance(span, dict):
                continue
            kind = span.get("kind")
            ms = span.get("ms")
            if not isinstance(ms, (int, float)):
                continue
            if kind == "transport":
                label = f"{span.get('from')}→{span.get('to')}"
            elif kind == "process":
                label = f"{span.get('node')}:{span.get('plugin')}"
            elif kind == "merge":
                # merge-спан stitcher'а: отображается как «merge @ node»
                label = f"merge @ {span.get('node', '?')}"
            else:
                continue
            self._trace_sums[label] = self._trace_sums.get(label, 0.0) + ms
            self._trace_counts[label] = self._trace_counts.get(label, 0) + 1
            self._trace_kinds.setdefault(label, kind)

    def reset_trace_segments(self) -> list[dict] | None:
        """Средние по сегментам за период + сброс. None если трасс не было.

        Возвращает список {label, kind, ms} в порядке появления сегментов
        (= ход кадра по цепочке) для публикации в system.trace_segments.
        """
        if not self._trace_counts:
            return None
        segments = [
            {
                "label": label,
                "kind": self._trace_kinds.get(label, ""),
                "ms": self._trace_sums[label] / self._trace_counts[label],
            }
            for label in self._trace_sums
        ]
        self._trace_sums.clear()
        self._trace_counts.clear()
        self._trace_kinds.clear()
        return segments

    def record_trace_branches(self, branches: object) -> None:
        """Запомнить последнюю сводку ветвей fan-in из trace_branches.

        branches — item["trace_branches"]: список {branch, total_ms, spans}.
        Хранит только ПОСЛЕДНИЙ снимок per-frame (не усредняет — это агрегаты
        уже готовые из stitcher'а). Молча игнорирует не-список / None.
        """
        if not isinstance(branches, list) or len(branches) == 0:
            return
        self._trace_branches_last = branches

    def reset_trace_branches(self) -> list[dict] | None:
        """Вернуть последнюю сводку ветвей + сбросить. None если не было.

        Используется _update_fps для публикации system.trace_branches раз в
        секунду (последний снимок нелинейного кадра за период).
        """
        branches = self._trace_branches_last
        self._trace_branches_last = None
        return branches
