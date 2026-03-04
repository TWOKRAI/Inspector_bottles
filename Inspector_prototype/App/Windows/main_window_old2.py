# -*- coding: utf-8 -*-
"""
MainWindow — главное окно приложения.

Ответственность: ТОЛЬКО сборка UI из виджетов и проксирование Qt-сигналов.
Вся бизнес-логика делегирована:
  - WindowManager   — RouterManager, IPC-каналы, send_register_update
  - SortController  — рецепты, автосохранение, reset_count
  - RegistersManager — единственный источник состояния регистров
  - Виджеты         — отображение и пользовательский ввод

Иерархия создания:
  WindowManager.create_all_windows()
    └── MainWindow.__init__()
          ├── _init_managers()    — создать RegistersManager, DataManager и др.
          ├── _init_ui()          — собрать виджеты и layout
          ├── _connect_signals()  — подключить Qt-сигналы
          ├── _apply_fullscreen() — применить настройки окна
          └── _startup()          — создать SortController, установить уровень доступа
"""
from typing import Any

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from App.Components.header import HeaderWidget
from App.Core.Managers import (
    ConverterManager,
    DataManager,
    LoggingManager,
    RecipeManager,
)
from App.Core.base_configurable_widget import ConfigurableWidget
from App.Registers import RegistersManager
from App.Registers.models.registers.processing import ProcessingRegisters
from App.Widget.Circle_widjet.Circle import CircleWidget
from App.Widget.Hikvision_widjet.Hikvision import HikvisionWidget
from App.Widget.ImagePanel import ImagePanelWidget
from App.Widget.Logging_widget import LoggingWidget
from App.Widget.Post_processing_widjet.Post_processing import PostProcessingWidget
from App.Widget.Processing_widjet.Processing import ProcessingWidget
from App.Widget.Sort_widjet import SortController, SortData, SortWidget
from App.Widget.Visual_config_widget import VisualConfigWidget


