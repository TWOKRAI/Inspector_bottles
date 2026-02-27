"""
AI Process - процесс машинного обучения и анализа.

Демонстрирует использование ProcessModule с AI логикой.
"""

import time
from typing import Dict, Any
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import WorkerManager, ThreadConfig, ThreadPriority
from multiprocess_framework.refactored.modules.message_module import Message


class AIProcess(ProcessModule):
    """
    Процесс машинного обучения и анализа.
    
    Демонстрирует:
    - Использование ProcessModule для AI логики
    - Обработку данных от Vision Process
    - Отправку результатов в DB Process
    """
    
    def __init__(
        self,
        name: str,
        shared_resources=None,
        config: dict = None
    ):
        """Инициализация AI Process."""
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.workers_count = config.get('workers_count', 1) if config else 1
        self.model_loaded = False
    
    def initialize(self) -> bool:
        """Инициализация процесса."""
        if not super().initialize():
            return False
        
        # Загружаем модель (симуляция)
        self._load_model()
        
        # Создаем воркеры для анализа
        self._create_ai_workers()
        
        # Регистрируем обработчики команд
        self._register_command_handlers()
        
        self.log_info("AI Process initialized", module=self.name)
        return True
    
    def _load_model(self):
        """Загрузка модели машинного обучения (симуляция)."""
        self.log_info("Loading AI model...", module=self.name)
        time.sleep(0.1)  # Симуляция загрузки
        self.model_loaded = True
        self.log_info("AI model loaded", module=self.name)
    
    def _create_ai_workers(self):
        """Создание воркеров для анализа."""
        for i in range(self.workers_count):
            worker_name = f"ai_worker_{i}"
            
            def worker_func(stop_event, pause_event, worker_id=i):
                """Функция воркера для анализа данных."""
                self.log_info(f"AI worker {worker_id} started", module=self.name)
                
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
                        
                        # Обрабатываем обработанные изображения от Vision Process
                        if msg.type == 'data' and msg.data.get('type') == 'processed_image':
                            self._analyze_image(msg, worker_id)
                    
                    time.sleep(0.01)
                
                self.log_info(f"AI worker {worker_id} stopped", module=self.name)
            
            thread_config = ThreadConfig(
                name=worker_name,
                priority=ThreadPriority.NORMAL,
                daemon=False
            )
            
            self.worker_manager.create_worker(
                name=worker_name,
                target=worker_func,
                config=thread_config
            )
    
    def _analyze_image(self, message: Message, worker_id: int):
        """
        Анализ изображения с помощью AI.
        
        Args:
            message: Сообщение с обработанным изображением
            worker_id: ID воркера
        """
        image_data = message.data.get('image_data')
        if not image_data:
            return
        
        # Симуляция анализа изображения
        self.log_debug(f"Worker {worker_id} analyzing image", module=self.name)
        time.sleep(0.05)  # Симуляция работы AI
        
        # Результаты анализа
        analysis_result = {
            'type': 'analysis_result',
            'image_id': message.data.get('image_id', 'unknown'),
            'defects': [],  # Список найденных дефектов
            'confidence': 0.95,
            'worker_id': worker_id,
            'timestamp': time.time()
        }
        
        # Отправляем результат в DB Process
        result_message = Message.create(
            type='data',
            sender=self.name,
            targets=['db_process'],
            data=analysis_result
        )
        
        self.send(result_message)
    
    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        def handle_reload_model(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды перезагрузки модели."""
            self._load_model()
            return {'status': 'success', 'message': 'Model reloaded'}
        
        if self.command_manager:
            self.command_manager.register_command(
                'reload_model',
                handle_reload_model,
                description='Reload AI model'
            )
    
    def shutdown(self) -> bool:
        """Завершение процесса."""
        self.log_info("AI Process shutting down", module=self.name)
        return super().shutdown()

