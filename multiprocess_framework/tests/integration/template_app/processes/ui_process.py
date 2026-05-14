"""
UI Process - процесс пользовательского интерфейса (PyQt).

Демонстрирует использование ProcessModule для UI процесса.
Это заготовка для будущего PyQt приложения.
"""

from typing import Dict, Any
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import Message


class UIProcess(ProcessModule):
    """
    Процесс пользовательского интерфейса (PyQt).

    Демонстрирует:
    - Использование ProcessModule для UI процесса
    - Получение данных от других процессов
    - Отправку команд другим процессам

    Примечание: Это заготовка. Для полной реализации нужно:
    1. Установить PyQt6: pip install PyQt6
    2. Создать QApplication и главное окно
    3. Интегрировать с RouterManager для получения сообщений
    """

    def __init__(self, name: str, shared_resources=None, config: dict = None):
        """Инициализация UI Process."""
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.app = None
        self.main_window = None
        self.ui_enabled = config.get("ui_enabled", False) if config else False

    def initialize(self) -> bool:
        """Инициализация процесса."""
        if not super().initialize():
            return False

        # Инициализируем UI только если включен
        if self.ui_enabled:
            self._init_ui()
        else:
            self.log_info("UI Process initialized (UI disabled)", module=self.name)
            # Запускаем поток для обработки сообщений даже без UI
            self._start_message_processor()

        # Регистрируем обработчики команд
        self._register_command_handlers()

        return True

    def _init_ui(self):
        """
        Инициализация PyQt приложения.

        Примечание: Для полной реализации нужно:
        1. Создать QApplication
        2. Создать главное окно
        3. Настроить сигналы/слоты для получения сообщений
        """
        try:
            # Попытка импорта PyQt6
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QTimer

            # Создаем QApplication (если еще не создан)
            import sys

            if not QApplication.instance():
                self.app = QApplication(sys.argv)
            else:
                self.app = QApplication.instance()

            # Здесь можно создать главное окно
            # self.main_window = MainWindow(self)
            # self.main_window.show()

            # Запускаем обработчик сообщений через QTimer
            self.timer = QTimer()
            self.timer.timeout.connect(self._process_messages)
            self.timer.start(100)  # Обновление каждые 100ms

            self.log_info("PyQt UI initialized", module=self.name)

        except ImportError:
            self.log_warning(
                "PyQt6 not installed. UI will run in headless mode. Install with: pip install PyQt6", module=self.name
            )
            self.ui_enabled = False
            self._start_message_processor()

    def _start_message_processor(self):
        """Запуск потока для обработки сообщений (для headless режима)."""
        import time
        from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority

        def message_processor(stop_event, pause_event):
            """Поток обработки сообщений."""
            self.log_info("Message processor started", module=self.name)

            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue

                messages = self.receive(timeout=0.1)
                for message in messages:
                    self._handle_message(message)

                time.sleep(0.01)

            self.log_info("Message processor stopped", module=self.name)

        thread_config = ThreadConfig(name="ui_message_processor", priority=ThreadPriority.NORMAL, daemon=False)

        self.worker_manager.create_worker(name="ui_message_processor", target=message_processor, config=thread_config)

    def _process_messages(self):
        """Обработка сообщений (для PyQt режима)."""
        messages = self.receive(timeout=0.0)
        for message in messages:
            self._handle_message(message)

    def _handle_message(self, message):
        """
        Обработка входящего сообщения.

        Args:
            message: Входящее сообщение
        """
        if isinstance(message, dict):
            msg = Message.from_dict(message)
        else:
            msg = message

        # Обрабатываем разные типы сообщений
        if msg.type == "data":
            # Обновляем UI с данными
            self._update_ui_with_data(msg.data)
        elif msg.type == "log":
            # Отображаем логи в UI
            self._display_log(msg.data)
        elif msg.type == "system":
            # Обрабатываем системные сообщения
            self._handle_system_message(msg.data)

    def _update_ui_with_data(self, data: Dict[str, Any]):
        """Обновление UI с данными."""
        # Здесь можно обновить виджеты PyQt
        self.log_debug(f"Updating UI with data: {data.get('type', 'unknown')}", module=self.name)

    def _display_log(self, data: Dict[str, Any]):
        """Отображение лога в UI."""
        level = data.get("level", "INFO")
        message = data.get("message", "")
        self.log_debug(f"UI Log [{level}]: {message}", module=self.name)

    def _handle_system_message(self, data: Dict[str, Any]):
        """Обработка системного сообщения."""
        action = data.get("action", "")
        self.log_info(f"System message: {action}", module=self.name)

    def send_command(self, target: str, command: str, data: Dict[str, Any] = None):
        """
        Отправка команды другому процессу.

        Args:
            target: Целевой процесс
            command: Команда
            data: Данные команды
        """
        command_message = Message.create(
            type="command", sender=self.name, targets=[target], data={"command": command, "data": data or {}}
        )

        self.send(command_message)

    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""

        def handle_refresh_ui(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды обновления UI."""
            # Здесь можно обновить UI
            return {"status": "success", "message": "UI refreshed"}

        if self.command_manager:
            self.command_manager.register_command("refresh_ui", handle_refresh_ui, description="Refresh UI")

    def run_ui(self):
        """Запуск UI приложения (для PyQt)."""
        if self.app and self.ui_enabled:
            self.app.exec()

    def shutdown(self) -> bool:
        """Завершение процесса."""
        if self.timer:
            self.timer.stop()

        if self.app:
            self.app.quit()

        self.log_info("UI Process shutting down", module=self.name)
        return super().shutdown()
