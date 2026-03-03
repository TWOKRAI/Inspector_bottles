# -*- coding: utf-8 -*-
"""
Менеджер окон приложения App Inspector.

Ответственность:
  - Жизненный цикл всех окон (создание, показ, скрытие, закрытие)
  - Владение RouterManager и QueueChannel — единственное место где живут IPC-каналы
  - Предоставление общего API send_register_update() для всех окон и виджетов
  - Управление уровнем доступа и полноэкранным режимом

Иерархия:
  WindowManager
    ├── RouterManager (router_module) — IPC с бэкендом
    │     └── QueueChannel × N       — обёртки над multiprocessing.Queue
    ├── MainWindow   ─┐
    ├── LoadingWindow  ├── окна-контейнеры (только UI)
    └── NeurounWindow ─┘
"""
import sys
from typing import Any, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QCursor
import qdarkstyle

from App.Windows.main_window import MainWindow
from App.Windows.window_loading import LoadingWindow
from App.Windows.neuroun_window import NeurounWindow
from App.Windows.message_window import MessageWindow

from App.Components.header import HeaderWidget
from App.Core.app_config import AppConfigManager
from App.Core.Threads.thread_loading import Loading
from App.Core.Threads.thread_image_update import UpdateImage
from App.Core.Threads.thread_bot_message import BotThread

# Фреймворк: роутер + сообщения (мягкий fallback если модули не установлены)
try:
    from multiprocess_framework.refactored.modules.router_module import (
        RouterManager,
        QueueChannel,
    )
    from multiprocess_framework.refactored.modules.message_module import (
        Message,
        MessageType,
    )
    _ROUTER_AVAILABLE = True
except ImportError:
    RouterManager = None        # type: ignore[assignment,misc]
    QueueChannel = None         # type: ignore[assignment,misc]
    Message = None              # type: ignore[assignment,misc]
    MessageType = None          # type: ignore[assignment,misc]
    _ROUTER_AVAILABLE = False


