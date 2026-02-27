"""
DB Process - процесс работы с базой данных.

Демонстрирует использование ProcessModule для работы с данными.
"""

import time
from typing import Dict, Any, List
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import Message


class DBProcess(ProcessModule):
    """
    Процесс работы с базой данных.
    
    Демонстрирует:
    - Использование ProcessModule для работы с БД
    - Сохранение результатов анализа
    - Работу с конфигурацией через ConfigManager
    """
    
    def __init__(
        self,
        name: str,
        shared_resources=None,
        config: dict = None
    ):
        """Инициализация DB Process."""
        super().__init__(name=name, shared_resources=shared_resources, config=config)
        self.db_connected = False
        self.saved_records: List[Dict[str, Any]] = []
    
    def initialize(self) -> bool:
        """Инициализация процесса."""
        if not super().initialize():
            return False
        
        # Подключаемся к БД (симуляция)
        self._connect_db()
        
        # Регистрируем обработчики команд
        self._register_command_handlers()
        
        # Запускаем поток для обработки данных
        self._start_data_processor()
        
        self.log_info("DB Process initialized", module=self.name)
        return True
    
    def _connect_db(self):
        """Подключение к базе данных (симуляция)."""
        self.log_info("Connecting to database...", module=self.name)
        time.sleep(0.1)  # Симуляция подключения
        self.db_connected = True
        self.log_info("Database connected", module=self.name)
    
    def _start_data_processor(self):
        """Запуск потока для обработки данных."""
        def data_processor(stop_event, pause_event):
            """Поток обработки данных из очереди."""
            self.log_info("Data processor started", module=self.name)
            
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
                    
                    # Обрабатываем результаты анализа от AI Process
                    if msg.type == 'data' and msg.data.get('type') == 'analysis_result':
                        self._save_analysis_result(msg.data)
                
                time.sleep(0.01)
            
            self.log_info("Data processor stopped", module=self.name)
        
        # Создаем воркер для обработки данных
        from multiprocess_framework.refactored.modules.worker_module import ThreadConfig, ThreadPriority
        
        thread_config = ThreadConfig(
            name='db_data_processor',
            priority=ThreadPriority.NORMAL,
            daemon=False
        )
        
        self.worker_manager.create_worker(
            name='db_data_processor',
            target=data_processor,
            config=thread_config
        )
    
    def _save_analysis_result(self, data: Dict[str, Any]):
        """
        Сохранение результата анализа в БД.
        
        Args:
            data: Данные результата анализа
        """
        # Симуляция сохранения в БД
        record = {
            'id': len(self.saved_records) + 1,
            'image_id': data.get('image_id', 'unknown'),
            'defects': data.get('defects', []),
            'confidence': data.get('confidence', 0.0),
            'timestamp': data.get('timestamp', time.time())
        }
        
        self.saved_records.append(record)
        self.log_debug(f"Saved analysis result: {record['id']}", module=self.name)
        
        # Можно использовать ConfigManager для сохранения настроек
        if self.config_manager:
            # Сохраняем статистику в конфигурацию
            stats = self.config_manager.get('db_stats', {})
            stats['total_records'] = len(self.saved_records)
            stats['last_save_time'] = time.time()
            self.config_manager.set('db_stats', stats)
    
    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        def handle_get_stats(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды получения статистики."""
            return {
                'status': 'success',
                'stats': {
                    'total_records': len(self.saved_records),
                    'db_connected': self.db_connected
                }
            }
        
        def handle_get_records(command_data: Dict[str, Any]) -> Dict[str, Any]:
            """Обработчик команды получения записей."""
            limit = command_data.get('limit', 10)
            return {
                'status': 'success',
                'records': self.saved_records[-limit:]
            }
        
        if self.command_manager:
            self.command_manager.register_command(
                'get_stats',
                handle_get_stats,
                description='Get database statistics'
            )
            self.command_manager.register_command(
                'get_records',
                handle_get_records,
                description='Get recent records'
            )
    
    def shutdown(self) -> bool:
        """Завершение процесса."""
        self.log_info("DB Process shutting down", module=self.name)
        return super().shutdown()

