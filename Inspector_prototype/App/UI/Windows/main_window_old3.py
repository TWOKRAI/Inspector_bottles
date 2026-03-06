# # -*- coding: utf-8 -*-
# """
# MainWindow — главное окно приложения.

# Ответственность: ТОЛЬКО сборка UI из виджетов и проксирование Qt-сигналов.
# Вся бизнес-логика делегирована:
#   - WindowManager   — RouterManager, IPC-каналы, send_register_update
#   - SortController  — рецепты, автосохранение, reset_count
#   - RegistersManager — единственный источник состояния регистров
#   - Виджеты         — отображение и пользовательский ввод

# Иерархия создания:
#   WindowManager.create_all_windows()
#     └── MainWindow.__init__()
#           ├── _init_managers()    — создать RegistersManager, DataManager и др.
#           ├── _init_ui()          — собрать виджеты и layout
#           ├── _connect_signals()  — подключить Qt-сигналы
#           ├── _apply_fullscreen() — применить настройки окна
#           └── _startup()          — создать SortController, установить уровень доступа
# """
# from typing import Any

# import numpy as np
# from PyQt5.QtCore import Qt, QTimer
# from PyQt5.QtWidgets import (
#     QHBoxLayout,
#     QMainWindow,
#     QPushButton,
#     QScrollArea,
#     QTabWidget,
#     QVBoxLayout,
#     QWidget,
# )

# from App.Components.header import HeaderWidget
# from App.Components.tab_widget import TabWidget, BaseTab  # новый импорт
# from App.Core.Managers import (
#     ConverterManager,
#     DataManager,
#     LoggingManager,
#     RecipeManager,
# )
# from App.Core.base_configurable_widget import ConfigurableWidget
# from App.Registers import RegistersManager
# from App.Registers.models.registers.processing import ProcessingRegisters
# from App.Widget.Circle_widjet.Circle import CircleWidget
# from App.Widget.Hikvision_widjet.Hikvision import HikvisionWidget
# from App.Widget.ImagePanel import ImagePanelWidget
# from App.Widget.Logging_widget import LoggingWidget
# from App.Widget.Post_processing_widjet.Post_processing import PostProcessingWidget
# from App.Widget.Processing_widjet.Processing import ProcessingWidget
# from App.Widget.Sort_widjet import SortController, SortData, SortWidget
# from App.Widget.Visual_config_widget import VisualConfigWidget


# class MainWindow(QMainWindow):
#     """
#     Главное окно приложения — чистый контейнер-compositor.

#     Публичный API (вызывается из WindowManager / потоков):
#         update_data(frames)        ← UpdateImage QThread → отображение кадров
#         update_access_level(level) ← WindowManager после входа администратора
#         close_programm()           ← WindowManager при завершении
#         controls_post_processing   ← property для UpdateImage thread (миграционный шим)
#     """

#     def __init__(self, window_manager=None) -> None:
#         super().__init__()
#         self._wm = window_manager

#         # Метрики производительности: пишет UpdateImage thread, читают виджеты
#         self.fps_after_processing: float = 0.0
#         self.processing_time_ms: float = 0.0
#         self.total_time_ms: float = 0.0
#         self.image_width: int = 0
#         self.image_height: int = 0
#         self.current_access_level: int = 0

#         # Миграционный шим: UpdateImage читает режим отображения отсюда.
#         # TODO: переключить UpdateImage на прямое чтение PostProcessingRegisters.
#         self._ctrls_post_processing: dict = {
#             "enable_post_processing": False,
#             "regions": [],
#             "region_chains": {},
#             "view_mode": "main",
#             "selected_region": None,
#             "selected_image": "original",
#             "show_region_processed": False,
#         }

#         self._init_managers()
#         self._init_ui()
#         self._connect_signals()
#         self._apply_fullscreen()
#         self._startup()

#     # ------------------------------------------------------------------
#     # Backward-compat свойства (читаются из UpdateImage thread)
#     # ------------------------------------------------------------------

#     @property
#     def header(self):
#         """Публичный доступ к HeaderWidget (используется WindowManager для подключения сигналов)."""
#         return self._header

#     @property
#     def controls_post_processing(self) -> dict:
#         """Шим для UpdateImage thread.
#         PostProcessingWidget пишет в тот же dict, UpdateImage читает.
#         TODO: заменить прямым чтением PostProcessingRegisters.
#         """
#         return self._ctrls_post_processing

