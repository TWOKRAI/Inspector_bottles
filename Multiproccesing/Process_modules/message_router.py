import time
import logging
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
from collections import defaultdict

class RouterMode(Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"

class RoutingStrategy(Enum):
    UNICAST = "unicast"
    MULTICAST = "multicast" 
    GROUP = "group"
    BROADCAST = "broadcast"

class DeliveryStatus(Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    INVALID = "invalid"


from typing import Dict, Any

class PriorityManager:
    """Менеджер приоритетов сообщений"""
    
    def __init__(self):
        self.priority_levels = {
            'critical': 0,
            'high': 1,
            'normal': 2,
            'low': 3,
            'background': 4
        }
    
    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка приоритета сообщения"""
        priority = message.get('priority', 'normal')
        
        if isinstance(priority, str):
            priority_value = self.priority_levels.get(priority, 2)
        else:
            # Если priority число, нормализуем его к нашим уровням
            priority_value = max(0, min(4, int(priority)))
        
        message['_priority_value'] = priority_value
        return message
    
    def get_priority_name(self, priority_value: int) -> str:
        """Получение имени приоритета по значению"""
        for name, value in self.priority_levels.items():
            if value == priority_value:
                return name
        return 'normal'


import time
from typing import Dict, Any, Optional
from enum import Enum

class DeliveryManager:
    """Менеджер гарантий доставки"""
    
    def __init__(self):
        self.pending_messages: Dict[str, Dict] = {}
        self.delivery_timeout = 30.0  # секунд
    
    def track_message(self, message_id: str, message: Dict, send_function: Callable) -> bool:
        """Отслеживание сообщения с гарантией доставки"""
        if not message.get('need_ack'):
            return True
            
        self.pending_messages[message_id] = {
            'message': message,
            'send_function': send_function,
            'timestamp': time.time(),
            'status': 'pending'
        }
        return True
    
    def acknowledge_message(self, message_id: str) -> bool:
        """Подтверждение доставки сообщения"""
        if message_id in self.pending_messages:
            self.pending_messages[message_id]['status'] = 'acknowledged'
            return True
        return False
    
    def check_timeouts(self):
        """Проверка таймаутов доставки"""
        current_time = time.time()
        timed_out = []
        
        for msg_id, info in self.pending_messages.items():
            if (current_time - info['timestamp']) > self.delivery_timeout:
                timed_out.append(msg_id)
        
        for msg_id in timed_out:
            del self.pending_messages[msg_id]
    
    def get_pending_count(self) -> int:
        """Количество ожидающих подтверждения сообщений"""
        return len(self.pending_messages)


import time
from typing import Dict, List, Any
from collections import defaultdict

class UniversalBatcher:
    """Универсальный батчер для группировки сообщений"""
    
    def __init__(self):
        self.batches: Dict[str, List[Dict]] = defaultdict(list)
        self.batch_configs = {
            'default': {'max_size': 100, 'max_time': 1.0}
        }
    
    def add_message(self, message: Dict[str, Any], batch_key: str = None) -> bool:
        """Добавление сообщения в батч"""
        if batch_key is None:
            batch_key = self._generate_batch_key(message)
        
        self.batches[batch_key].append(message)
        
        # Проверяем, не пора ли отправить батч
        config = self.batch_configs.get('default')
        if (len(self.batches[batch_key]) >= config['max_size']):
            return self.flush_batch(batch_key)
        
        return True
    
    def flush_batch(self, batch_key: str) -> bool:
        """Отправка батча сообщений"""
        if batch_key not in self.batches or not self.batches[batch_key]:
            return False
        
        batch = self.batches[batch_key]
        # TODO: Реализовать отправку батча
        print(f"Flushing batch {batch_key} with {len(batch)} messages")
        
        # Очищаем батч после отправки
        self.batches[batch_key] = []
        return True
    
    def flush_all(self) -> bool:
        """Отправка всех батчей"""
        success = True
        for batch_key in list(self.batches.keys()):
            if not self.flush_batch(batch_key):
                success = False
        return success
    
    def _generate_batch_key(self, message: Dict) -> str:
        """Генерация ключа для группировки сообщений"""
        msg_type = message.get('type', 'unknown')
        priority = message.get('_priority_value', 2)
        return f"{msg_type}_p{priority}"

class UniversalRouterManager:
    """
    Универсальный менеджер маршрутизации сообщений
    """
    
    def __init__(self, router_id: str, config: Dict[str, Any] = None):
        self.router_id = router_id
        self.config = config or {}
        self.is_external = (router_id != "internal")
        
        # Регистрация методов отправки и обработки
        self.send_methods: Dict[str, Callable] = {}
        self.receive_handlers: Dict[str, Callable] = {}
        
        # Менеджеры
        self.batcher = UniversalBatcher()
        self.priority_manager = PriorityManager()
        self.delivery_manager = DeliveryManager()
        
        # Валидация сообщений
        self.required_fields = ['id', 'type', 'sender']
        
        # Логирование
        self.logger = logging.getLogger(f"Router_{router_id}")
        self.setup_logging()
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'messages_delivered': 0,
            'messages_failed': 0,
            'messages_invalid': 0
        }
    
    def setup_logging(self):
        """Настройка логирования (временная, потом интегрируем с LoggerManager)"""
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                f'%(asctime)s - Router_{self.router_id} - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def register_send_method(self, method_name: str, send_function: Callable) -> bool:
        """Регистрация метода отправки"""
        try:
            self.send_methods[method_name] = send_function
            self.logger.info(f"Registered send method: {method_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register send method {method_name}: {e}")
            return False
    
    def register_receive_handler(self, message_type: str, handler_function: Callable) -> bool:
        """Регистрация обработчика входящих сообщений"""
        try:
            self.receive_handlers[message_type] = handler_function
            self.logger.info(f"Registered receive handler for: {message_type}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register receive handler for {message_type}: {e}")
            return False
    
    def route_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Основной метод маршрутизации сообщения
        Возвращает статус доставки
        """
        self.stats['messages_processed'] += 1
        
        # 1. Валидация сообщения
        validation_result = self._validate_message(message)
        if not validation_result['valid']:
            self.stats['messages_invalid'] += 1
            self.logger.warning(f"Invalid message: {validation_result['error']}")
            return {
                'status': DeliveryStatus.INVALID,
                'error': validation_result['error'],
                'message_id': message.get('id', 'unknown')
            }
        
        # 2. Определение стратегии и роутеров
        strategy = self._determine_routing_strategy(message)
        target_routers = self._determine_routers(message)
        
        # 3. Проверка - обрабатываем ли мы это сообщение?
        if not self._should_handle_message(target_routers):
            self.logger.debug(f"Message not for this router: {message['id']}")
            return {
                'status': DeliveryStatus.PENDING,
                'message': "Message routed to other routers",
                'message_id': message['id']
            }
        
        # 4. Обработка приоритета
        prioritized_msg = self.priority_manager.process(message)
        
        # 5. Выполнение маршрутизации
        delivery_result = self._execute_routing(strategy, prioritized_msg)
        
        # 6. Обновление статистики
        if delivery_result['status'] == DeliveryStatus.DELIVERED:
            self.stats['messages_delivered'] += 1
        else:
            self.stats['messages_failed'] += 1
            
        return delivery_result
    
    def _validate_message(self, message: Dict) -> Dict[str, Any]:
        """Валидация структуры сообщения"""
        for field in self.required_fields:
            if field not in message:
                return {
                    'valid': False,
                    'error': f"Missing required field: {field}",
                    'missing_field': field
                }
        
        # Проверка типа targets
        targets = message.get('targets')
        if targets is None:
            return {
                'valid': False,
                'error': "Missing 'targets' field",
                'missing_field': 'targets'
            }
        
        # targets может быть: str, list[str], "all"
        if not isinstance(targets, (str, list)):
            return {
                'valid': False,
                'error': "Field 'targets' must be string or list",
                'invalid_field': 'targets'
            }
        
        return {'valid': True}
    
    def _determine_routing_strategy(self, message: Dict) -> RoutingStrategy:
        """Определение стратегии маршрутизации на основе targets"""
        targets = message.get('targets', [])
        
        if targets == "all":
            return RoutingStrategy.BROADCAST
        elif isinstance(targets, str):
            return RoutingStrategy.GROUP
        elif isinstance(targets, list) and len(targets) > 1:
            return RoutingStrategy.MULTICAST
        else:
            return RoutingStrategy.UNICAST
    
    def _determine_routers(self, message: Dict) -> List[str]:
        """Определение роутеров для обработки сообщения"""
        routers = message.get('routers', [])
        
        if not routers:  # пустой список = внутренний
            return ["internal"]
        elif routers == "internal":
            return ["internal"]
        elif routers == "external":
            return ["external"]
        elif isinstance(routers, list):
            return routers
        else:
            return ["internal"]  # fallback
    
    def _should_handle_message(self, routers: List[str]) -> bool:
        """Должен ли этот роутер обрабатывать сообщение?"""
        if "internal" in routers and not self.is_external:
            return True
        elif self.router_id in routers:
            return True
        elif "external" in routers and self.is_external:
            return True
        return False
    
    def _execute_routing(self, strategy: RoutingStrategy, message: Dict) -> Dict[str, Any]:
        """Выполнение маршрутизации по стратегии"""
        try:
            targets = message.get('targets', [])
            
            if strategy == RoutingStrategy.BROADCAST:
                return self._route_broadcast(message)
            elif strategy == RoutingStrategy.GROUP:
                return self._route_group(message, targets)
            elif strategy == RoutingStrategy.MULTICAST:
                return self._route_multicast(message, targets)
            else:  # UNICAST
                return self._route_unicast(message, targets)
                
        except Exception as e:
            self.logger.error(f"Routing execution failed: {e}")
            return {
                'status': DeliveryStatus.FAILED,
                'error': str(e),
                'message_id': message.get('id', 'unknown')
            }
    
    def _route_unicast(self, message: Dict, target: Union[str, List]) -> Dict[str, Any]:
        """Маршрутизация одному получателю"""
        if isinstance(target, list):
            target = target[0]  # берем первого из списка
            
        return self._deliver_to_target(message, target)
    
    def _route_multicast(self, message: Dict, targets: List[str]) -> Dict[str, Any]:
        """Маршрутизация нескольким получателям"""
        results = []
        for target in targets:
            result = self._deliver_to_target(message, target)
            results.append(result)
        
        # Определяем общий статус
        if all(r['status'] == DeliveryStatus.DELIVERED for r in results):
            overall_status = DeliveryStatus.DELIVERED
        elif any(r['status'] == DeliveryStatus.DELIVERED for r in results):
            overall_status = DeliveryStatus.PENDING  # частичная доставка
        else:
            overall_status = DeliveryStatus.FAILED
            
        return {
            'status': overall_status,
            'details': results,
            'message_id': message.get('id', 'unknown')
        }
    
    def _route_group(self, message: Dict, group_name: str) -> Dict[str, Any]:
        """Маршрутизация группе получателей"""
        # TODO: Реализовать когда будет менеджер групп процессов
        self.logger.warning(f"Group routing not implemented yet for group: {group_name}")
        return {
            'status': DeliveryStatus.FAILED,
            'error': f"Group routing not implemented: {group_name}",
            'message_id': message.get('id', 'unknown')
        }
    
    def _route_broadcast(self, message: Dict) -> Dict[str, Any]:
        """Широковещательная маршрутизация"""
        # TODO: Реализовать когда будет менеджер процессов
        self.logger.warning("Broadcast routing not implemented yet")
        return {
            'status': DeliveryStatus.FAILED,
            'error': "Broadcast routing not implemented",
            'message_id': message.get('id', 'unknown')
        }
    
    def _deliver_to_target(self, message: Dict, target: str) -> Dict[str, Any]:
        """Доставка сообщения конкретной цели"""
        try:
            # Определяем метод доставки на основе типа цели
            delivery_method = self._get_delivery_method(target)
            if not delivery_method:
                return {
                    'status': DeliveryStatus.FAILED,
                    'error': f"No delivery method for target: {target}",
                    'target': target,
                    'message_id': message.get('id', 'unknown')
                }
            
            # Доставляем сообщение
            result = delivery_method(target, message)
            
            return {
                'status': DeliveryStatus.DELIVERED if result else DeliveryStatus.FAILED,
                'target': target,
                'message_id': message.get('id', 'unknown'),
                'result': result
            }
            
        except Exception as e:
            self.logger.error(f"Delivery failed to {target}: {e}")
            return {
                'status': DeliveryStatus.FAILED,
                'error': str(e),
                'target': target,
                'message_id': message.get('id', 'unknown')
            }
    
    def _get_delivery_method(self, target: str) -> Optional[Callable]:
        """Получение метода доставки для цели"""
        # Пока используем первый зарегистрированный метод
        # TODO: Реализовать логику выбора метода на основе цели
        if self.send_methods:
            return next(iter(self.send_methods.values()))
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики роутера"""
        return self.stats.copy()
    
    def process_incoming_messages(self, stop_event, pause_event):
        """Обработка входящих сообщений (для использования в WorkerManager)"""
        # TODO: Реализовать когда будет очередь входящих сообщений
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(0.01)


# Пример тестирования роутера
def test_router():
    # Создаем роутер
    router = UniversalRouterManager("test_router")
    
    # Регистрируем тестовый метод отправки
    def test_send(target, message):
        print(f"Delivered to {target}: {message.get('type')}")
        return True
    
    router.register_send_method("test", test_send)
    
    # Тестовые сообщения
    messages = [
        {
            "id": "msg1",
            "type": "command",
            "sender": "test_sender",
            "targets": ["process_a"],
            "routers": ["internal"],
            "priority": "high",
            "data": {"command": "start"}
        },
        {
            "id": "msg2", 
            "type": "log",
            "sender": "test_sender",
            "targets": "all",
            "routers": ["internal", "external"],
            "data": {"level": "INFO", "message": "Test log"}
        }
    ]
    
    # Отправляем сообщения
    for msg in messages:
        result = router.route_message(msg)
        print(f"Message {msg['id']}: {result['status']}")
    
    # Получаем статистику
    print("Router stats:", router.get_stats())

if __name__ == "__main__":
    test_router()