class WindowManager:
    """
    Менеджер окон приложения.

    Единственный владелец RouterManager — все окна и виджеты
    вызывают self._wm.send_register_update(...) вместо прямой
    работы с очередями.
    """

    # IPC-каналы: атрибут queue_manager → имя канала в роутере
    _QUEUE_CHANNEL_MAP = [
        "control_draw",
        "control_camera",
        "control_conveyor",
        "control_neuroun",
        "control_robot",
        "control_processing",
        "control_post_processing",
        "control_frame_process",
        "control_overlay",
    ]

    def __init__(self, queue_manager, stop_event):
        self.queue_manager = queue_manager
        self.stop_event = stop_event

        self.app = QApplication(sys.argv)
        self.app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())

        self.loading_window = None
        self.main_window = None
        self.neuroun_window = None
        self.message_window = None
        self.header = None

        self.fullscreen = False
        self.access_level = 2

        self.app_config = AppConfigManager()

        # Инициализируем роутер до создания окон: окна могут запросить send_register_update
        self._router_manager: Optional[Any] = None
        self._setup_router()

        self.create_all_windows()
        self.create_thread()
        self.toggle_cursor_visibility(True)
        self.set_fullscreen(self.fullscreen)

        self.admin_function(self.access_level)

        # Сигнал готовности процесса App
        try:
            self.queue_manager.process_ready_queue.put('proc_app')
            print("App process ready signal sent")
        except Exception as e:
            print(f"Error sending ready signal: {e}")

    # ------------------------------------------------------------------
    # Роутер и IPC
    # ------------------------------------------------------------------

    def _setup_router(self) -> None:
        """Создать RouterManager и зарегистрировать все IPC-каналы.

        Вызывается один раз в __init__ до создания окон.
        Все окна и виджеты используют send_register_update() —
        никто не обращается к queue_manager напрямую для регистров.
        """
        if not _ROUTER_AVAILABLE:
            print("[WindowManager] router_module недоступен — IPC отключён")
            return
        if self.queue_manager is None:
            return

        self._router_manager = RouterManager("app_ui_router")
        self._router_manager.initialize()

        registered = []
        for attr in self._QUEUE_CHANNEL_MAP:
            queue = getattr(self.queue_manager, attr, None)
            if queue is not None:
                self._router_manager.register_channel(QueueChannel(attr, queue))
                registered.append(attr)

        print(f"[WindowManager] Роутер инициализирован, каналы: {registered}")

    def setup_register_observer(self, registers_manager) -> None:
        """Подписать глобальный observer: любое программное изменение регистра
        (загрузка рецепта, сброс) автоматически уходит в бэкенд через роутер.

        Вызывается из MainWindow после создания RegistersManager.
        """
        if not hasattr(registers_manager, "subscribe_all"):
            return

        def _on_register_changed(register_name: str, field_name: str, value: Any) -> None:
            self.send_register_update(register_name, field_name, value, registers_manager)

        registers_manager.subscribe_all(_on_register_changed)

    def send_register_update(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        registers_manager=None,
    ) -> None:
        """Единая точка отправки изменения регистра в бэкенд через RouterManager.

        Вызывается:
          - SliderControlEnhanced / CheckboxControlEnhanced при изменении значения
          - SortController после применения рецепта (через observer RegistersManager)
          - Любым виджетом через self._wm.send_register_update(...)

        Читает полный snapshot регистра чтобы бэкенд получил актуальное состояние.
        """
        if not self._router_manager:
            return
        if not _ROUTER_AVAILABLE:
            return

        snapshot: dict = {}
        if registers_manager is not None:
            reg_obj = registers_manager.get_register(register_name)
            snapshot = reg_obj.model_dump() if reg_obj else {field_name: value}
        else:
            snapshot = {field_name: value}

        channel = f"control_{register_name}"
        msg = (
            Message.create(MessageType.COMMAND, sender="app_ui")
            .set_channel(channel)
            .set_command(
                "set_register",
                args={
                    "register": register_name,
                    "field": field_name,
                    "value": value,
                    "snapshot": snapshot,
                },
            )
        )
        self._router_manager.send(msg)

    # ------------------------------------------------------------------
    # Создание окон и потоков
    # ------------------------------------------------------------------

    def create_all_windows(self):
        """Создание всех окон приложения"""
        self.header = HeaderWidget(window_manager=self)
        self.header.main_show.connect(self.show_main_winodw)
        self.header.neuroun_show.connect(self.show_neuroun_winodw)

        # Создаем главное окно сначала чтобы получить его размер
        self.main_window = MainWindow(window_manager=self)
        self.main_window.header.main_show.connect(self.show_main_winodw)
        self.main_window.header.neuroun_show.connect(self.show_neuroun_winodw)
        self.main_window.hide()
        
        # Создаем окно загрузки с таким же размером как главное окно
        self.loading_window = LoadingWindow(window_manager=self)
        # Устанавливаем размер окна загрузки равным размеру главного окна
        main_window_size = self.main_window.size()
        self.loading_window.resize(main_window_size)
        self.loading_window.setGeometry(self.main_window.geometry())

    def create_thread(self):
        """Создание рабочих потоков приложения"""
        if self.loading_window:
            self.worker_loading = Loading(self.queue_manager, self.stop_event)
            self.worker_loading.progress_updated.connect(self.loading_window.update_progress)
            self.worker_loading.window_close.connect(self.close_loading_winodw)
            self.worker_loading.window_close.connect(self.show_main_winodw)
            self.worker_loading.start()

        if self.main_window:
            self.worker_update_image = UpdateImage(window_manager=self)
            self.worker_update_image.update_frame.connect(self.main_window.update_data)
            self.worker_update_image.start()

        self.bot_thread = BotThread(window_manager=self)
        self.bot_thread.message.connect(self.show_message)
        self.bot_thread.start()

    def set_fullscreen(self, fullscreen):
        """Установка режима fullscreen для всех окон"""
        self.fullscreen = fullscreen
        
        # Получаем настройки ограничения из конфигурации приложения
        limit_fullhd = self.app_config.get_limit_fullhd() if self.app_config else False
        limit_width = self.app_config.get_fullscreen_limit_width() if self.app_config else 1920
        limit_height = self.app_config.get_fullscreen_limit_height() if self.app_config else 1080
        
        if self.main_window:
            if fullscreen:
                if limit_fullhd:
                    # Ограничиваем размер до заданного разрешения вместо fullscreen
                    self.main_window.showNormal()
                    self.main_window.setFixedSize(limit_width, limit_height)
                    # Центрируем окно на экране
                    screen = self.main_window.screen().availableGeometry()
                    x = (screen.width() - limit_width) // 2
                    y = (screen.height() - limit_height) // 2
                    self.main_window.move(x, y)
                else:
                    self.main_window.showFullScreen()
            else:
                # Снимаем ограничение размера при выключении fullscreen
                self.main_window.setFixedSize(16777215, 16777215)  # Убираем фиксированный размер (16777215 = QWIDGETSIZE_MAX)
                self.main_window.setMaximumSize(16777215, 16777215)  # Убираем максимальный размер
                self.main_window.setMinimumSize(800, 600)  # Восстанавливаем минимальный размер
                self.main_window.showNormal()

        if self.loading_window:
            if fullscreen:
                if limit_fullhd:
                    self.loading_window.showNormal()
                    self.loading_window.setFixedSize(limit_width, limit_height)
                    screen = self.loading_window.screen().availableGeometry()
                    x = (screen.width() - limit_width) // 2
                    y = (screen.height() - limit_height) // 2
                    self.loading_window.move(x, y)
                else:
                    self.loading_window.showFullScreen()
            else:
                self.loading_window.setFixedSize(16777215, 16777215)
                self.loading_window.setMaximumSize(16777215, 16777215)
                self.loading_window.setMinimumSize(800, 600)
                self.loading_window.showNormal()

        if self.neuroun_window:
            if fullscreen:
                if limit_fullhd:
                    self.neuroun_window.showNormal()
                    self.neuroun_window.setFixedSize(limit_width, limit_height)
                    screen = self.neuroun_window.screen().availableGeometry()
                    x = (screen.width() - limit_width) // 2
                    y = (screen.height() - limit_height) // 2
                    self.neuroun_window.move(x, y)
                else:
                    self.neuroun_window.showFullScreen()
            else:
                self.neuroun_window.setFixedSize(16777215, 16777215)
                self.neuroun_window.setMaximumSize(16777215, 16777215)
                self.neuroun_window.setMinimumSize(800, 600)
                self.neuroun_window.showNormal()

    def toggle_cursor_visibility(self, visible):
        """Переключает видимость курсора для всех окон"""
        cursor = QCursor(Qt.ArrowCursor) if visible else QCursor(Qt.BlankCursor)

        if self.main_window:
            self.main_window.setCursor(cursor)
        if self.loading_window:
            self.loading_window.setCursor(cursor)

    def change_language(self, language):
        """Реализация смены языка"""
        pass

    def admin_function(self, access_level):
        """Установка уровня доступа администратора"""
        self.access_level = access_level
        if self.main_window:
            self.main_window.update_access_level(access_level)

    def close_program(self):
        """Закрытие программы и всех окон"""
        if self.main_window:
            self.main_window.close()
           
        if self.loading_window:
            self.loading_window.close()

        if self.neuroun_window:
            self.neuroun_window.close()

        self.queue_manager.stop_event.set()
        self.queue_manager.memory_manager.close_all()

    def run(self):
        """Запуск главного цикла приложения"""
        self.loading_window.show()
        sys.exit(self.app.exec_())

    def show_message(self, message):
        """Показать сообщение пользователю"""
        if isinstance(self.message_window, MessageWindow):
            self.message_window.close()
            self.message_window.deleteLater()
            self.message_window = None

        if message[0] != '.':
            print(message)
            self.message_window = MessageWindow(self.queue_manager, message)
            self.message_window.show()

    def close_loading_winodw(self):
        """Закрытие окна загрузки"""
        if self.loading_window:
            self.loading_window.close()
            self.loading_window.deleteLater()
            self.loading_window = None

    def show_main_winodw(self):
        """Показать главное окно"""
        if not self.main_window:
            self.main_window = MainWindow(window_manager=self)
            self.main_window.show()
        else:
            self.main_window.show()
        
        self.close_neuroun_winodw()

        print('ПОказал окно майн')

    def close_main_winodw(self):
        """Закрыть главное окно"""
        if self.main_window:
            self.main_window.hide()    
    
    def show_neuroun_winodw(self):
        """Показать окно нейросети"""
        if not self.neuroun_window:
            self.neuroun_window = NeurounWindow(window_manager=self)
            self.neuroun_window.header.main_show.connect(self.show_main_winodw)
            self.neuroun_window.header.neuroun_show.connect(self.show_neuroun_winodw)
            self.neuroun_window.show()
        else:
            self.neuroun_window.show()
        
        self.close_main_winodw()

        print('ПОказал окно нейрон')

    def close_neuroun_winodw(self):
        """Закрыть окно нейросети"""
        if self.neuroun_window:
            self.neuroun_window.hide()