#     @property
#     def controls_processing(self) -> dict:
#         """Шим для UpdateImage thread — параметры обработки.
#         Читает актуальное состояние из RegistersManager.
#         TODO: заменить прямым чтением ProcessingRegisters в UpdateImage thread.
#         """
#         reg = self.registers_manager.get_register("processing")
#         return reg.model_dump() if reg else {}

#     @property
#     def controls_draw(self) -> dict:
#         """Шим для UpdateImage thread — параметры отрисовки оверлея.
#         Читает актуальное состояние из RegistersManager.
#         TODO: заменить прямым чтением DrawRegisters в UpdateImage thread.
#         """
#         reg = self.registers_manager.get_register("draw")
#         return reg.model_dump() if reg else {}

#     # ------------------------------------------------------------------
#     # Менеджеры
#     # ------------------------------------------------------------------

#     def _init_managers(self) -> None:
#         """Создать доменные менеджеры.

#         Роутер НЕ создаётся здесь — он живёт в WindowManager.
#         После создания RegistersManager регистрируем observer в WindowManager
#         чтобы любые программные изменения регистров уходили в бэкенд.
#         """
#         self.logging_manager = LoggingManager(
#             queue_manager=getattr(self._wm, "queue_manager", None)
#         )
#         self.registers_manager = RegistersManager()

#         _conv = ConverterManager()
#         self.recipe_manager = RecipeManager(
#             converter=_conv, registers_manager=self.registers_manager
#         )
#         self.data_manager = DataManager(
#             recipe_manager=self.recipe_manager, converter=_conv
#         )
#         self._sort_data = SortData(recipe_manager=self.recipe_manager)

#         # Подключаем глобальный observer: программные изменения регистров → IPC
#         if self._wm and hasattr(self._wm, "setup_register_observer"):
#             self._wm.setup_register_observer(self.registers_manager)

#     # ------------------------------------------------------------------
#     # Построение UI
#     # ------------------------------------------------------------------

#     def _init_ui(self) -> None:
#         self.setWindowTitle("Inspector")
#         self.setMinimumSize(800, 600)
#         self.setGeometry(100, 100, 1200, 800)

#         self._header = HeaderWidget(window_manager=self._wm)
#         self._image_panel = ImagePanelWidget(self.registers_manager, parent=self)

#         # Создаём контейнер вкладок (теперь это TabWidget)
#         self._tab_widget = TabWidget()

#         # Заполняем вкладки
#         self._populate_tabs()

#         central = QWidget()
#         layout = QVBoxLayout(central)
#         layout.setContentsMargins(0, 0, 0, 0)
#         layout.setSpacing(2)
#         layout.addWidget(self._header)
#         layout.addWidget(self._image_panel)
#         layout.addSpacing(3)
#         layout.addWidget(self._tab_widget, stretch=1)
#         self.setCentralWidget(central)

#     def _populate_tabs(self) -> None:
#         """Создаёт и добавляет виджеты-вкладки в TabWidget."""
#         # ── Сорта (рецепты) ──────────────────────────────────────────
#         self._sort_widget = SortWidget(
#             self._sort_data,
#             default_number=2,
#             params_provider=None,   # будет установлен в _startup()
#         )

#         sort_container = QWidget()
#         sort_layout = QVBoxLayout(sort_container)
#         sort_layout.addWidget(self._sort_widget)

#         reset_btn = QPushButton("Сбросить значения")
#         reset_btn.setFixedSize(200, 50)
#         self._reset_btn = reset_btn
#         sort_layout.addWidget(reset_btn)

#         # Добавляем вкладку (обёртку вручную не делаем, т.к. wrap_scroll=False)
#         self._tab_widget.add_tab(sort_container, "Сорта", wrap_scroll=False)

#         # ── Визуальная настройка ─────────────────────────────────────
#         app_config = getattr(self._wm, "app_config", None)
#         # VisualConfigWidget не наследует BaseTab (пока), просто добавляем
#         self._tab_widget.add_tab(
#             VisualConfigWidget(window_manager=self._wm, app_config=app_config),
#             "Визуальная настройка"
#         )

#         # ── Логирование ──────────────────────────────────────────────
#         self._tab_widget.add_tab(
#             LoggingWidget(
#                 window_manager=self._wm,
#                 logging_manager=self.logging_manager,
#             ),
#             "Логирование"
#         )

#         # ── Hikvision ────────────────────────────────────────────────
#         qm = getattr(self._wm, "queue_manager", None)
#         _cam_controls: dict = {
#             "source": "camera",
#             "image_path": "Data/last_frame.png",
#             "enable_main_processing": True,
#         }

