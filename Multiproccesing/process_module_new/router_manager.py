# router_manager.py
from typing import Dict, Any, Callable, Optional
import time
from dispatch_handler import Dispatcher

class RouterManager:
    """
    Упрощенный менеджер маршрутизации - только базовые каналы
    """
    
    def __init__(self, router_id: str, logger_manager=None):
        self.router_id = router_id
        self.logger = logger_manager
        
        # Диспетчер для каналов доставки
        self.channel_dispatcher = Dispatcher(f"channels_{router_id}")
        
        # Базовая статистика
        self.stats = {'sent': 0, 'received': 0, 'errors': 0}
        
        # Инициализация базовых каналов
        self._init_basic_channels()
        
        self._log("info", f"Router {router_id} ready")

    def _log(self, level: str, message: str):
        """Простое логирование"""
        if self.logger:
            getattr(self.logger, level)(f"[{self.router_id}] {message}")
        else:
            print(f"[{level.upper()}] {self.router_id}: {message}")

    def _init_basic_channels(self):
        """Только самые необходимые каналы"""
        channels = [
            ("internal", self._deliver_internal),    # Внутри процесса
            ("queue", self._deliver_queue),          # Межпроцессные очереди  
            ("log", self._deliver_log),              # Логирование
        ]
        
        for name, handler in channels:
            self.channel_dispatcher.register_handler(name, handler)

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Простая отправка сообщения
        """
        self.stats['sent'] += 1
        
        try:
            # Определяем канал доставки
            channel = message.get('channel', self._detect_channel(message))
            
            # Отправляем через диспетчер
            result = self.channel_dispatcher.dispatch(message, key_field=channel)
            
            if result.get('status') == 'error':
                self.stats['errors'] += 1
                self._log("error", f"Send failed: {result.get('reason')}")
            else:
                self._log("debug", f"Message delivered via {channel}")
                
            return result
            
        except Exception as e:
            self.stats['errors'] += 1
            self._log("error", f"Send error: {e}")
            return {'status': 'error', 'reason': str(e)}

    def receive(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Простой прием сообщения  
        """
        self.stats['received'] += 1
        self._log("debug", f"Message received: {message.get('type')}")
        return self.send(message)  # Перенаправляем на отправку

    def _detect_channel(self, message: Dict) -> str:
        """Автоматическое определение канала"""
        msg_type = message.get('type', '')
        target = message.get('target', '')
        
        if msg_type == 'log' or target == 'logger':
            return 'log'
        elif target in ['internal', 'router']:
            return 'internal' 
        else:
            return 'queue'  # По умолчанию - очередь

    # === БАЗОВЫЕ КАНАЛЫ ДОСТАВКИ ===
    
    def _deliver_internal(self, message: Dict) -> Dict[str, Any]:
        """Доставка внутри процесса"""
        target = message.get('target')
        self._log("debug", f"Internal delivery to {target}")
        return {'status': 'success', 'channel': 'internal'}

    def _deliver_queue(self, message: Dict) -> Dict[str, Any]:
        """Доставка через очередь"""
        target = message.get('target') 
        self._log("debug", f"Queue delivery to {target}")
        return {'status': 'success', 'channel': 'queue'}

    def _deliver_log(self, message: Dict) -> Dict[str, Any]:
        """Доставка в лог"""
        log_data = message.get('data', {})
        level = log_data.get('level', 'INFO').lower()
        text = log_data.get('message', '')
        
        self._log(level, text)
        return {'status': 'success', 'channel': 'log'}

    # === БАЗОВОЕ УПРАВЛЕНИЕ ===
    
    def register_channel(self, name: str, handler: Callable) -> bool:
        """Регистрация кастомного канала"""
        success = self.channel_dispatcher.register_handler(name, handler)
        if success:
            self._log("info", f"Channel registered: {name}")
        return success

    def get_stats(self) -> Dict[str, Any]:
        """Базовая статистика"""
        return {
            'router_id': self.router_id,
            'sent': self.stats['sent'],
            'received': self.stats['received'], 
            'errors': self.stats['errors']
        }

# === ИНТЕГРАЦИЯ С PROCESS_MODULE ===

class ProcessRouterManager(RouterManager):
    """
    Роутер для ProcessModule с привязкой к менеджерам
    """
    
    def __init__(self, process_module, logger_manager=None):
        super().__init__(f"process_{process_module.name}", logger_manager)
        self.process_module = process_module
        
        # Регистрируем процесс-специфичные каналы
        self.register_channel("process_internal", self._deliver_to_manager)
        self.register_channel("process_queue", self._deliver_to_queue)

    def _deliver_to_manager(self, message: Dict) -> Dict[str, Any]:
        """Доставка менеджеру внутри процесса"""
        msg_type = message.get('type')
        target = message.get('target')
        
        # Простая маршрутизация к менеджерам
        manager_map = {
            'command': 'commands',
            'log': 'logger', 
            'worker': 'workers'
        }
        
        manager_name = manager_map.get(msg_type)
        if manager_name:
            manager = self.process_module.get_manager(manager_name)
            if manager:
                self._log("debug", f"Delivered to {manager_name}")
                return {'status': 'success', 'manager': manager_name}
        
        return {'status': 'error', 'reason': f'No manager for {msg_type}'}

    def _deliver_to_queue(self, message: Dict) -> Dict[str, Any]:
        """Доставка в очередь процесса"""
        queue_name = message.get('queue', 'system')
        
        if hasattr(self.process_module, 'queues'):
            queue = self.process_module.queues.get(queue_name)
            if queue:
                queue.put(message)
                self._log("debug", f"Queued to {queue_name}")
                return {'status': 'success', 'queue': queue_name}
        
        return {'status': 'error', 'reason': f'Queue not found: {queue_name}'}

# === ПРОСТОЕ ТЕСТИРОВАНИЕ ===

def test_simple_router():
    """Тестирование упрощенного роутера"""
    
    # Создаем мок логгера
    class TestLogger:
        def info(self, msg): print(f"[INFO] {msg}")
        def debug(self, msg): print(f"[DEBUG] {msg}") 
        def error(self, msg): print(f"[ERROR] {msg}")
    
    router = RouterManager("test", TestLogger())
    
    # Тестовые сообщения
    messages = [
        {"id": "1", "type": "command", "target": "internal", "data": {"action": "test"}},
        {"id": "2", "type": "log", "target": "logger", "data": {"level": "INFO", "message": "Hello"}},
    ]
    
    print("🚀 Testing simple router...")
    
    for msg in messages:
        result = router.send(msg)
        print(f"Message {msg['id']}: {result['status']}")
    
    print("📊 Stats:", router.get_stats())
    
    return router

if __name__ == "__main__":
    test_simple_router()