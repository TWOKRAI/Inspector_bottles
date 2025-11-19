# router_manager.py
from typing import Dict, Any, Callable, Optional, List
import time
from queue import Queue, Empty
import threading
from Dispatch_module.dispatch_handler import Dispatcher


class RouterManager:
    """
    Упрощенный менеджер маршрутизации с приемом сообщений
    """
    
    def __init__(self, router_id: str, logger_manager=None):
        self.router_id = router_id
        self.logger = logger_manager
        
        # Диспетчер для каналов отправки
        self.channel_dispatcher = Dispatcher(f"channels_{router_id}")
        
        # Каналы приема (имя -> очередь сообщений)
        self.receive_queues: Dict[str, Queue] = {}
        
        # Очередь входящих сообщений для обработки
        self.incoming_queue = Queue()
        
        # Статистика
        self.stats = {'sent': 0, 'received': 0, 'errors': 0, 'processed': 0}
        
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
        """Базовые каналы отправки"""
        channels = [
            ("internal", self._deliver_internal),
            ("queue", self._deliver_queue),  
            ("log", self._deliver_log),
        ]
        
        for name, handler in channels:
            self.channel_dispatcher.register_handler(name, handler)

    # === ОТПРАВКА СООБЩЕНИЙ ===
    
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

    # === ПРИЕМ СООБЩЕНИЙ ===
    
    def register_receive_channel(self, name: str, queue: Queue) -> bool:
        """Регистрация канала для приема сообщений"""
        self.receive_queues[name] = queue
        self._log("info", f"Receive channel registered: {name}")
        return True

    def poll_messages(self, timeout: float = 0.01) -> List[Dict[str, Any]]:
        """
        Опрос всех каналов приема для получения сообщений
        Возвращает список сообщений с информацией о канале и времени
        """
        messages = []
        
        for channel_name, queue in self.receive_queues.items():
            try:
                # Пытаемся получить сообщение без блокировки
                message = queue.get_nowait()
                
                if message:
                    # Добавляем мета-информацию
                    if isinstance(message, dict):
                        message['_receive_info'] = {
                            'channel': channel_name,
                            'receive_time': time.time(),
                            'router_id': self.router_id
                        }
                    else:
                        # Если сообщение не dict, оборачиваем его
                        message = {
                            'data': message,
                            '_receive_info': {
                                'channel': channel_name,
                                'receive_time': time.time(),
                                'router_id': self.router_id
                            }
                        }
                    
                    messages.append(message)
                    self.stats['received'] += 1
                    
            except Empty:
                # Очередь пуста - это нормально
                continue
            except Exception as e:
                self.stats['errors'] += 1
                self._log("error", f"Error polling {channel_name}: {e}")
        
        return messages

    def process_incoming(self, handler: Callable[[Dict], None], 
                        stop_event: threading.Event = None,
                        poll_interval: float = 0.01):
        """
        Бесконечный цикл обработки входящих сообщений
        Для использования в отдельном потоке
        """
        self._log("info", "Starting message processing loop")
        
        while True:
            if stop_event and stop_event.is_set():
                self._log("info", "Stopping message processing loop")
                break
                
            try:
                # Опрашиваем каналы
                messages = self.poll_messages()
                
                # Обрабатываем каждое сообщение
                for message in messages:
                    try:
                        handler(message)
                        self.stats['processed'] += 1
                    except Exception as e:
                        self.stats['errors'] += 1
                        self._log("error", f"Message handling error: {e}")
                
                # Не грузим CPU
                time.sleep(poll_interval)
                
            except Exception as e:
                self.stats['errors'] += 1
                self._log("error", f"Processing loop error: {e}")
                time.sleep(1)  # Пауза при ошибке

    def _detect_channel(self, message: Dict) -> str:
        """Автоматическое определение канала отправки"""
        msg_type = message.get('type', '')
        target = message.get('target', '')
        
        if msg_type == 'log' or target == 'logger':
            return 'log'
        elif target in ['internal', 'router']:
            return 'internal' 
        else:
            return 'queue'

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

    # === УПРАВЛЕНИЕ ===
    
    def register_channel(self, name: str, handler: Callable) -> bool:
        """Регистрация кастомного канала отправки"""
        success = self.channel_dispatcher.register_handler(name, handler)
        if success:
            self._log("info", f"Channel registered: {name}")
        return success

    def get_stats(self) -> Dict[str, Any]:
        """Статистика"""
        return {
            'router_id': self.router_id,
            'sent': self.stats['sent'],
            'received': self.stats['received'], 
            'processed': self.stats['processed'],
            'errors': self.stats['errors'],
            'receive_channels': len(self.receive_queues)
        }


def test_router_with_receive():
    """Тестирование роутера с приемом сообщений"""
    
    class TestLogger:
        def info(self, msg): print(f"[INFO] {msg}")
        def debug(self, msg): print(f"[DEBUG] {msg}") 
        def error(self, msg): print(f"[ERROR] {msg}")
    
    # Создаем тестовые очереди
    test_queue1 = Queue()
    test_queue2 = Queue()
    
    router = RouterManager("test", TestLogger())
    
    # Регистрируем каналы приема
    router.register_receive_channel("test_channel1", test_queue1)
    router.register_receive_channel("test_channel2", test_queue2)
    
    # Кладем тестовые сообщения в очереди
    test_queue1.put({"id": "1", "type": "test", "data": "Hello from channel1"})
    test_queue2.put({"id": "2", "type": "test", "data": "Hello from channel2"})
    
    print("🚀 Testing router with receive...")
    
    # Опрашиваем сообщения
    messages = router.poll_messages()
    print(f"Received {len(messages)} messages")
    
    for msg in messages:
        print(f"Message: {msg.get('id')} from {msg.get('_receive_info', {}).get('channel')}")
        print(f"Full message: {msg}")
    
    print("📊 Stats:", router.get_stats())
    
    return router

if __name__ == "__main__":
    test_router_with_receive()