#         def _dispatch_camera() -> None:
#             # TODO: заменить на self._wm.send_register_update("camera", ...)
#             if qm:
#                 qm.remove_old_frame_if_full(qm.control_camera)
#                 qm.control_camera.put(dict(_cam_controls))
#                 if hasattr(qm, "control_camera_event"):
#                     qm.control_camera_event.set()
#                 for q in (
#                     getattr(qm, "control_source", None),
#                     getattr(qm, "control_source_image", None),
#                 ):
#                     if q:
#                         qm.remove_old_frame_if_full(q)
#                         q.put(dict(_cam_controls))

#         self._hikvision_widget = HikvisionWidget(
#             window_manager=self._wm,
#             ui_elements={},
#             controls_hikvision={},
#             controls_camera=_cam_controls,
#             callback=lambda: None,
#             callback_camera=_dispatch_camera,
#             stop_event=getattr(self._wm, "stop_event", None),
#             data_manager=self.data_manager,
#         )
#         self._tab_widget.add_tab(self._hikvision_widget, "Hikvision")

#         # ── Регионы (PostProcessing) ─────────────────────────────────
#         def _dispatch_post_processing() -> None:
#             # TODO: заменить на self._wm.send_register_update("post_processing", ...)
#             if qm:
#                 qm.remove_old_frame_if_full(qm.control_post_processing)
#                 qm.control_post_processing.put(dict(self._ctrls_post_processing))

#         self._tab_widget.add_tab(
#             PostProcessingWidget(
#                 window_manager=self._wm,
#                 ui_elements={},
#                 controls_post_processing=self._ctrls_post_processing,
#                 callback=_dispatch_post_processing,
#                 data_manager=self.data_manager,
#             ),
#             "Регионы"
#         )

#         # ── Обработка (Processing) ───────────────────────────────────
#         _processing_controls = ProcessingRegisters().model_dump()

#         def _dispatch_processing() -> None:
#             # TODO: заменить на self._wm.send_register_update("processing", ...)
#             if qm:
#                 qm.remove_old_frame_if_full(qm.control_processing)
#                 qm.control_processing.put(dict(_processing_controls))
#                 if hasattr(qm, "control_processing_event"):
#                     qm.control_processing_event.set()

#         self._tab_widget.add_tab(
#             ProcessingWidget(
#                 window_manager=self._wm,
#                 ui_elements={},
#                 controls_processing=_processing_controls,
#                 callback=_dispatch_processing,
#                 data_manager=self.data_manager,
#                 controls_post_processing=self._ctrls_post_processing,
#                 callback_post_processing=_dispatch_post_processing,
#             ),
#             "Обработка"
#         )

#         # ── Форма (CircleWidget) ─────────────────────────────────────
#         self._tab_widget.add_tab(
#             CircleWidget(window_manager=self._wm),
#             "Форма"
#         )

#     # ------------------------------------------------------------------
#     # Подключение сигналов и настройка окна
#     # ------------------------------------------------------------------

#     def _connect_signals(self) -> None:
#         self.data_manager.data_changed.connect(self._on_data_changed)
#         thread = getattr(self._hikvision_widget, "camera_message_thread", None)
#         if thread:
#             thread.message_received.connect(self._on_camera_message)

#     def _apply_fullscreen(self) -> None:
#         if not getattr(self._wm, "fullscreen", False):
#             self.showNormal()
#             return
#         app_config = getattr(self._wm, "app_config", None)
#         if app_config and app_config.get_limit_fullhd():
#             w = app_config.get_fullscreen_limit_width()
#             h = app_config.get_fullscreen_limit_height()
#             self.setFixedSize(w, h)
#             screen = self.screen().availableGeometry()
#             self.move((screen.width() - w) // 2, (screen.height() - h) // 2)
#         else:
#             self.showFullScreen()

#     def _startup(self) -> None:
#         """Финальный шаг инициализации: создать SortController и применить уровень доступа.

#         SortController создаётся здесь (а не в _init_managers) потому что ему нужен
#         уже созданный _sort_widget, который появляется только после _build_tabs().
#         """
#         # Передаём ссылку на data_manager в window_manager для автосохранения в SortController
#         if self._wm:
#             self._wm._data_manager_ref = self.data_manager

#         self._sort_controller = SortController(
#             sort_widget=self._sort_widget,
#             sort_data=self._sort_data,
#             registers_manager=self.registers_manager,
#             window_manager=self._wm,
#         )

#         # SortWidget теперь может получать живые параметры через контроллер
#         self._sort_widget.set_params_provider(self._sort_controller.get_all_params)

