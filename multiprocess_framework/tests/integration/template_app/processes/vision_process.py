"""
Vision Process - процесс обработки изображений.

Демонстрирует использование ProcessModule с WorkerManager для обработки данных.
"""

import time
from typing import Dict, Any

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ThreadConfig, ThreadPriority
from multiprocess_framework.modules.message_module import Message


class VisionProcess(ProcessModule):
    """
    Процесс обработки изображений.

    Демонстрирует:
    - Использование ProcessModule как базового класса
    - Создание воркеров через WorkerManager
    - Обработку сообщений через RouterManager
    - Использование конфигурации
    """

    def __init__(self, name: str, shared_resources=None, config: dict = None):
        """
        Инициализация Vision Process.

        Args:
            name: Имя процесса
            shared_resources: SharedResourcesManager
            config: Конфигурация процесса
        """
        super().__init__(name=name, shared_resources=shared_resources, config=config)

        # Специфичные для Vision Process настройки
        self.workers_count = config.get("workers_count", 2) if config else 2
        self.processing_enabled = True

    def initialize(self) -> bool:
        """Инициализация процесса."""
        if not super().initialize():
            return False

        # Создаем воркеры для обработки изображений
        self._create_vision_workers()

        # Регистрируем обработчики команд
        self._register_command_handlers()

        self.log_info("Vision Process initialized", module=self.name)
        return True

    def _create_vision_workers(self):
        """Создание воркеров для обработки изображений."""
        for i in range(self.workers_count):
            worker_name = f"vision_worker_{i}"

            def worker_func(stop_event, pause_event, worker_id=i):
                """Функция воркера для обработки изображений."""
                self.log_info(f"Vision worker {worker_id} started", module=self.name)

                while not stop_event.is_set():
                    if pause_event.is_set():
                        time.sleep(0.1)
                        continue

                    # Получаем сообщения из очереди процесса
                    messages = self.receive(timeout=0.1)

                    for message in messages:
                        if isinstance(message, dict):
                            msg = Message.from_dict(message)
                        else:
                            msg = message

                        # Обрабатываем сообщения типа 'data' с изображениями
                        if msg.type == "data" and msg.data.get("type") == "image":
                            self._process_image(msg, worker_id)

                    time.sleep(0.01)  # Небольшая задержка для CPU

                self.log_info(f"Vision worker {worker_id} stopped", module=self.name)

            # Создаем конфигурацию потока
            thread_config = ThreadConfig(name=worker_name, priority=ThreadPriority.NORMAL, daemon=False)

            # Регистрируем воркер
            self.worker_manager.create_worker(name=worker_name, target=worker_func, config=thread_config)

    def _process_image(self, message: Message, worker_id: int):
        """
        Обработка изображения.

        Args:
            message: Сообщение с изображением
            worker_id: ID воркера
        """
        image_data = message.data.get("image_data")
        if not image_data:
            return

        # Симуляция обработки изображения
        self.log_debug(f"Worker {worker_id} processing image", module=self.name)

        # Отправляем результат в AI процесс
        result_message = Message.create(
            type="data",
            sender=self.name,
            targets=["ai_process"],
            data={
                "type": "processed_image",
                "image_data": image_data,
                "worker_id": worker_id,
                "timestamp": time.time(),
            },
        )

        self.send(result_message)

    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""

        def handle_start_processing(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды начала обработки."""
            self.processing_enabled = True
            self.log_info("Processing enabled", module=self.name)
            return {"status": "success", "message": "Processing enabled"}

        def handle_stop_processing(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды остановки обработки."""
            self.processing_enabled = False
            self.log_info("Processing disabled", module=self.name)
            return {"status": "success", "message": "Processing disabled"}

        # Регистрируем команды через CommandManager
        if self.command_manager:
            self.command_manager.register_command(
                "start_processing", handle_start_processing, description="Start image processing"
            )
            self.command_manager.register_command(
                "stop_processing", handle_stop_processing, description="Stop image processing"
            )

    def shutdown(self) -> bool:
        """Завершение процесса."""
        self.log_info("Vision Process shutting down", module=self.name)
        return super().shutdown()
