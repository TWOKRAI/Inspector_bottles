from process_module import ProcessModule
from message_router import UniversalRouterManager, DeliveryStatus
from worker_manager import ThreadConfig, ThreadPriority
from queue_registey import QueueRegistry
import time
import queue
from typing import Dict, List

class RouterProcess(ProcessModule):
    """
    Специализированный процесс для маршрутизации сообщений.
    Работает как центральный хаб для всех сообщений между процессами.
    """
    
    def __init__(self, name: str, process_manager=None, config: dict = None):
        super().__init__(name, process_manager, config)
        
        # Заменяем внутренний роутер на внешний с оптимизациями
        router_config = {
            'batch_size': 50,
            'batch_timeout': 0.1,
            'max_queue_size': 10000,
            'enable_broadcast': True,
            'enable_groups': True
        }
        self.router = UniversalRouterManager(name, router_config)
        self.managers['router'] = self.router
        
        # Группы процессов для групповой маршрутизации
        self.process_groups: Dict[str, List[str]] = {}
        
        # Статистика маршрутизации
        self.routing_stats = {
            'total_messages': 0,
            'successful_routes': 0,
            'failed_routes': 0,
            'broadcast_messages': 0,
            'group_messages': 0,
            'queues_registered': 0
        }
        
        print(f"🔄 Router Process {name} initialized")
    
    def _init_application_threads(self):
        """Инициализация потоков приложения для роутера"""
        # Основной поток обработки сообщений (высокий приоритет)
        self.worker_manager.create_worker(
            "message_router",
            self._message_routing_loop,
            ThreadConfig(priority=ThreadPriority.REALTIME),
            auto_start=True
        )
        
        # Поток для статистики и мониторинга
        self.worker_manager.create_worker(
            "stats_monitor",
            self._stats_monitoring_loop,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True
        )
        
        # Поток для очистки и обслуживания
        self.worker_manager.create_worker(
            "maintenance",
            self._maintenance_loop,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True
        )
    
    def _message_routing_loop(self, stop_event, pause_event):
        """Основной цикл маршрутизации сообщений"""
        batch = []
        batch_start_time = time.time()
        
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            try:
                # Получаем сообщение из системной очереди
                message_data = self.queues['system'].get_nowait()
                batch.append(message_data)
                self.routing_stats['total_messages'] += 1
                
                # Проверяем условия для обработки батча
                current_time = time.time()
                batch_size = len(batch)
                batch_age = current_time - batch_start_time
                
                batch_ready = (
                    batch_size >= 10 or  # По размеру
                    batch_age >= 0.05 or  # По времени
                    batch_size > 0 and self.queues['system'].empty()  # Если очередь пуста
                )
                
                if batch_ready and batch:
                    self._process_message_batch(batch)
                    batch = []
                    batch_start_time = current_time
                    
            except queue.Empty:
                # Обрабатываем оставшиеся сообщения в батче
                if batch:
                    self._process_message_batch(batch)
                    batch = []
                    batch_start_time = time.time()
                time.sleep(0.001)  # Короткая пауза при пустой очереди
                
            except Exception as e:
                self.log("ERROR", f"Routing loop error: {e}", "router")
                time.sleep(0.01)
    
    def _process_message_batch(self, batch: List[Dict]):
        """Обработка батча сообщений"""
        successful_routes = 0
        
        for message_data in batch:
            try:
                if isinstance(message_data, dict):
                    result = self.router.route_message(message_data)
                    if result.get('status') == DeliveryStatus.DELIVERED:
                        successful_routes += 1
                else:
                    # Пытаемся преобразовать в dict
                    try:
                        if hasattr(message_data, 'to_dict'):
                            message_dict = message_data.to_dict()
                        else:
                            message_dict = dict(message_data)
                        result = self.router.route_message(message_dict)
                        if result.get('status') == DeliveryStatus.DELIVERED:
                            successful_routes += 1
                    except Exception as e:
                        self.log("ERROR", f"Failed to convert message: {e}", "router")
            except Exception as e:
                self.log("ERROR", f"Failed to process message in batch: {e}", "router")
        
        # Обновляем статистику
        self.routing_stats['successful_routes'] += successful_routes
        self.routing_stats['failed_routes'] += (len(batch) - successful_routes)
    
    def _stats_monitoring_loop(self, stop_event, pause_event):
        """Цикл мониторинга статистики"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            # Логируем статистику каждые 30 секунд
            self.log("INFO", f"Router stats: {self.get_detailed_stats()}", "router")
            time.sleep(30)
    
    def _maintenance_loop(self, stop_event, pause_event):
        """Цикл обслуживания (очистка, проверка здоровья)"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            # Очистка устаревших данных каждые 60 секунд
            self._cleanup_old_data()
            time.sleep(60)
    
    def _cleanup_old_data(self):
        """Очистка устаревших данных"""
        # Здесь можно добавить логику очистки кешей, устаревших сообщений и т.д.
        pass
    
    def register_process(self, process_name: str, queues: Dict):
        """Регистрация процесса в роутере"""
        try:
            # Регистрируем очереди процесса в QueueRegistry
            if self.process_manager:
                success = self.process_manager.queue_registry.register_process_queues(process_name, queues)
                if success:
                    self.routing_stats['queues_registered'] += 1
                    self.log("INFO", f"Registered process: {process_name}", "router")
                    return True
            return False
        except Exception as e:
            self.log("ERROR", f"Failed to register process {process_name}: {e}", "router")
            return False
    
    def create_group(self, group_name: str, processes: List[str]):
        """Создание группы процессов для групповой маршрутизации"""
        self.process_groups[group_name] = processes
        self.log("INFO", f"Created group '{group_name}': {processes}", "router")
    
    def add_to_group(self, group_name: str, process_name: str):
        """Добавление процесса в группу"""
        if group_name not in self.process_groups:
            self.process_groups[group_name] = []
        
        if process_name not in self.process_groups[group_name]:
            self.process_groups[group_name].append(process_name)
            self.log("INFO", f"Added {process_name} to group '{group_name}'", "router")
    
    def route_to_group(self, message: Dict, group_name: str) -> Dict:
        """Маршрутизация сообщения в группу процессов"""
        if group_name not in self.process_groups:
            return {
                'status': DeliveryStatus.FAILED,
                'error': f"Group '{group_name}' not found",
                'message_id': message.get('id', 'unknown')
            }
        
        group_members = self.process_groups[group_name]
        message['targets'] = group_members
        self.routing_stats['group_messages'] += 1
        
        return self.router.route_message(message)
    
    def broadcast_message(self, message: Dict, exclude_sender: bool = True) -> Dict:
        """Широковещательная рассылка сообщения всем процессам"""
        if self.process_manager:
            all_processes = self.process_manager.queue_registry.get_registered_processes()
            if exclude_sender and 'sender' in message:
                all_processes = [p for p in all_processes if p != message['sender']]
            
            message['targets'] = all_processes
            self.routing_stats['broadcast_messages'] += 1
            
            return self.router.route_message(message)
        else:
            return {
                'status': DeliveryStatus.FAILED,
                'error': "Process manager not available",
                'message_id': message.get('id', 'unknown')
            }
    
    def get_detailed_stats(self) -> Dict:
        """Получение детальной статистики роутера"""
        router_stats = self.router.get_stats()
        return {
            **self.routing_stats,
            'router_stats': router_stats,
            'process_groups': list(self.process_groups.keys()),
            'registered_processes': len(self.process_manager.queue_registry.get_registered_processes()) if self.process_manager else 0
        }
    
    def start_routing(self):
        """Запуск маршрутизации"""
        self.log("INFO", "Starting message routing...", "router")
        self.run()
    
    def stop_routing(self):
        """Остановка маршрутизации"""
        self.log("INFO", "Stopping message routing...", "router")
        self.stop()