#         # Кнопка "Сбросить значения" подключается к контроллеру
#         self._reset_btn.clicked.connect(self._sort_controller.reset_count)

#         self.update_access_level(self.current_access_level)

#     # ------------------------------------------------------------------
#     # Публичный API — вызывается из WindowManager / потоков
#     # ------------------------------------------------------------------

#     def update_data(self, frames: list) -> None:
#         """Slot для UpdateImage.update_frame — отображает кадры и обновляет FPS."""
#         if frames:
#             self._image_panel.display_frames(frames)
#         if hasattr(self._hikvision_widget, "update_fps_metrics"):
#             self._hikvision_widget.update_fps_metrics(
#                 self.fps_after_processing,
#                 self.processing_time_ms,
#                 self.total_time_ms,
#             )

#     def update_access_level(self, level: int) -> None:
#         """Распространить уровень доступа на все ConfigurableWidget в дереве.

#         Вызывается WindowManager после входа администратора.
#         """
#         self.current_access_level = level
#         for child in self.findChildren(ConfigurableWidget):
#             child.access_level = level

#     def update_fps_display(self) -> None:
#         """Обновить отображение FPS и размера изображения в HikvisionWidget.

#         Вызывается UpdateImage thread когда меняется размер кадра.
#         """
#         if hasattr(self._hikvision_widget, "image_width"):
#             self._hikvision_widget.image_width = self.image_width
#             self._hikvision_widget.image_height = self.image_height
#         if hasattr(self._hikvision_widget, "update_fps_display"):
#             self._hikvision_widget.update_fps_display()

#     def close_programm(self) -> None:
#         """Корректное завершение: остановить потоки и закрыть окно."""
#         if hasattr(self._hikvision_widget, "stop_thread"):
#             self._hikvision_widget.stop_thread()
#         stop_event = getattr(self._wm, "stop_event", None)
#         if stop_event:
#             stop_event.set()
#         self.close()

#     # ------------------------------------------------------------------
#     # Приватные обработчики событий
#     # ------------------------------------------------------------------

#     def _on_data_changed(self) -> None:
#         pass

#     def _on_camera_message(self, message: dict) -> None:
#         msg_type = message.get("type")
#         if msg_type == "image_size":
#             self.image_height = message.get("height", 0)
#             self.image_width = message.get("width", 0)
#             if hasattr(self._hikvision_widget, "image_width"):
#                 self._hikvision_widget.image_width = self.image_width
#                 self._hikvision_widget.image_height = self.image_height
#             if hasattr(self._hikvision_widget, "update_fps_display"):
#                 self._hikvision_widget.update_fps_display()
#         elif msg_type == "parameters_response":
#             params = message.get("parameters", {})
#             self.fps_after_processing = params.get("frame_rate", 0.0)

#     # ------------------------------------------------------------------
#     # Qt overrides
#     # ------------------------------------------------------------------

#     def closeEvent(self, event) -> None:
#         event.accept()



# -*- coding: utf-8 -*-
"""
MainWindow — главное окно приложения.

Ответственность: ТОЛЬКО сборка UI из виджетов и проксирование Qt-сигналов.
Вся бизнес-логика делегирована:
  - WindowManager — управление окнами, IPC, команды камере
  - RegistersManager — единственный источник состояния регистров
  - DataManager / RecipeManager — рецепты, автосохранение
  - SortController — логика сортов/рецептов
  - PerformanceMonitor — метрики производительности (FPS, время обработки)
  - CameraService — работа с камерой (enum, open, параметры)

Иерархия создания (теперь менеджеры создаются в WindowManager и инжектируются):
  WindowManager.create_all_windows()
    ├── создаёт RegistersManager, DataManager, RecipeManager, PerformanceMonitor, CameraService
    ├── создаёт SortController
    └── создаёт MainWindow, передавая все зависимости
          ├── _init_ui()          — собрать виджеты и layout
          ├── _connect_signals()  — подключить Qt-сигналы
          ├── _apply_fullscreen() — применить настройки окна
          └── set_sort_controller() — установить контроллер (вызывается после создания)
"""

