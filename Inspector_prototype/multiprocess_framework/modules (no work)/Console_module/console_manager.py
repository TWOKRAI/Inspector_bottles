"""
Console Manager - Управление консольными окнами.

Простой и мощный API для:
- Настройки консолей для процессов
- Родной консоли процесса (если enabled без recipient)
- Дублирования вывода в другие консоли (recipients)
- Создания отдельных каналов
- Интеграции с Router
"""

import sys
import threading
from typing import Dict, Optional, List, Set, Any, Union
from multiprocessing import Process, Queue

from .redirector import ConsoleRedirector
from .window_process import ConsoleWindowProcess
from .console_channel import ConsoleChannel


class _CustomConsoleChannel(ConsoleChannel):
    """Специальный канал для кастомных консолей"""
    
    def __init__(self, name: str, console_manager, custom_channel_name: str):
        super().__init__(name, console_manager, None, None)
        self._custom_channel_name = custom_channel_name
    
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить в кастомный канал"""
        try:
            text = message.get('text', '') or message.get('message', '') or str(message.get('content', ''))
            if not text:
                return {'status': 'error', 'reason': 'No text content'}
            
            level = message.get('level', 'INFO')
            add_timestamp = message.get('timestamp', False)
            formatted_text = self._format_message(text, level, add_timestamp)
            
            success = self._console_manager._send_to_custom_channel(
                self._custom_channel_name, formatted_text
            )
            
            return {'status': 'success' if success else 'error', 'channel': self.name}
        except Exception as e:
            return {'status': 'error', 'reason': str(e)}


class ConsoleManager:
    """
    Менеджер консольных окон.
    
    Простой API для управления консолями процессов и создания отдельных каналов.
    """
    
    def __init__(self, logger=None):
        """
        Args:
            logger: Логгер (опционально)
        """
        self.logger = logger
        # Консоли процессов
        self._console_processes: Dict[str, Process] = {}  # {console_name: Process}
        self._console_queues: Dict[str, Queue] = {}  # {console_name: Queue}
        self._console_titles: Dict[str, str] = {}  # {console_name: title}
        
        # Привязка процессов к консолям
        self._process_consoles: Dict[str, List[str]] = {}  # {process_name: [console_names]}
        self._process_recipients: Dict[str, List[str]] = {}  # {process_name: [recipient_names]}
        self._process_has_native: Dict[str, bool] = {}  # {process_name: bool}
        
        # Redirectors для процессов
        self._redirectors: Dict[str, ConsoleRedirector] = {}
        
        # Кастомные каналы (для специальных сообщений)
        self._custom_channels: Dict[str, Queue] = {}
        
        self._lock = threading.Lock()
    
    # ========================================================================
    # НАСТРОЙКА КОНСОЛЕЙ ДЛЯ ПРОЦЕССОВ
    # ========================================================================
    
    def configure_process_console(
        self,
        process_name: str,
        enabled: bool = True,
        recipient: Optional[Union[str, List[str]]] = None,
        title: Optional[str] = None
    ):
        """
        Настройка консоли для процесса.
        
        Args:
            process_name: Имя процесса
            enabled: Включить родную консоль процесса (по умолчанию True)
            recipient: Получатели вывода - список консолей, куда дублировать.
                       Может быть строкой (один получатель) или списком.
                       Если не указан и enabled=True, создается только родная консоль.
            title: Заголовок родной консоли процесса (None = имя процесса)
            
        Логика:
            - enabled=True, recipient=None → создается родная консоль процесса
            - enabled=True, recipient=["console1"] → родная консоль + дублирование в console1
            - enabled=False, recipient=["console1"] → только дублирование (без родной)
            
        Example:
            # Родная консоль процесса
            console_manager.configure_process_console("Worker1", enabled=True)
            
            # Родная консоль + дублирование в другую
            console_manager.configure_process_console(
                "Worker1", 
                enabled=True, 
                recipient="shared_console"
            )
            
            # Только дублирование (без родной)
            console_manager.configure_process_console(
                "Worker1",
                enabled=False,
                recipient=["console1", "console2"]
            )
        """
        with self._lock:
            # Нормализуем recipient в список
            recipients_list = []
            if recipient:
                if isinstance(recipient, str):
                    recipients_list = [recipient]
                elif isinstance(recipient, list):
                    recipients_list = recipient
            
            # Сохраняем конфигурацию
            self._process_has_native[process_name] = enabled
            self._process_recipients[process_name] = recipients_list
            
            # Формируем список всех консолей для процесса
            console_list = []
            
            # Добавляем родную консоль если enabled
            if enabled:
                native_console = process_name
                console_list.append(native_console)
                # Сохраняем title для родной консоли
                if title:
                    self._console_titles[native_console] = title
                else:
                    # Авто-генерация title если не указан
                    if native_console not in self._console_titles:
                        self._console_titles[native_console] = process_name
            
            # Добавляем получателей
            console_list.extend(recipients_list)
            
            self._process_consoles[process_name] = console_list
            
            if self.logger:
                if enabled and recipients_list:
                    self.logger.info(
                        f"✅ Console configured for {process_name}: "
                        f"native console + {len(recipients_list)} recipient(s)",
                        module="console"
                    )
                elif enabled:
                    self.logger.info(
                        f"✅ Console configured for {process_name}: native console only",
                        module="console"
                    )
                elif recipients_list:
                    self.logger.info(
                        f"✅ Console configured for {process_name}: "
                        f"{len(recipients_list)} recipient(s) only",
                        module="console"
                    )
    
    def create_process_console(self, process_name: str) -> bool:
        """
        Создать консоли для процесса (родную и получателей).
        
        Args:
            process_name: Имя процесса
            
        Returns:
            True если хотя бы одна консоль создана
        """
        with self._lock:
            if process_name not in self._process_consoles:
                return False
            
            console_names = self._process_consoles[process_name]
            if not console_names:
                return False
            
            created_any = False
            
            # Создаем все необходимые консоли
            for console_name in console_names:
                # Если консоль уже существует, пропускаем
                if console_name in self._console_queues:
                    continue
                
                # Получаем title для консоли
                title = self._console_titles.get(console_name, console_name)
                
                # Создаем queue и процесс консоли
                output_queue = Queue(maxsize=1000)
                console_proc = Process(
                    target=ConsoleManager._run_console_window,
                    args=(title, [console_name], output_queue),
                    name=f"Console-{console_name}"
                )
                console_proc.start()
                
                self._console_queues[console_name] = output_queue
                self._console_processes[console_name] = console_proc
                created_any = True
                
                if self.logger:
                    self.logger.info(
                        f"✅ Console created: {title} ({console_name})",
                        module="console"
                    )
            
            return created_any
    
    # ========================================================================
    # СОЗДАНИЕ ОТДЕЛЬНЫХ КАНАЛОВ
    # ========================================================================
    
    def create_custom_channel(
        self,
        name: str,
        title: Optional[str] = None
    ) -> Queue:
        """
        Создать отдельный канал консоли для специальных сообщений.
        
        Args:
            name: Имя канала (будет использоваться в роутере)
            title: Заголовок окна консоли (None = name)
            
        Returns:
            Queue для отправки сообщений в консоль
            
        Example:
            # Создаем канал для уведомлений
            queue = console_manager.create_custom_channel(
                name="notifications",
                title="System Notifications"
            )
            
            # Отправляем сообщение
            queue.put(('stdout', 'Новое уведомление!\n'), block=False)
        """
        with self._lock:
            if name in self._custom_channels:
                return self._custom_channels[name]
            
            output_queue = Queue(maxsize=1000)
            console_title = title or name
            
            console_proc = Process(
                target=ConsoleManager._run_console_window,
                args=(console_title, [name], output_queue),
                name=f"Console-{name}"
            )
            console_proc.start()
            
            self._custom_channels[name] = output_queue
            self._console_processes[f"custom_{name}"] = console_proc
            
            if self.logger:
                self.logger.info(f"✅ Custom console channel created: {name}", module="console")
            
            return output_queue
    
    # ========================================================================
    # ПЕРЕНАПРАВЛЕНИЕ ВЫВОДА
    # ========================================================================
    
    def setup_redirect(self, process_name: str) -> Optional[ConsoleRedirector]:
        """
        Настроить перенаправление stdout/stderr для процесса.
        
        Создает redirector который будет писать во все консоли процесса
        (родную и получателей).
        
        Args:
            process_name: Имя процесса
            
        Returns:
            ConsoleRedirector или None
        """
        with self._lock:
            if process_name not in self._process_consoles:
                return None
            
            console_names = self._process_consoles[process_name]
            if not console_names:
                return None
            
            # Собираем все queues для процесса
            queues = []
            for console_name in console_names:
                queue = self._console_queues.get(console_name)
                if queue:
                    queues.append(queue)
            
            if not queues:
                return None
            
            # Создаем redirector с множественными получателями
            redirector = ConsoleRedirector(queues, process_name)
            self._redirectors[process_name] = redirector
            
            return redirector
    
    # ========================================================================
    # ИНТЕГРАЦИЯ С ROUTER
    # ========================================================================
    
    def register_in_router(self, router_manager, prefix: str = "console") -> List[str]:
        """
        Зарегистрировать все каналы консоли в RouterManager.
        
        Создает каналы:
        - console.{process_name} - для каждого процесса
        - console.group.{group_name} - для групп
        - console.all - для всех консолей
        - console.{custom_name} - для кастомных каналов
        
        Args:
            router_manager: Экземпляр RouterManager
            prefix: Префикс для имен каналов
            
        Returns:
            Список зарегистрированных каналов
            
        Example:
            channels = console_manager.register_in_router(router_manager)
            # Теперь можно отправлять:
            router.send({
                'channel': 'console.Worker1',
                'text': 'Привет!',
                'level': 'INFO'
            })
        """
        registered = []
        
        with self._lock:
            # Каналы для процессов (в родную консоль процесса)
            for process_name in self._process_consoles.keys():
                if self._process_has_native.get(process_name, False):
                    channel_name = f"{prefix}.{process_name}"
                    channel = ConsoleChannel(
                        name=channel_name,
                        console_manager=self,
                        target_process=process_name
                    )
                    if router_manager.register_channel(channel):
                        registered.append(channel_name)
            
            # Каналы для консолей-получателей (если это не родные консоли процессов)
            processed_native_consoles = set()
            for process_name in self._process_consoles.keys():
                if self._process_has_native.get(process_name, False):
                    processed_native_consoles.add(process_name)
            
            for console_name in self._console_queues.keys():
                # Пропускаем если это родная консоль процесса (для них уже созданы каналы выше)
                if console_name in processed_native_consoles:
                    continue
                # Это консоль-получатель или кастомная консоль - создаем канал
                channel_name = f"{prefix}.{console_name}"
                channel = ConsoleChannel(
                    name=channel_name,
                    console_manager=self,
                    target_console=console_name
                )
                if router_manager.register_channel(channel):
                    registered.append(channel_name)
            
            # Общий канал (broadcast во все консоли)
            if self._console_queues or self._custom_channels:
                channel_name = f"{prefix}.all"
                channel = ConsoleChannel(
                    name=channel_name,
                    console_manager=self,
                    target_process=None,
                    target_console=None
                )
                if router_manager.register_channel(channel):
                    registered.append(channel_name)
            
            # Кастомные каналы
            for custom_name in self._custom_channels.keys():
                channel_name = f"{prefix}.{custom_name}"
                # Создаем специальный канал для кастомного
                custom_channel = _CustomConsoleChannel(
                    name=channel_name,
                    console_manager=self,
                    custom_channel_name=custom_name
                )
                if router_manager.register_channel(custom_channel):
                    registered.append(channel_name)
        
        if self.logger:
            self.logger.info(f"✅ Registered {len(registered)} console channels in router", module="console")
        
        return registered
    
    def get_custom_channel_queue(self, channel_name: str) -> Optional[Queue]:
        """
        Получить queue для кастомного канала.
        
        Args:
            channel_name: Имя кастомного канала
            
        Returns:
            Queue или None
        """
        with self._lock:
            return self._custom_channels.get(channel_name)
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def get_queue(self, process_name: str) -> Optional[Queue]:
        """
        Получить queue для родной консоли процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            Queue родной консоли или None
        """
        with self._lock:
            # Возвращаем queue родной консоли (если есть)
            if process_name in self._console_queues:
                return self._console_queues[process_name]
            return None
    
    def get_all_queues(self, process_name: str) -> List[Queue]:
        """
        Получить все queues для процесса (родная + получатели).
        
        Args:
            process_name: Имя процесса
            
        Returns:
            Список queues
        """
        with self._lock:
            queues = []
            if process_name not in self._process_consoles:
                return queues
            
            for console_name in self._process_consoles[process_name]:
                queue = self._console_queues.get(console_name)
                if queue:
                    queues.append(queue)
            
            return queues
    
    def get_status(self, process_name: str) -> Dict:
        """
        Получить статус консоли процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            Словарь со статусом
        """
        with self._lock:
            has_native = self._process_has_native.get(process_name, False)
            recipients = self._process_recipients.get(process_name, [])
            console_names = self._process_consoles.get(process_name, [])
            
            # Проверяем какие консоли созданы
            created_consoles = [
                name for name in console_names 
                if name in self._console_queues
            ]
            
            native_title = None
            if has_native and process_name in self._console_titles:
                native_title = self._console_titles[process_name]
            
            return {
                'has_native_console': has_native,
                'has_console': len(created_consoles) > 0,
                'native_title': native_title or (process_name if has_native else None),
                'recipients': recipients,
                'all_consoles': console_names,
                'created_consoles': created_consoles
            }
    
    def close_all(self):
        """Закрыть все консоли"""
        with self._lock:
            # Закрываем redirectors
            for process_name, redirector in list(self._redirectors.items()):
                redirector.close()
                import sys
                sys.stdout = redirector.original_stdout
                sys.stderr = redirector.original_stderr
            self._redirectors.clear()
            
            # Закрываем все консоли процессов
            for console_name in list(self._console_processes.keys()):
                self._close_console(console_name)
            
            # Закрываем кастомные каналы
            for custom_name in list(self._custom_channels.keys()):
                self._close_custom_channel(custom_name)
            
            # Очищаем конфигурации
            self._process_consoles.clear()
            self._process_recipients.clear()
            self._process_has_native.clear()
            self._console_titles.clear()
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # ========================================================================
    
    @staticmethod
    def _run_console_window(title: str, process_names: List[str], output_queue: Queue):
        """Запуск процесса консоли (статический метод для pickle)"""
        console = ConsoleWindowProcess(title, process_names, output_queue)
        console.run()
    
    def _send_text_to_queue(
        self,
        text: str,
        target_process: Optional[str] = None,
        target_console: Optional[str] = None
    ) -> bool:
        """Отправить текст в queue (используется ConsoleChannel)"""
        return self._send_to_console(text, target_process, target_console)
    
    def _send_to_console(
        self,
        text: str,
        target_process: Optional[str] = None,
        target_console: Optional[str] = None
    ) -> bool:
        """Отправить текст в queue (внутренний метод)"""
        try:
            if target_process:
                # Отправляем в родную консоль процесса
                queue = self._console_queues.get(target_process)
                if queue:
                    queue.put(('stdout', text), block=False)
                    return True
            elif target_console:
                # Отправляем в конкретную консоль
                queue = self._console_queues.get(target_console)
                if queue:
                    queue.put(('stdout', text), block=False)
                    return True
            else:
                # Broadcast - все консоли и кастомные каналы
                for queue in self._console_queues.values():
                    try:
                        queue.put(('stdout', text), block=False)
                    except Exception:
                        pass
                for queue in self._custom_channels.values():
                    try:
                        queue.put(('stdout', text), block=False)
                    except Exception:
                        pass
                return True
            return False
        except Exception:
            return False
    
    def _send_to_custom_channel(self, channel_name: str, text: str) -> bool:
        """Отправить в кастомный канал"""
        queue = self._custom_channels.get(channel_name)
        if queue:
            queue.put(('stdout', text), block=False)
            return True
        return False
    
    def _close_console(self, console_name: str):
        """Закрыть консоль"""
        if console_name in self._console_processes:
            proc = self._console_processes[console_name]
            try:
                proc.terminate()
                proc.join(timeout=2.0)
            except Exception:
                pass
            del self._console_processes[console_name]
        
        if console_name in self._console_queues:
            try:
                self._console_queues[console_name].put(('close', ''), block=False)
            except Exception:
                pass
            del self._console_queues[console_name]
    
    def _close_custom_channel(self, channel_name: str):
        """Закрыть кастомный канал"""
        if channel_name in self._custom_channels:
            try:
                self._custom_channels[channel_name].put(('close', ''), block=False)
            except Exception:
                pass
            del self._custom_channels[channel_name]
        
        proc_key = f"custom_{channel_name}"
        if proc_key in self._console_processes:
            proc = self._console_processes[proc_key]
            try:
                proc.terminate()
                proc.join(timeout=2.0)
            except Exception:
                pass
            del self._console_processes[proc_key]

