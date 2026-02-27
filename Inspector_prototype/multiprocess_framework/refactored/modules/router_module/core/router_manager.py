"""
Менеджер маршрутизации сообщений (Refactored).

Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
Интегрируется с Dispatch модулем для интеллектуальной маршрутизации сообщений.

Архитектура:
- RouterManager → Dispatcher → MessageChannel
- RouterManager использует Dispatch модуль для выбора канала отправки
- Dispatcher анализирует сообщение и выбирает оптимальный канал
- MessageChannel отправляет сообщение через свой протокол (Queue, Logger, etc.)
"""

from typing import Dict, Any, List, Optional, Callable, Union
import time
import threading

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager

# Импорт Dispatch_module из refactored модуля
from ...dispatch_module import Dispatcher, DispatchStrategy, HandlerInfo

# Импорт MessageChannel из локального модуля
from ..channels.base_channel import MessageChannel

# Импорт Message для типизации (циклический импорт избегаем через TYPE_CHECKING)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...message_module import Message


class RouterManager(BaseManager, ObservableMixin):
    """
    Универсальный менеджер маршрутизации с интеллектуальным диспетчером (Refactored).
    
    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)
    
    Философия:
    - Dispatcher выбирает КАКОЙ канал использовать для отправки
    - MessageChannel знает КАК отправлять/принимать через свой протокол
    - RouterManager управляет всем процессом маршрутизации
    
    Attributes:
        manager_name: Имя роутера (синоним router_id для совместимости)
        queue_registry: Реестр очередей (опционально)
        _channels: Реестр каналов (Dict[str, MessageChannel])
        channel_dispatcher: Dispatcher для выбора канала отправки
        message_dispatcher: Dispatcher для обработки входящих сообщений
        _listening: Флаг асинхронного прослушивания
        _listener_thread: Поток для асинхронного прослушивания
        _message_callbacks: Список колбэков для входящих сообщений
        _stats: Статистика работы роутера
    """
    
    def __init__(
        self, 
        manager_name: str,
        process: Optional[Any] = None,
        queue_registry=None,
        dispatch_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        logger=None,
        **kwargs
    ):
        """
        Инициализация роутера.
        
        Args:
            manager_name: Имя роутера (синоним router_id для совместимости)
            process: Ссылка на родительский процесс (опционально)
            queue_registry: Реестр очередей (опционально)
            dispatch_strategy: Стратегия диспетчеризации
            logger: Логгер (опционально, используется через ObservableMixin)
            **kwargs: Дополнительные параметры для ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Инициализация ObservableMixin
        managers = kwargs.get('managers', {})
        if logger and 'logger' not in managers:
            managers['logger'] = logger
        
        config = kwargs.get('config', {})
        auto_proxy = kwargs.get('auto_proxy', True)  # Автоматические прокси-методы для логирования
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=auto_proxy
        )
        
        # Сохраняем параметры для совместимости
        self.router_id = manager_name  # Синоним для совместимости со старым API
        self.queue_registry = queue_registry
        
        # Реестр каналов
        self._channels: Dict[str, MessageChannel] = {}
        
        # Диспетчер для выбора каналов отправки
        self.channel_dispatcher = Dispatcher(
            f"{manager_name}_channel_dispatcher", 
            default_strategy=dispatch_strategy
        )
        
        # Диспетчер для обработки входящих сообщений
        self.message_dispatcher = Dispatcher(
            f"{manager_name}_message_dispatcher",
            default_strategy=dispatch_strategy
        )
        
        # Асинхронное прослушивание
        self._listening = False
        self._listener_thread = None
        self._message_callbacks = []
        
        # Статистика
        self._stats = {
            'sent': 0,
            'received': 0,
            'errors': 0,
            'processed': 0,
            'dispatch_errors': 0
        }
        
        # НЕ вызываем initialize() здесь - это делается явно после создания
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация роутера.
        
        Инициализирует обработчики по умолчанию и настраивает диспетчеры.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация обработчиков по умолчанию
            self._init_default_handlers()
            
            self.is_initialized = True
            self._log_info(f"Router '{self.manager_name}' initialized with dispatcher integration")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize router: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы роутера.
        
        Останавливает прослушивание, очищает каналы и колбэки.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Останавливаем прослушивание
            self.stop_listening()
            
            # Останавливаем прослушивание на всех каналах
            for channel in self._channels.values():
                try:
                    if hasattr(channel, 'stop_listening'):
                        channel.stop_listening()
                except Exception as e:
                    self._log_error(f"Error stopping channel {channel.name}: {e}")
            
            # Очищаем колбэки
            self._message_callbacks.clear()
            
            # Очищаем каналы
            self._channels.clear()
            
            self.is_initialized = False
            self._log_info("Router shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during router shutdown: {e}")
            return False
    
    # ========================================================================
    # ИНИЦИАЛИЗАЦИЯ ОБРАБОТЧИКОВ ПО УМОЛЧАНИЮ
    # ========================================================================
    
    def _init_default_handlers(self):
        """Инициализация обработчиков по умолчанию для диспетчера каналов."""
        # Обработчик для логических сообщений
        self.channel_dispatcher.register_handler(
            key="log_message",
            handler=self._handle_log_message,
            expects_full_message=True,
            efficiency=10,
            tags=["log", "system"]
        )
        
        # Обработчик для broadcast сообщений
        self.channel_dispatcher.register_handler(
            key="broadcast_message", 
            handler=self._handle_broadcast_message,
            expects_full_message=True,
            efficiency=5,
            tags=["broadcast", "system"]
        )
        
        # Обработчик по умолчанию (очередь)
        self.channel_dispatcher.register_handler(
            key="default_queue",
            handler=self._handle_default_queue,
            expects_full_message=True,
            efficiency=0,
            tags=["queue", "default"]
        )
    
    # ========================================================================
    # ОСНОВНОЙ API - ОТПРАВКА С ДИСПЕТЧЕРИЗАЦИЕЙ
    # ========================================================================
    
    def send(self, message: Union['Message', Dict[str, Any]]) -> Dict[str, Any]:
        """
        Отправить сообщение с интеллектуальным выбором канала через диспетчер.
        Поддерживает как объекты Message, так и словари для обратной совместимости.
        
        Args:
            message: Сообщение для отправки (Message объект или словарь)
            
        Returns:
            Результат отправки
            
        Example:
            # С Message объектом
            msg = Message.create(type=MessageType.COMMAND, sender="GUI", targets=["Worker"], command="process")
            result = router.send(msg)
            
            # Со словарем (обратная совместимость)
            result = router.send({
                'type': 'command',
                'sender': 'GUI',
                'targets': ['Worker'],
                'command': 'process_data'
            })
        """
        self._stats['sent'] += 1
        
        try:
            # Конвертируем Message в dict если нужно
            if hasattr(message, 'to_dict'):
                # Это объект Message
                message_dict = message.to_dict()
            else:
                # Это уже словарь
                message_dict = message
            
            # Если канал указан явно - используем его
            explicit_channel = message_dict.get('channel')
            if explicit_channel:
                return self._send_via_channel(message_dict, explicit_channel)
            
            # Определяем ключ для диспетчера
            dispatch_key = self._get_dispatch_key(message_dict)
            
            # Находим обработчик напрямую по ключу
            handler_info = self.channel_dispatcher._find_handler(dispatch_key)
            
            # Если обработчик не найден, используем обработчик по умолчанию
            if not handler_info:
                self._log_debug(f"No handler found for key '{dispatch_key}', using default_queue")
                handler_info = self.channel_dispatcher._find_handler('default_queue')
                if not handler_info:
                    self._stats['dispatch_errors'] += 1
                    return self._handle_send_error(f"No handler found for key '{dispatch_key}' and no default handler")
            
            # Вызываем обработчик напрямую
            try:
                handler_data = message_dict if handler_info.expects_full_message else message_dict.get("data", {})
                dispatch_result = handler_info.handler(handler_data)
                
                # Проверяем результат обработчика
                if dispatch_result.get('status') == 'error':
                    self._stats['dispatch_errors'] += 1
                    return self._handle_send_error(f"Handler error: {dispatch_result.get('reason')}")
                
                # dispatch_result содержит имя канала и параметры
                channel_name = dispatch_result.get('channel', 'internal_queue')
                return self._send_via_channel(message_dict, channel_name)
            except Exception as e:
                self._stats['dispatch_errors'] += 1
                return self._handle_send_error(f"Handler execution failed: {e}")
            
        except Exception as e:
            return self._handle_send_error(f"Send error: {e}")
    
    def _get_dispatch_key(self, message: Union['Message', Dict[str, Any]]) -> str:
        """
        Определяет ключ для диспетчера на основе сообщения.
        Работает как с Message объектами, так и со словарями.
        
        Приоритет:
        1. Поле 'command' для командных сообщений
        2. Поле 'type' для типизированных сообщений  
        3. Автоматическое определение по содержимому
        """
        # Поддержка Message объектов через словарный интерфейс
        if hasattr(message, 'get'):
            # Это Message объект - используем словарный интерфейс O(1)
            get_func = message.get
            contains_func = lambda k: k in message
        else:
            # Это словарь
            get_func = message.get
            contains_func = lambda k: k in message
        
        # Командные сообщения
        if contains_func('command'):
            return get_func('command')
        
        # Типизированные сообщения
        if contains_func('type'):
            msg_type = get_func('type')
            
            # Специальные обработки для системных типов
            if msg_type == 'log':
                return 'log_message'
            elif msg_type in ['broadcast', 'event']:
                return 'broadcast_message'
            else:
                return msg_type
        
        # Автоматическое определение по содержимому
        if contains_func('targets'):
            targets = get_func('targets', [])
            if isinstance(targets, list) and 'all' in targets:
                return 'broadcast_message'
        
        # По умолчанию
        return 'default_queue'
    
    def _send_via_channel(self, message: Dict[str, Any], channel_name: str) -> Dict[str, Any]:
        """
        Отправка сообщения через конкретный канал.
        
        Если указанный канал не найден, пытается использовать первый доступный канал.
        """
        channel = self._channels.get(channel_name)
        if not channel:
            # Если канал не найден, пытаемся использовать первый доступный канал
            if self._channels:
                # Используем первый доступный канал
                first_channel_name = next(iter(self._channels.keys()))
                channel = self._channels[first_channel_name]
                self._log_debug(f"Channel '{channel_name}' not found, using '{first_channel_name}' instead")
            else:
                return self._handle_send_error(f"Channel not found: {channel_name} and no channels available")
        
        result = channel.send(message)
        
        if result.get('status') == 'error':
            self._stats['errors'] += 1
            self._log_error(f"Send failed via {channel_name}: {result.get('reason')}")
        else:
            self._log_debug(f"Message delivered via {channel_name}")
        
        return result
    
    def _handle_send_error(self, error_msg: str) -> Dict[str, Any]:
        """Обработка ошибок отправки."""
        self._stats['errors'] += 1
        self._log_error(error_msg)
        return {'status': 'error', 'reason': error_msg}
    
    # ========================================================================
    # ОБРАБОТЧИКИ КАНАЛОВ ДЛЯ ДИСПЕТЧЕРА
    # ========================================================================
    
    def _handle_log_message(self, message: Union['Message', Dict[str, Any]]) -> Dict[str, Any]:
        """Обработчик для логических сообщений."""
        return {
            'status': 'success',
            'channel': 'log_channel',
            'handler': 'log_message'
        }
    
    def _handle_broadcast_message(self, message: Union['Message', Dict[str, Any]]) -> Dict[str, Any]:
        """Обработчик для широковещательных сообщений."""
        # Можно добавить логику выбора между разными broadcast каналами
        return {
            'status': 'success', 
            'channel': 'internal_queue',  # В будущем заменить на реальный broadcast канал
            'handler': 'broadcast_message'
        }
    
    def _handle_default_queue(self, message: Union['Message', Dict[str, Any]]) -> Dict[str, Any]:
        """Обработчик по умолчанию для очередей."""
        return {
            'status': 'success',
            'channel': 'internal_queue',
            'handler': 'default_queue'
        }
    
    # ========================================================================
    # РЕГИСТРАЦИЯ КАСТОМНЫХ ОБРАБОТЧИКОВ КАНАЛОВ
    # ========================================================================
    
    def register_channel_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Зарегистрировать кастомный обработчик для выбора каналов.
        
        Args:
            key: Ключ для диспетчеризации
            handler: Функция-обработчик, возвращающая channel_name
            expects_full_message: Использовать полное сообщение
            metadata: Метаданные обработчика
            efficiency: Уровень эффективности обработчика (для FALLBACK_MATCH стратегии)
            tags: Теги для группировки
            
        Example:
            def custom_channel_selector(message):
                if message.get('urgent'):
                    return {'channel': 'priority_queue'}
                return {'channel': 'internal_queue'}
            
            router.register_channel_handler('urgent_message', custom_channel_selector)
        """
        return self.channel_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags
        )
    
    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Зарегистрировать обработчик для входящих сообщений.
        
        Args:
            key: Ключ для диспетчеризации входящих сообщений
            handler: Функция-обработчик входящих сообщений
            expects_full_message: Использовать полное сообщение
            metadata: Метаданные обработчика
            efficiency: Уровень эффективности обработчика (для FALLBACK_MATCH стратегии)
            tags: Теги для группировки
        """
        return self.message_dispatcher.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags
        )
    
    # ========================================================================
    # ПРИЕМ И ОБРАБОТКА СООБЩЕНИЙ
    # ========================================================================
    
    def receive(self, timeout: float = 0.0, return_messages: bool = True) -> List[Union['Message', Dict[str, Any]]]:
        """
        Получить сообщения со всех каналов и обработать через диспетчер.
        Автоматически конвертирует словари в Message объекты для удобства работы.
        
        Args:
            timeout: Таймаут опроса
            return_messages: Если True, возвращает Message объекты, иначе словари
            
        Returns:
            Список сообщений (Message объекты или словари) с результатами обработки
        """
        # Импортируем Message здесь чтобы избежать циклического импорта
        from ...message_module import Message
        
        messages = self._poll_all_channels(timeout)
        processed_messages = []
        
        for message_dict in messages:
            try:
                # Добавляем информацию о роутере
                if isinstance(message_dict, dict):
                    if '_receive_info' not in message_dict:
                        message_dict['_receive_info'] = {}
                    message_dict['_receive_info'].update({
                        'router_id': self.router_id,
                        'receive_time': time.time()
                    })
                
                # Обрабатываем через диспетчер сообщений
                dispatch_key = self._get_dispatch_key(message_dict)
                dispatch_result = self.message_dispatcher.dispatch(
                    message=message_dict,
                    key_field=dispatch_key
                )
                
                message_dict['_dispatch_result'] = dispatch_result
                
                # Конвертируем в Message объект если нужно
                if return_messages:
                    message = Message.from_dict(message_dict)
                    processed_messages.append(message)
                else:
                    processed_messages.append(message_dict)
                
            except Exception as e:
                self._log_error(f"Message processing error: {e}")
                if isinstance(message_dict, dict):
                    message_dict['_dispatch_result'] = {'status': 'error', 'reason': str(e)}
                    if return_messages:
                        try:
                            message = Message.from_dict(message_dict)
                            processed_messages.append(message)
                        except Exception:
                            processed_messages.append(message_dict)
                    else:
                        processed_messages.append(message_dict)
                else:
                    processed_messages.append(message_dict)
        
        self._stats['received'] += len(processed_messages)
        return processed_messages
    
    # ========================================================================
    # АСИНХРОННЫЙ ПРИЕМ С ДИСПЕТЧЕРИЗАЦИЕЙ
    # ========================================================================
    
    def add_message_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Добавить колбэк для асинхронного приема сообщений."""
        if callback not in self._message_callbacks:
            self._message_callbacks.append(callback)
    
    def start_listening(self, poll_interval: float = 0.01):
        """Запустить асинхронное прослушивание с диспетчеризацией."""
        if self._listening:
            self._log_warning("Already listening")
            return
        
        self._listening = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            args=(poll_interval,),
            daemon=True
        )
        self._listener_thread.start()
        self._log_info("Started async message listening with dispatcher")
    
    def _listen_loop(self, poll_interval: float):
        """Цикл асинхронного прослушивания с диспетчеризацией."""
        while self._listening:
            try:
                # Получаем Message объекты по умолчанию для удобства работы
                messages = self.receive(return_messages=True)
                
                for message in messages:
                    # Вызываем зарегистрированные колбэки
                    for callback in self._message_callbacks:
                        try:
                            callback(message)
                            self._stats['processed'] += 1
                        except Exception as e:
                            self._stats['errors'] += 1
                            self._log_error(f"Callback error: {e}")
                
                time.sleep(poll_interval)
                
            except Exception as e:
                self._stats['errors'] += 1
                self._log_error(f"Listen loop error: {e}")
                time.sleep(1)
    
    def stop_listening(self, timeout: float = 5.0) -> bool:
        """
        Остановить асинхронное прослушивание сообщений.
        
        Args:
            timeout: Таймаут ожидания остановки потока в секундах
            
        Returns:
            True если остановка успешна, False в противном случае
        """
        if not self._listening:
            self._log_debug("Not listening, nothing to stop")
            return True
        
        self._listening = False
        
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=timeout)
            
            if self._listener_thread.is_alive():
                self._log_warning(f"Listener thread did not stop within {timeout} seconds")
                return False
            else:
                self._log_info("Listener thread stopped successfully")
        
        self._listener_thread = None
        return True
    
    # ========================================================================
    # УПРАВЛЕНИЕ КАНАЛАМИ
    # ========================================================================
    
    def register_channel(self, channel: MessageChannel) -> bool:
        """
        Зарегистрировать канал в роутере.
        
        Args:
            channel: Канал, реализующий интерфейс MessageChannel
            
        Returns:
            True если канал успешно зарегистрирован
        """
        try:
            if not isinstance(channel, MessageChannel):
                self._log_error(f"Channel must implement MessageChannel interface")
                return False
            
            channel_name = channel.name
            if channel_name in self._channels:
                self._log_warning(f"Channel '{channel_name}' already registered, replacing")
            
            self._channels[channel_name] = channel
            self._log_debug(f"Channel '{channel_name}' registered successfully")
            return True
        except Exception as e:
            self._log_error(f"Failed to register channel: {e}")
            return False
    
    def unregister_channel(self, channel_name: str) -> bool:
        """
        Удалить канал из роутера.
        
        Args:
            channel_name: Имя канала для удаления
            
        Returns:
            True если канал успешно удален
        """
        if channel_name in self._channels:
            del self._channels[channel_name]
            self._log_debug(f"Channel '{channel_name}' unregistered")
            return True
        return False
    
    def get_channel(self, channel_name: str) -> Optional[MessageChannel]:
        """Получить канал по имени."""
        return self._channels.get(channel_name)
    
    def get_all_channels(self) -> List[MessageChannel]:
        """Получить все зарегистрированные каналы."""
        return list(self._channels.values())
    
    def _poll_all_channels(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """
        Получить сообщения со всех зарегистрированных каналов.
        
        Args:
            timeout: Таймаут опроса для каждого канала
            
        Returns:
            Список всех полученных сообщений
        """
        all_messages = []
        for channel_name, channel in self._channels.items():
            try:
                messages = channel.poll(timeout)
                if messages:
                    # Добавляем информацию о канале-источнике
                    for msg in messages:
                        if isinstance(msg, dict):
                            msg['_source_channel'] = channel_name
                    all_messages.extend(messages)
            except Exception as e:
                self._log_error(f"Error polling channel '{channel_name}': {e}")
        
        return all_messages
    
    # ========================================================================
    # СТАТИСТИКА И МОНИТОРИНГ
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить полную статистику работы роутера.
        
        Интегрируется со статистикой BaseManager и ObservableMixin.
        """
        # Получаем базовую статистику от BaseManager
        stats = super().get_stats() if hasattr(super(), 'get_stats') else {}
        
        # Добавляем статистику роутера
        channel_info = {
            'channels_count': len(self._channels),
            'channels': {
                name: channel.get_info() if hasattr(channel, 'get_info') else {'name': name, 'type': channel.channel_type}
                for name, channel in self._channels.items()
            }
        }
        
        router_stats = {
            'router_id': self.router_id,
            'sent': self._stats['sent'],
            'received': self._stats['received'],
            'processed': self._stats['processed'],
            'errors': self._stats['errors'],
            'dispatch_errors': self._stats['dispatch_errors'],
            'listening': self._listening,
            'callbacks_count': len(self._message_callbacks),
            'channel_handlers': len(self.channel_dispatcher.handlers),
            'message_handlers': len(self.message_dispatcher.handlers),
            **channel_info
        }
        
        # Объединяем статистику
        if isinstance(stats, dict):
            stats['router'] = router_stats
        else:
            stats = {'router': router_stats}
        
        return stats
    
    def get_dispatcher_info(self) -> Dict[str, Any]:
        """Получить информацию о диспетчерах."""
        return {
            'channel_dispatcher': {
                'name': self.channel_dispatcher.name,
                'strategy': self.channel_dispatcher.strategy.value,
                'handlers_count': len(self.channel_dispatcher.handlers),
                'handlers': self.channel_dispatcher.get_all_handlers()
            },
            'message_dispatcher': {
                'name': self.message_dispatcher.name,
                'strategy': self.message_dispatcher.strategy.value,
                'handlers_count': len(self.message_dispatcher.handlers),
                'handlers': self.message_dispatcher.get_all_handlers()
            }
        }
    
    # ========================================================================
    # СОВМЕСТИМОСТЬ СО СТАРЫМ API
    # ========================================================================
    
    def cleanup(self):
        """
        Очистка ресурсов роутера (совместимость со старым API).
        
        Делегирует к shutdown() для единообразия.
        """
        self.shutdown()