from typing import Any, Optional

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
from App.Components.tab_widget import TabWidget, BaseTab
from App.Core.Managers import (
    ConverterManager,
    DataManager,
    LoggingManager,
    RecipeManager,
)
from App.Core.base_configurable_widget import ConfigurableWidget
from App.Core.performance_monitor import PerformanceMonitor
from App.Registers import RegistersManager
from App.Services.camera_service import CameraService
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
    Главное окно приложения — чистый контейнер.

    Публичный API (вызывается из WindowManager / потоков):
        update_data(frames)        ← UpdateImage QThread → отображение кадров
        update_access_level(level) ← WindowManager после входа администратора
        close_programm()           ← WindowManager при завершении
        set_sort_controller(ctrl)  ← WindowManager после создания контроллера
    """

    def __init__(
        self,
        window_manager=None,
        registers_manager: Optional[RegistersManager] = None,
        data_manager: Optional[DataManager] = None,
        logging_manager: Optional[LoggingManager] = None,
        performance_monitor: Optional[PerformanceMonitor] = None,
        camera_service: Optional[CameraService] = None,
    ) -> None:
        super().__init__()
        self._wm = window_manager
        self._rm = registers_manager
        self._dm = data_manager
        self._lm = logging_manager
        self._perf_monitor = performance_monitor
        self._camera_service = camera_service

        # Уровень доступа (админ/оператор)
        self.current_access_level: int = 0

        # Контроллер сортов (будет установлен позже через set_sort_controller)
        self._sort_controller: Optional[SortController] = None

        # Виджеты, к которым нужен доступ извне
        self._header: Optional[HeaderWidget] = None
        self._image_panel: Optional[ImagePanelWidget] = None
        self._sort_widget: Optional[SortWidget] = None
        self._hikvision_widget: Optional[HikvisionWidget] = None
        self._reset_btn: Optional[QPushButton] = None

        # Данные сортов (YAML-хранилище) — создаётся здесь, но может быть передано извне
        self._sort_data = SortData(recipe_manager=self._dm.recipe_manager if self._dm else None)

        self._init_ui()
        self._connect_signals()
        self._apply_fullscreen()
        # Запуск автообновления не требуется, контроллер будет установлен позже

    # ------------------------------------------------------------------
    # Backward-compat свойства (для UpdateImage thread)
    # ------------------------------------------------------------------

    @property
    def header(self):
        """Публичный доступ к HeaderWidget (используется WindowManager для подключения сигналов)."""
        return self._header

    @property
    def controls_post_processing(self) -> dict:
        """Шим для UpdateImage thread — читает PostProcessingRegisters."""
        reg = self._rm.get_register("post_processing")
        return reg.model_dump() if reg else {}

    @property
    def controls_processing(self) -> dict:
        """Шим для UpdateImage thread — читает ProcessingRegisters."""
        reg = self._rm.get_register("processing")
        return reg.model_dump() if reg else {}

    @property
    def controls_draw(self) -> dict:
        """Шим для UpdateImage thread — читает DrawRegisters."""
        reg = self._rm.get_register("draw")
        return reg.model_dump() if reg else {}

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setWindowTitle("Inspector")
        self.setMinimumSize(800, 600)
        self.setGeometry(100, 100, 1200, 800)

        self._header = HeaderWidget(window_manager=self._wm)
        self._image_panel = ImagePanelWidget(registers_manager=self._rm, parent=self)

        self._tab_widget = TabWidget()
        self._populate_tabs()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._image_panel)
        layout.addSpacing(3)
        layout.addWidget(self._tab_widget, stretch=1)
        self.setCentralWidget(central)

    def _populate_tabs(self) -> None:
        """Создаёт и добавляет виджеты-вкладки в TabWidget."""

        # ── Сорта (рецепты) ──────────────────────────────────────────
        self._sort_widget = SortWidget(
            sort_data=self._sort_data,
            default_number=2,
            params_provider=None,  # будет установлен через set_sort_controller
        )
        sort_container = QWidget()
        sort_layout = QVBoxLayout(sort_container)
        sort_layout.addWidget(self._sort_widget)

        self._reset_btn = QPushButton("Сбросить значения")
        self._reset_btn.setFixedSize(200, 50)
        sort_layout.addWidget(self._reset_btn)

        self._tab_widget.add_tab(sort_container, "Сорта", wrap_scroll=False)

        # ── Визуальная настройка ─────────────────────────────────────
        app_config = getattr(self._wm, "app_config", None)
        self._tab_widget.add_tab(
            VisualConfigWidget(window_manager=self._wm, app_config=app_config),
            "Визуальная настройка"
        )

        # ── Логирование ──────────────────────────────────────────────
        self._tab_widget.add_tab(
            LoggingWidget(
                window_manager=self._wm,
                logging_manager=self._lm,
            ),
            "Логирование"
        )

        # ── Hikvision ────────────────────────────────────────────────
        self._hikvision_widget = HikvisionWidget(
            window_manager=self._wm,
            camera_service=self._camera_service,
            registers_manager=self._rm,
            data_manager=self._dm,
        )
        self._tab_widget.add_tab(self._hikvision_widget, "Hikvision")

        # ── Регионы (PostProcessing) ─────────────────────────────────
        self._tab_widget.add_tab(
            PostProcessingWidget(
                window_manager=self._wm,
                registers_manager=self._rm,
                data_manager=self._dm,
            ),
            "Регионы"
        )

        # ── Обработка (Processing) ───────────────────────────────────
        self._tab_widget.add_tab(
            ProcessingWidget(
                window_manager=self._wm,
                registers_manager=self._rm,
                data_manager=self._dm,
            ),
            "Обработка"
        )

        # ── Форма (CircleWidget) ─────────────────────────────────────
        self._tab_widget.add_tab(
            CircleWidget(window_manager=self._wm),
            "Форма"
        )

    # ------------------------------------------------------------------
    # Подключение сигналов и настройка окна
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Подключаем сигналы от виджетов, если нужно (например, для обновления данных)
        if self._hikvision_widget and hasattr(self._hikvision_widget, "camera_message_thread"):
            thread = self._hikvision_widget.camera_message_thread
            if thread:
                thread.message_received.connect(self._on_camera_message)
        # Другие сигналы могут быть добавлены по необходимости

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

    # ------------------------------------------------------------------
    # Публичный API — вызывается из WindowManager / потоков
    # ------------------------------------------------------------------

    def update_data(self, frames: list) -> None:
        """Slot для UpdateImage.update_frame — отображает кадры."""
        if frames:
            self._image_panel.display_frames(frames)

    def update_access_level(self, level: int) -> None:
        """Распространить уровень доступа на все ConfigurableWidget в дереве."""
        self.current_access_level = level
        for child in self.findChildren(ConfigurableWidget):
            child.access_level = level

    def set_sort_controller(self, controller: SortController) -> None:
        """Устанавливает контроллер сортов (вызывается WindowManager)."""
        self._sort_controller = controller
        if self._sort_widget:
            self._sort_widget.set_params_provider(controller.get_all_params)
        if self._reset_btn:
            self._reset_btn.clicked.connect(controller.reset_count)

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

    def _on_camera_message(self, message: dict) -> None:
        """Обрабатывает сообщения от камеры (например, размер изображения)."""
        msg_type = message.get("type")
        if msg_type == "image_size" and self._perf_monitor:
            self._perf_monitor.update_image_size(
                message.get("width", 0),
                message.get("height", 0)
            )
        elif msg_type == "parameters_response" and self._perf_monitor:
            params = message.get("parameters", {})
            # Здесь должны быть реальные значения processing_time и total_time
            # Пока передаём только fps, остальное позже
            self._perf_monitor.update_metrics(
                fps=params.get("frame_rate", 0.0),
                proc_time=0.0,
                total_time=0.0
            )

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        event.accept()











# -*- coding: utf-8 -*-
"""
MainWindow — чистый компоновщик виджетов.