class MainWindow(QMainWindow):
    """
    Главное окно приложения — чистый контейнер-compositor.

    Публичный API (вызывается из WindowManager / потоков):
        update_data(frames)        ← UpdateImage QThread → отображение кадров
        update_access_level(level) ← WindowManager после входа администратора
        close_programm()           ← WindowManager при завершении
        controls_post_processing   ← property для UpdateImage thread (миграционный шим)
    """

    def __init__(self, window_manager=None) -> None:
        super().__init__()
        self._wm = window_manager

        # Метрики производительности: пишет UpdateImage thread, читают виджеты
        self.fps_after_processing: float = 0.0
        self.processing_time_ms: float = 0.0
        self.total_time_ms: float = 0.0
        self.image_width: int = 0
        self.image_height: int = 0
        self.current_access_level: int = 0

        # Миграционный шим: UpdateImage читает режим отображения отсюда.
        # TODO: переключить UpdateImage на прямое чтение PostProcessingRegisters.
        self._ctrls_post_processing: dict = {
            "enable_post_processing": False,
            "regions": [],
            "region_chains": {},
            "view_mode": "main",
            "selected_region": None,
            "selected_image": "original",
            "show_region_processed": False,
        }

        self._init_managers()
        self._init_ui()
        self._connect_signals()
        self._apply_fullscreen()
        self._startup()

    # ------------------------------------------------------------------
    # Backward-compat свойства (читаются из UpdateImage thread)
    # ------------------------------------------------------------------

    @property
    def header(self):
        """Публичный доступ к HeaderWidget (используется WindowManager для подключения сигналов)."""
        return self._header

    @property
    def controls_post_processing(self) -> dict:
        """Шим для UpdateImage thread.
        PostProcessingWidget пишет в тот же dict, UpdateImage читает.
        TODO: заменить прямым чтением PostProcessingRegisters.
        """
        return self._ctrls_post_processing

    @property
    def controls_processing(self) -> dict:
        """Шим для UpdateImage thread — параметры обработки.
        Читает актуальное состояние из RegistersManager.
        TODO: заменить прямым чтением ProcessingRegisters в UpdateImage thread.
        """
        reg = self.registers_manager.get_register("processing")
        return reg.model_dump() if reg else {}

    @property
    def controls_draw(self) -> dict:
        """Шим для UpdateImage thread — параметры отрисовки оверлея.
        Читает актуальное состояние из RegistersManager.
        TODO: заменить прямым чтением DrawRegisters в UpdateImage thread.
        """
        reg = self.registers_manager.get_register("draw")
        return reg.model_dump() if reg else {}

    # ------------------------------------------------------------------
    # Менеджеры
    # ------------------------------------------------------------------

    def _init_managers(self) -> None:
        """Создать доменные менеджеры.

        Роутер НЕ создаётся здесь — он живёт в WindowManager.
        После создания RegistersManager регистрируем observer в WindowManager
        чтобы любые программные изменения регистров уходили в бэкенд.
        """
        self.logging_manager = LoggingManager(
            queue_manager=getattr(self._wm, "queue_manager", None)
        )
        self.registers_manager = RegistersManager()

        _conv = ConverterManager()
        self.recipe_manager = RecipeManager(
            converter=_conv, registers_manager=self.registers_manager
        )
        self.data_manager = DataManager(
            recipe_manager=self.recipe_manager, converter=_conv
        )
        self._sort_data = SortData(recipe_manager=self.recipe_manager)

        # Подключаем глобальный observer: программные изменения регистров → IPC
        if self._wm and hasattr(self._wm, "setup_register_observer"):
            self._wm.setup_register_observer(self.registers_manager)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setWindowTitle("Inspector")
        self.setMinimumSize(800, 600)
        self.setGeometry(100, 100, 1200, 800)

        self._header = HeaderWidget(window_manager=self._wm)
        self._image_panel = ImagePanelWidget(self.registers_manager, parent=self)
        self._tab_widget = self._build_tabs()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._image_panel)
        layout.addSpacing(3)
        layout.addWidget(self._tab_widget, stretch=1)
        self.setCentralWidget(central)

    def _build_tabs(self) -> QTabWidget:
        """Собрать QTabWidget из виджетов-вкладок.

        Каждая вкладка — самостоятельный виджет из App/Widget/.
        MainWindow не знает о внутреннем устройстве виджетов.
        """
        tab_widget = QTabWidget()
        tab_widget.setMinimumHeight(220)
        tab_widget.setStyleSheet(
            "QTabBar::tab { height: 35px; width: 95px; }"
            "QTabWidget::pane { border: 1px solid #ccc; }"
        )

        # ── Сорта (рецепты) ──────────────────────────────────────────
        # SortWidget — только отображение. SortController создаётся в _startup()
        # после того как все виджеты собраны (нужен params_provider).
        self._sort_widget = SortWidget(
            self._sort_data,
            default_number=2,
            params_provider=None,   # будет установлен в _startup()
        )

        sort_container = QWidget()
        sort_layout = QVBoxLayout(sort_container)
        sort_layout.addWidget(self._sort_widget)

        reset_btn = QPushButton("Сбросить значения")
        reset_btn.setFixedSize(200, 50)
        # Сигнал reset подключается к SortController в _startup()
        self._reset_btn = reset_btn
        sort_layout.addWidget(reset_btn)

        tab_widget.addTab(self._wrap_scroll(sort_container), "Сорта")

        # ── Визуальная настройка ─────────────────────────────────────
        app_config = getattr(self._wm, "app_config", None)
        tab_widget.addTab(
            self._wrap_scroll(
                VisualConfigWidget(window_manager=self._wm, app_config=app_config)
            ),
            "Визуальная настройка",
        )

        # ── Логирование ──────────────────────────────────────────────
        tab_widget.addTab(
            self._wrap_scroll(
                LoggingWidget(
                    window_manager=self._wm,
                    logging_manager=self.logging_manager,
                )
            ),
            "Логирование",
        )

        # ── Hikvision ────────────────────────────────────────────────
        qm = getattr(self._wm, "queue_manager", None)
        _cam_controls: dict = {
            "source": "camera",
            "image_path": "Data/last_frame.png",
            "enable_main_processing": True,
        }

        def _dispatch_camera() -> None:
            # TODO: заменить на self._wm.send_register_update("camera", ...)
            if qm:
                qm.remove_old_frame_if_full(qm.control_camera)
                qm.control_camera.put(dict(_cam_controls))
                if hasattr(qm, "control_camera_event"):
                    qm.control_camera_event.set()
                for q in (
                    getattr(qm, "control_source", None),
                    getattr(qm, "control_source_image", None),
                ):
                    if q:
                        qm.remove_old_frame_if_full(q)
                        q.put(dict(_cam_controls))

        self._hikvision_widget = HikvisionWidget(
            window_manager=self._wm,
            ui_elements={},
            controls_hikvision={},
            controls_camera=_cam_controls,
            callback=lambda: None,
            callback_camera=_dispatch_camera,
            stop_event=getattr(self._wm, "stop_event", None),
            data_manager=self.data_manager,
        )
        tab_widget.addTab(self._wrap_scroll(self._hikvision_widget), "Hikvision")

        # ── Регионы (PostProcessing) ─────────────────────────────────
        def _dispatch_post_processing() -> None:
            # TODO: заменить на self._wm.send_register_update("post_processing", ...)
            if qm:
                qm.remove_old_frame_if_full(qm.control_post_processing)
                qm.control_post_processing.put(dict(self._ctrls_post_processing))

        tab_widget.addTab(
            self._wrap_scroll(
                PostProcessingWidget(
                    window_manager=self._wm,
                    ui_elements={},
                    controls_post_processing=self._ctrls_post_processing,
                    callback=_dispatch_post_processing,
                    data_manager=self.data_manager,
                )
            ),
            "Регионы",
        )

        # ── Обработка (Processing) ───────────────────────────────────
        _processing_controls = ProcessingRegisters().model_dump()

        def _dispatch_processing() -> None:
            # TODO: заменить на self._wm.send_register_update("processing", ...)
            if qm:
                qm.remove_old_frame_if_full(qm.control_processing)
                qm.control_processing.put(dict(_processing_controls))
                if hasattr(qm, "control_processing_event"):
                    qm.control_processing_event.set()

        tab_widget.addTab(
            self._wrap_scroll(
                ProcessingWidget(
                    window_manager=self._wm,
                    ui_elements={},
                    controls_processing=_processing_controls,
                    callback=_dispatch_processing,
                    data_manager=self.data_manager,
                    controls_post_processing=self._ctrls_post_processing,
                    callback_post_processing=_dispatch_post_processing,
                )
            ),
            "Обработка",
        )

        # ── Форма (CircleWidget) ─────────────────────────────────────
        tab_widget.addTab(
            self._wrap_scroll(CircleWidget(window_manager=self._wm)),
            "Форма",
        )

        # ── Кнопка Скрыть / Показать ─────────────────────────────────
        self._tabs_visible = True
        self._btn_toggle = QPushButton("Скрыть")
        self._btn_toggle.setFixedHeight(35)
        self._btn_toggle.setFixedWidth(95)
        self._btn_toggle.clicked.connect(self._toggle_tabs)
        self._btn_toggle.setStyleSheet(
            "QPushButton {"
            "  background-color: #f0f0f0; border: none;"
            "  border-top-left-radius: 4px; border-top-right-radius: 4px;"
            "  padding: 0px; font-size: 12px;"
            "}"
            "QPushButton:hover { background-color: #e0e0e0; }"
            "QPushButton:pressed { background-color: #d0d0d0; }"
        )
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.addWidget(self._btn_toggle)
        tab_widget.setCornerWidget(corner, Qt.TopRightCorner)

        return tab_widget

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QScrollArea:
        """Обернуть виджет в QScrollArea (широкий скроллбар для touch-экранов)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollBar:vertical { width: 40px; }")
        scroll.setWidget(widget)
        return scroll

    # ------------------------------------------------------------------
    # Подключение сигналов и настройка окна
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.data_manager.data_changed.connect(self._on_data_changed)
        thread = getattr(self._hikvision_widget, "camera_message_thread", None)
        if thread:
            thread.message_received.connect(self._on_camera_message)

    def _apply_fullscreen(self) -> None:
        if not getattr(self._wm, "fullscreen", False):
            self.showNormal()
            return
        app_config = getattr(self._wm, "app_config", None)
        if app_config and app_config.get_limit_fullhd():
            w = app_config.get_fullscreen_limit_width()
            h = app_config.get_fullscreen_limit_height()
            self.setFixedSize(w, h)
            screen = self.screen().availableGeometry()
            self.move((screen.width() - w) // 2, (screen.height() - h) // 2)
        else:
            self.showFullScreen()

    def _startup(self) -> None:
        """Финальный шаг инициализации: создать SortController и применить уровень доступа.

        SortController создаётся здесь (а не в _init_managers) потому что ему нужен
        уже созданный _sort_widget, который появляется только после _build_tabs().
        """
        # Передаём ссылку на data_manager в window_manager для автосохранения в SortController
        if self._wm:
            self._wm._data_manager_ref = self.data_manager

        self._sort_controller = SortController(
            sort_widget=self._sort_widget,
            sort_data=self._sort_data,
            registers_manager=self.registers_manager,
            window_manager=self._wm,
        )

        # SortWidget теперь может получать живые параметры через контроллер
        self._sort_widget.set_params_provider(self._sort_controller.get_all_params)

        # Кнопка "Сбросить значения" подключается к контроллеру
        self._reset_btn.clicked.connect(self._sort_controller.reset_count)

        self.update_access_level(self.current_access_level)

    # ------------------------------------------------------------------
    # Публичный API — вызывается из WindowManager / потоков
    # ------------------------------------------------------------------

    def update_data(self, frames: list) -> None:
        """Slot для UpdateImage.update_frame — отображает кадры и обновляет FPS."""
        if frames:
            self._image_panel.display_frames(frames)
        if hasattr(self._hikvision_widget, "update_fps_metrics"):
            self._hikvision_widget.update_fps_metrics(
                self.fps_after_processing,
                self.processing_time_ms,
                self.total_time_ms,
            )

    def update_access_level(self, level: int) -> None:
        """Распространить уровень доступа на все ConfigurableWidget в дереве.

        Вызывается WindowManager после входа администратора.
        """
        self.current_access_level = level
        for child in self.findChildren(ConfigurableWidget):
            child.access_level = level

    def update_fps_display(self) -> None:
        """Обновить отображение FPS и размера изображения в HikvisionWidget.

        Вызывается UpdateImage thread когда меняется размер кадра.
        """
        if hasattr(self._hikvision_widget, "image_width"):
            self._hikvision_widget.image_width = self.image_width
            self._hikvision_widget.image_height = self.image_height
        if hasattr(self._hikvision_widget, "update_fps_display"):
            self._hikvision_widget.update_fps_display()

    def close_programm(self) -> None:
        """Корректное завершение: остановить потоки и закрыть окно."""
        if hasattr(self._hikvision_widget, "stop_thread"):
            self._hikvision_widget.stop_thread()
        stop_event = getattr(self._wm, "stop_event", None)
        if stop_event:
            stop_event.set()
        self.close()

    # ------------------------------------------------------------------
    # Приватные обработчики событий
    # ------------------------------------------------------------------

    def _on_data_changed(self) -> None:
        pass

    def _on_camera_message(self, message: dict) -> None:
        msg_type = message.get("type")
        if msg_type == "image_size":
            self.image_height = message.get("height", 0)
            self.image_width = message.get("width", 0)
            if hasattr(self._hikvision_widget, "image_width"):
                self._hikvision_widget.image_width = self.image_width
                self._hikvision_widget.image_height = self.image_height
            if hasattr(self._hikvision_widget, "update_fps_display"):
                self._hikvision_widget.update_fps_display()
        elif msg_type == "parameters_response":
            params = message.get("parameters", {})
            self.fps_after_processing = params.get("frame_rate", 0.0)

    def _toggle_tabs(self) -> None:
        self._tabs_visible = not self._tabs_visible
        if self._tabs_visible:
            self._tab_widget.setMaximumHeight(16_777_215)
            self._tab_widget.setMinimumHeight(220)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(True)
            self._btn_toggle.setText("Скрыть")
        else:
            tab_bar_h = self._tab_widget.tabBar().sizeHint().height()
            corner_h = self._btn_toggle.sizeHint().height()
            total_h = max(tab_bar_h, corner_h) + 2
            self._tab_widget.setMaximumHeight(total_h)
            self._tab_widget.setMinimumHeight(total_h)
            for i in range(self._tab_widget.count()):
                w = self._tab_widget.widget(i)
                if w:
                    w.setVisible(False)
            self._btn_toggle.setText("Показать")

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        event.accept()