Ответственность:
  - Инжекция зависимостей (managers, services)
  - Сборка UI из автономных виджетов
  - Маршрутизация сигналов между виджетами
  - Проксирование команд к WindowManager (IPC)

Все виджеты самодостаточны:
  - ImagePanelWidget — отображение кадров + метрики производительности
  - SortContainer — рецепты, автосохранение, работа с регистрами
  - HikvisionWidget — камера, потоки, параметры SDK
  - Остальные вкладки — аналогично

Сигнальная шина:
  Widget A --сигнал--> MainWindow --сигнал--> Widget B
  или напрямую через RegistersManager (pub/sub)
"""

from typing import Any, Optional, List, Dict

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

# Компоненты
from App.Components.header import HeaderWidget
from App.Components.tab_widget import TabWidget

# Виджеты — все автономные
from App.Widget.ImagePanel.image_panel import ImagePanelWidget
from App.Widget.Sort_widjet.sort_container import SortContainer
from App.Widget.Hikvision_widjet.Hikvision import HikvisionWidget
from App.Widget.Logging_widget import LoggingWidget
from App.Widget.Post_processing_widjet.Post_processing import PostProcessingWidget
from App.Widget.Processing_widjet.Processing import ProcessingWidget
from App.Widget.Circle_widjet.Circle import CircleWidget
from App.Widget.Visual_config_widget import VisualConfigWidget


class MainWindow(QMainWindow):
    """
    Главное окно — чистый контейнер-compositor.
    
    Публичный API (вызывается WindowManager):
        update_frame(frame, metrics)  — новый кадр от UpdateImage thread
        update_access_level(level)    — смена уровня доступа
        close_programm()              — корректное завершение
    """
    
    # Сигналы для WindowManager (если нужна обратная связь)
    reset_count_requested = pyqtSignal()           # Кнопка "Сбросить значения"
    recipe_applied = pyqtSignal(str)               # Применён рецепт (для логирования)
    camera_command = pyqtSignal(dict)              # Команда камере (enum, open, etc)
    
    def __init__(
        self,
        window_manager: Optional[Any] = None,
        registers_manager: Optional[Any] = None,
        data_manager: Optional[Any] = None,
        logging_manager: Optional[Any] = None,
        camera_service: Optional[Any] = None,
        performance_monitor: Optional[Any] = None,
        app_config: Optional[Any] = None,
    ) -> None:
        super().__init__()
        
        # Инжектированные зависимости — только храним ссылки
        self._wm = window_manager
        self._rm = registers_manager
        self._dm = data_manager
        self._lm = logging_manager
        self._camera_service = camera_service
        self._perf_monitor = performance_monitor
        self._app_config = app_config
        
        # Состояние
        self._current_access_level: int = 0
        
        # Виджеты (создаются в _init_ui)
        self._header: Optional[HeaderWidget] = None
        self._image_panel: Optional[ImagePanelWidget] = None
        self._tab_widget: Optional[TabWidget] = None
        
        # Подвиджеты вкладок (для доступа к cleanup)
        self._sort_container: Optional[SortContainer] = None
        self._hikvision_widget: Optional[HikvisionWidget] = None
        
        self._init_ui()
        self._connect_inter_widget_signals()
        self._apply_window_settings()
        
    # ------------------------------------------------------------------
    # UI Construction — только создание и компоновка
    # ------------------------------------------------------------------
    
    def _init_ui(self) -> None:
        """Создать все виджеты и разместить в layout."""
        self.setWindowTitle("Inspector")
        self.setMinimumSize(800, 600)
        
        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 1. Шапка
        self._header = HeaderWidget(window_manager=self._wm)
        layout.addWidget(self._header)
        
        # 2. Панель изображений (с метриками производительности)
        self._image_panel = ImagePanelWidget(
            registers_manager=self._rm,
            performance_monitor=self._perf_monitor,
            parent=self
        )
        layout.addWidget(self._image_panel, stretch=1)
        
        layout.addSpacing(3)
        
        # 3. Вкладки
        self._tab_widget = self._build_tabs()
        layout.addWidget(self._tab_widget)
        
    def _build_tabs(self) -> TabWidget:
        """Создать TabWidget со всеми вкладками."""
        tabs = TabWidget()
        
        # ── Сорта (рецепты) ──────────────────────────────────────────
        # Полностью автономный контейнер со своим контроллером
        self._sort_container = SortContainer(
            registers_manager=self._rm,
            data_manager=self._dm,
            parent=self
        )
        tabs.add_tab(self._sort_container, "Сорта", wrap_scroll=False)
        
        # ── Визуальная настройка ─────────────────────────────────────
        tabs.add_tab(
            VisualConfigWidget(
                window_manager=self._wm,
                app_config=self._app_config
            ),
            "Визуальная настройка"
        )
        
        # ── Логирование ──────────────────────────────────────────────
        tabs.add_tab(
            LoggingWidget(
                window_manager=self._wm,
                logging_manager=self._lm,
            ),
            "Логирование"
        )
        
        # ── Hikvision (камера) ───────────────────────────────────────
        # Полностью автономный — свой поток, своя логика
        self._hikvision_widget = HikvisionWidget(
            camera_service=self._camera_service,
            registers_manager=self._rm,
            data_manager=self._dm,
            window_manager=self._wm,  # только для queue_manager, если нужно
        )
        tabs.add_tab(self._hikvision_widget, "Hikvision")
        
        # ── Регионы (пост-обработка) ─────────────────────────────────
        tabs.add_tab(
            PostProcessingWidget(
                registers_manager=self._rm,
                data_manager=self._dm,
            ),
            "Регионы"
        )
        
        # ── Обработка ────────────────────────────────────────────────
        tabs.add_tab(
            ProcessingWidget(
                registers_manager=self._rm,
                data_manager=self._dm,
            ),
            "Обработка"
        )
        
        # ── Форма (Circle) ───────────────────────────────────────────
        tabs.add_tab(
            CircleWidget(window_manager=self._wm),
            "Форма"
        )
        
        return tabs
        
    # ------------------------------------------------------------------
    # Signal Routing — соединяем виджеты друг с другом
    # ------------------------------------------------------------------
    
    def _connect_inter_widget_signals(self) -> None:
        """
        Маршрутизация сигналов между виджетами.
        MainWindow выступает как "шина" — знает топологию, но не логику.
        """
        # Hikvision → ImagePanel: размер изображения для метрик
        self._hikvision_widget.image_size_detected.connect(
            self._image_panel.set_image_size
        )
        
        # Hikvision → ImagePanel: FPS от SDK (для отображения)
        self._hikvision_widget.fps_updated.connect(
            self._image_panel.update_fps_metrics
        )
        
        # SortContainer → MainWindow → WindowManager (reset_count)
        self._sort_container.reset_requested.connect(
            self._on_reset_count_requested
        )
        
        # SortContainer → логирование
        self._sort_container.recipe_applied.connect(
            self.recipe_applied.emit  # прокси наружу
        )
        
        # Hikvision → логирование/обработка
        self._hikvision_widget.camera_error.connect(
            self._on_camera_error
        )
        
        # ImagePanel → наружу (если нужно)
        self._image_panel.frame_clicked.connect(
            self._on_frame_clicked
        )
        
    # ------------------------------------------------------------------
    # Window Settings
    # ------------------------------------------------------------------
    
    def _apply_window_settings(self) -> None:
        """Применить настройки окна (fullscreen, размер, позиция)."""
        if not getattr(self._wm, 'fullscreen', False):
            self.showNormal()
            self.setGeometry(100, 100, 1200, 800)
            return
            
        # Fullscreen mode
        if self._app_config and self._app_config.get_limit_fullhd():
            w = self._app_config.get_fullscreen_limit_width()
            h = self._app_config.get_fullscreen_limit_height()
            self.setFixedSize(w, h)
            screen = self.screen().availableGeometry()
            self.move((screen.width() - w) // 2, (screen.height() - h) // 2)
        else:
            self.showFullScreen()
            
    # ------------------------------------------------------------------
    # Public API — вызывается WindowManager / потоками
    # ------------------------------------------------------------------
    
    def update_frame(
        self, 
        frame: Any,  # np.ndarray
        metrics: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Slot для UpdateImage thread.
        
        Args:
            frame: Кадр от камеры (numpy array)
            metrics: Опциональные метрики {'fps': 30.0, 'proc_time': 5.2, 'total_time': 10.5}
        """
        self._image_panel.display_frame(frame, metrics)
        
    def update_access_level(self, level: int) -> None:
        """
        Распространить уровень доступа на все виджеты.
        Вызывается WindowManager после входа администратора.
        """
        self._current_access_level = level
        
        # Рекурсивно находим все ConfigurableWidget
        from App.Core.base_configurable_widget import ConfigurableWidget
        for child in self.findChildren(ConfigurableWidget):
            child.access_level = level
            
    def close_programm(self) -> None:
        """Корректное завершение: cleanup всех виджетов."""
        # Останавливаем потоки и сохраняем состояние
        if self._hikvision_widget:
            self._hikvision_widget.cleanup()
            
        if self._sort_container:
            self._sort_container.cleanup()
            
        # Сигнал наружу
        if self._wm and hasattr(self._wm, 'stop_event'):
            self._wm.stop_event.set()
            
        self.close()
        
    # ------------------------------------------------------------------
    # Private Slots — обработчики сигналов виджетов
    # ------------------------------------------------------------------
    
    def _on_reset_count_requested(self) -> None:
        """Кнопка 'Сбросить значения' в SortContainer."""
        # Прокси в WindowManager для IPC
        if self._wm and hasattr(self._wm, 'send_reset_count'):
            self._wm.send_reset_count()
        self.reset_count_requested.emit()
        
    def _on_camera_error(self, error_msg: str) -> None:
        """Ошибка от HikvisionWidget — можно показать в статус-баре или логе."""
        if self._lm:
            self._lm.log_error(f"Camera: {error_msg}")
            
    def _on_frame_clicked(self, pos: tuple) -> None:
        """Клик по изображению — например, выбор точки для калибровки."""
        # Прокси наружу или обработка здесь
        pass
        
    # ------------------------------------------------------------------
    # Properties для обратной совместимости (убрать позже)
    # ------------------------------------------------------------------
    
    @property
    def header(self):
        """Доступ к HeaderWidget (используется WindowManager)."""
        return self._header
        
    # ------------------------------------------------------------------
    # Qt Overrides
    # ------------------------------------------------------------------
    
    def closeEvent(self, event) -> None:
        """Пользователь закрыл окно — корректный shutdown."""
        self.close_programm()
        event.accept()