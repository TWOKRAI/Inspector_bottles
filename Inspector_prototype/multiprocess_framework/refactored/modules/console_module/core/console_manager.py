"""
ConsoleManager - менеджер консольных окон с интеграцией всех модулей системы.

Поддерживает два режима работы:
- Встроенный режим: консоль в процессе (опционально включается/выключается)
- Отдельный процесс: создается через ProcessManager для отладки

Интегрируется с:
- BaseManager для единообразия
- CommandManager для обработки команд
- RouterManager для отправки сообщений
- ProcessManager для создания отдельного процесса
"""
import sys
import threading
import queue
from typing import Dict, Optional, List, Set, Any, Union, TYPE_CHECKING
from multiprocessing import Process, Queue
from datetime import datetime

if TYPE_CHECKING:
    from multiprocessing import Process as ProcessType

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager
from ..interfaces import IConsoleManager
from ..redirectors.console_redirector import ConsoleRedirector
from ..channels.console_channel import ConsoleChannel
from ..processes.window_process import ConsoleWindowProcess


class ConsoleManager(BaseManager, ObservableMixin, IConsoleManager):
    """
    Менеджер консольных окон с интеграцией всех модулей системы.
    
    Особенности:
    - Наследуется от BaseManager для единообразия
    - Использует ObservableMixin для логирования и метрик
    - Два режима работы: встроенный и отдельный процесс
    - Интеграция с CommandManager для обработки команд
    - Интеграция с RouterManager для отправки сообщений
    - Перенаправление stdout/stderr
    - Интерактивный режим (опционально)
    
    Attributes:
        _enabled: Включена ли консоль
        _interactive: Интерактивный режим
        _redirect_enabled: Включено ли перенаправление stdout/stderr
        _redirector: ConsoleRedirector для перенаправления вывода
        _output_queue: Queue для вывода в консоль (встроенный режим)
        _input_queue: Queue для ввода команд (интерактивный режим)
        _command_manager: CommandManager для обработки команд
        _router_manager: RouterManager для отправки сообщений
        _input_thread: Поток для чтения ввода (интерактивный режим)
        _console_process: Процесс консоли (для отдельного процесса)
    """
    
    def __init__(
        self,
        manager_name: str = "ConsoleManager",
        process: Optional["ProcessType"] = None,
        command_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        enabled: bool = False,
        interactive: bool = False,
        redirect_enabled: bool = False,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        enable_logging: bool = True,
        enable_error_tracking: bool = True,
        enable_statistics: bool = True,
        **kwargs
    ):
        """
        Инициализация ConsoleManager.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс
            command_manager: CommandManager для обработки команд
            router_manager: RouterManager для отправки сообщений
            enabled: Включить консоль при инициализации
            interactive: Включить интерактивный режим
            redirect_enabled: Включить перенаправление stdout/stderr
            managers: Словарь менеджеров для ObservableMixin
            config: Конфигурация для ObservableMixin
            enable_logging: Включить логирование
            enable_error_tracking: Включить отслеживание ошибок
            enable_statistics: Включить статистику
            **kwargs: Дополнительные параметры
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Подготовка менеджеров для ObservableMixin
        if managers is None:
            managers = {}
        
        if config is None:
            config = {
                'logger': enable_logging,
                'error': enable_error_tracking,
                'statistics': enable_statistics
            }
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=True
        )
        
        # Сохраняем зависимости
        self._command_manager = command_manager
        self._router_manager = router_manager
        
        # Состояние консоли
        self._enabled = False
        self._interactive = False
        self._redirect_enabled = False
        
        # Очереди для встроенного режима
        self._output_queue: Optional[Queue] = None
        self._input_queue: Optional[Queue] = None
        
        # Перенаправитель вывода
        self._redirector: Optional[ConsoleRedirector] = None
        
        # Поток для интерактивного ввода
        self._input_thread: Optional[threading.Thread] = None
        self._input_thread_running = False
        
        # Поток для отображения вывода (встроенный режим)
        self._output_thread: Optional[threading.Thread] = None
        self._output_thread_running = False
        
        # Процесс консоли (для отдельного процесса)
        self._console_process: Optional[Process] = None
        self._console_process_queue: Optional[Queue] = None
        
        # Блокировка для потокобезопасности
        self._lock = threading.Lock()
        
        # Включаем консоль если указано
        if enabled:
            self.enable_console(enabled=True)
        
        # Включаем интерактивный режим если указано
        if interactive:
            self.enable_interactive(enabled=True)
        
        # Включаем перенаправление если указано
        if redirect_enabled:
            self.setup_redirect(enabled=True)
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация ConsoleManager.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Если консоль включена, создаем очереди
            if self._enabled:
                self._create_queues()
            
            self.is_initialized = True
            self._log_info(f"ConsoleManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize ConsoleManager: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы ConsoleManager.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Отключаем консоль
            self.enable_console(enabled=False)
            
            # Останавливаем интерактивный режим
            self.enable_interactive(enabled=False)
            
            # Отключаем перенаправление
            self.setup_redirect(enabled=False)
            
            # Останавливаем поток вывода
            self._stop_output_thread()
            
            # Закрываем отдельный процесс если есть
            if self._console_process:
                self._close_console_process()
            
            self.is_initialized = False
            self._log_info("ConsoleManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"Error during ConsoleManager shutdown: {e}")
            return False
    
    # ========================================================================
    # РЕАЛИЗАЦИЯ IConsoleManager - ОСНОВНОЙ API
    # ========================================================================
    
    def enable_console(self, enabled: bool = True) -> bool:
        """
        Включить/выключить консоль в процессе.
        
        Args:
            enabled: Включить или выключить
        
        Returns:
            bool: True если операция успешна
        """
        with self._lock:
            if enabled == self._enabled:
                return True
            
            if enabled:
                # Включаем консоль
                self._create_queues()
                self._start_output_thread()
                self._enabled = True
                self._log_info("Console enabled")
            else:
                # Выключаем консоль
                self._stop_output_thread()
                self._close_queues()
                self._enabled = False
                self._log_info("Console disabled")
            
            return True
    
    def is_console_enabled(self) -> bool:
        """Проверить включена ли консоль."""
        return self._enabled
    
    def send_message(self, text: str, level: str = "INFO", **kwargs) -> bool:
        """
        Отправить сообщение в консоль.
        
        Args:
            text: Текст сообщения
            level: Уровень логирования (INFO, WARNING, ERROR, DEBUG)
            **kwargs: Дополнительные параметры
        
        Returns:
            bool: True если сообщение отправлено
        """
        if not self._enabled or not self._output_queue:
            return False
        
        try:
            formatted_text = self._format_message(text, level, kwargs.get('timestamp', False))
            self._output_queue.put(('stdout', formatted_text), block=False)
            return True
        except Exception as e:
            self._log_error(f"Failed to send message: {e}")
            return False
    
    def register_in_router(self, router_manager, prefix: str = "console") -> List[str]:
        """
        Зарегистрировать каналы консоли в RouterManager.
        
        Args:
            router_manager: Экземпляр RouterManager
            prefix: Префикс для имен каналов
        
        Returns:
            Список зарегистрированных каналов
        """
        registered = []
        
        if not router_manager:
            return registered
        
        with self._lock:
            # Канал для текущего процесса
            if self._enabled:
                channel_name = f"{prefix}.{self.manager_name}"
                channel = ConsoleChannel(
                    name=channel_name,
                    console_manager=self,
                    target_process=self.manager_name
                )
                if router_manager.register_channel(channel):
                    registered.append(channel_name)
                    self._log_info(f"Registered console channel: {channel_name}")
        
        return registered
    
    def setup_redirect(self, enabled: bool = True) -> bool:
        """
        Настроить перенаправление stdout/stderr.
        
        Args:
            enabled: Включить или выключить перенаправление
        
        Returns:
            bool: True если операция успешна
        """
        with self._lock:
            if enabled == self._redirect_enabled:
                return True
            
            if enabled:
                # Включаем перенаправление
                if not self._enabled:
                    self._log_warning("Cannot enable redirect: console is not enabled")
                    return False
                
                if not self._output_queue:
                    self._create_queues()
                
                # Создаем redirector
                self._redirector = ConsoleRedirector(
                    output_queues=[self._output_queue],
                    process_name=self.manager_name
                )
                
                # Перенаправляем stdout/stderr
                sys.stdout = self._redirector
                sys.stderr = self._redirector
                
                self._redirect_enabled = True
                self._log_info("Redirect enabled")
            else:
                # Выключаем перенаправление
                if self._redirector:
                    self._redirector.restore()
                    self._redirector.close()
                    self._redirector = None
                
                self._redirect_enabled = False
                self._log_info("Redirect disabled")
            
            return True
    
    def create_debug_process(
        self,
        process_name: str,
        process_manager,
        router_manager,
        command_manager
    ) -> bool:
        """
        Создать отдельный процесс для отладки через ProcessManager.
        
        Создает отдельный процесс консоли через ProcessManager.
        В этом процессе будет только ConsoleManager для приема сообщений и вывода.
        
        Args:
            process_name: Имя процесса
            process_manager: ProcessManagerCore для создания процесса
            router_manager: RouterManager для отправки сообщений
            command_manager: CommandManager для обработки команд
        
        Returns:
            bool: True если процесс создан успешно
        """
        if not process_manager:
            self._log_error("ProcessManager not provided")
            return False
        
        try:
            # Создаем отдельный процесс консоли через ProcessManager
            # Используем ConsoleWindowProcess для отображения
            output_queue = Queue(maxsize=1000)
            
            console_proc = Process(
                target=ConsoleManager._run_console_window,
                args=(process_name, [process_name], output_queue),
                name=f"Console-{process_name}"
            )
            console_proc.start()
            
            self._console_process = console_proc
            self._console_process_queue = output_queue
            
            self._log_info(f"Debug console process created: {process_name}")
            return True
        
        except Exception as e:
            self._log_error(f"Failed to create debug process: {e}")
            return False
    
    @staticmethod
    def _run_console_window(title: str, process_names: List[str], output_queue: Queue):
        """
        Запуск процесса консоли (статический метод для pickle).
        
        Args:
            title: Заголовок окна консоли
            process_names: Список имен процессов
            output_queue: Queue для получения данных
        """
        console = ConsoleWindowProcess(title, process_names, output_queue)
        console.run()
    
    # ========================================================================
    # ИНТЕРАКТИВНЫЙ РЕЖИМ
    # ========================================================================
    
    def enable_interactive(self, enabled: bool = True) -> bool:
        """
        Включить/выключить интерактивный режим.
        
        Args:
            enabled: Включить или выключить
        
        Returns:
            bool: True если операция успешна
        """
        with self._lock:
            if enabled == self._interactive:
                return True
            
            if enabled:
                # Включаем интерактивный режим
                if not self._enabled:
                    self._log_warning("Cannot enable interactive: console is not enabled")
                    return False
                
                if not self._input_queue:
                    self._input_queue = Queue(maxsize=100)
                
                # Запускаем поток для чтения ввода
                self._input_thread_running = True
                self._input_thread = threading.Thread(
                    target=self._read_input_loop,
                    name=f"ConsoleInput-{self.manager_name}",
                    daemon=True
                )
                self._input_thread.start()
                
                self._interactive = True
                self._log_info("Interactive mode enabled")
            else:
                # Выключаем интерактивный режим
                self._input_thread_running = False
                if self._input_thread:
                    self._input_thread.join(timeout=1.0)
                    self._input_thread = None
                
                if self._input_queue:
                    self._input_queue = None
                
                self._interactive = False
                self._log_info("Interactive mode disabled")
            
            return True
    
    def _read_input_loop(self):
        """
        Цикл чтения ввода из консоли (для интерактивного режима).
        
        Читает команды из stdin и обрабатывает через CommandManager.
        """
        if not self._command_manager:
            self._log_warning("CommandManager not available for interactive mode")
            return
        
        while self._input_thread_running:
            try:
                # Читаем команду из stdin
                try:
                    command = input().strip()
                except (EOFError, KeyboardInterrupt):
                    break
                
                if not command:
                    continue
                
                # Обрабатываем через CommandManager
                try:
                    message = {
                        'command': command,
                        'source': 'console',
                        'process': self.manager_name
                    }
                    
                    result = self._command_manager.handle_command(message)
                    
                    # Отправляем результат в консоль
                    if result:
                        result_text = str(result)
                        self.send_message(f"Result: {result_text}", level="INFO")
                    else:
                        self.send_message("Command executed", level="INFO")
                
                except Exception as e:
                    self.send_message(f"Error: {str(e)}", level="ERROR")
            
            except Exception as e:
                self._log_error(f"Error in input loop: {e}")
                break
    
    def _start_output_thread(self):
        """Запустить поток для отображения вывода."""
        if self._output_thread_running:
            return
        
        if not self._output_queue:
            return
        
        self._output_thread_running = True
        self._output_thread = threading.Thread(
            target=self._output_display_loop,
            name=f"ConsoleOutput-{self.manager_name}",
            daemon=True
        )
        self._output_thread.start()
    
    def _stop_output_thread(self):
        """Остановить поток отображения вывода."""
        self._output_thread_running = False
        if self._output_thread:
            self._output_thread.join(timeout=1.0)
            self._output_thread = None
    
    def _output_display_loop(self):
        """
        Цикл отображения вывода из очереди в консоль процесса.
        
        Читает сообщения из очереди и выводит их в stdout процесса.
        """
        while self._output_thread_running:
            try:
                if not self._output_queue:
                    break
                
                try:
                    stream_type, data = self._output_queue.get(timeout=0.1)
                    
                    if stream_type == 'close':
                        break
                    elif stream_type == 'flush':
                        sys.stdout.flush()
                        sys.stderr.flush()
                    elif stream_type in ('stdout', 'stderr'):
                        if stream_type == 'stdout':
                            sys.stdout.write(data)
                            sys.stdout.flush()
                        else:
                            sys.stderr.write(data)
                            sys.stderr.flush()
                
                except queue.Empty:
                    continue
                except Exception as e:
                    self._log_error(f"Error in output display loop: {e}")
                    break
            
            except Exception as e:
                self._log_error(f"Error in output display loop: {e}")
                break
        
        self._output_thread_running = False
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def _create_queues(self):
        """Создать очереди для консоли."""
        if not self._output_queue:
            self._output_queue = Queue(maxsize=1000)
    
    def _close_queues(self):
        """Закрыть очереди консоли."""
        if self._output_queue:
            try:
                self._output_queue.put(('close', ''), block=False)
            except Exception:
                pass
            self._output_queue = None
    
    def _close_console_process(self):
        """Закрыть отдельный процесс консоли."""
        if self._console_process:
            try:
                if self._console_process_queue:
                    self._console_process_queue.put(('close', ''), block=False)
                self._console_process.terminate()
                self._console_process.join(timeout=2.0)
            except Exception:
                pass
            self._console_process = None
            self._console_process_queue = None
    
    def _format_message(self, text: str, level: str = 'INFO', add_timestamp: bool = False) -> str:
        """Форматирование сообщения для консоли."""
        parts = []
        
        if add_timestamp:
            parts.append(f"[{datetime.now().strftime('%H:%M:%S')}]")
        
        if level and level.upper() != 'INFO':
            parts.append(f"[{level.upper()}]")
        
        parts.append(text)
        
        formatted = " ".join(parts)
        if not formatted.endswith('\n'):
            formatted += '\n'
        
        return formatted
    
    def _send_to_console(
        self,
        text: str,
        target_process: Optional[str] = None,
        target_console: Optional[str] = None
    ) -> bool:
        """
        Отправить текст в консоль (внутренний метод).
        
        Args:
            text: Текст для отправки
            target_process: Имя процесса (для родной консоли)
            target_console: Имя консоли (для конкретной консоли)
        
        Returns:
            bool: True если отправлено успешно
        """
        try:
            if target_process and target_process == self.manager_name:
                # Отправляем в свою консоль
                if self._output_queue:
                    self._output_queue.put(('stdout', text), block=False)
                    return True
            elif target_console:
                # Отправляем в конкретную консоль (для отдельного процесса)
                if self._console_process_queue:
                    self._console_process_queue.put(('stdout', text), block=False)
                    return True
            else:
                # Отправляем в свою консоль по умолчанию
                if self._output_queue:
                    self._output_queue.put(('stdout', text), block=False)
                    return True
            
            return False
        except Exception:
            return False
    
    # ========================================================================
    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def get_output_queue(self) -> Optional[Queue]:
        """Получить очередь вывода (для использования в других компонентах)."""
        return self._output_queue
    
    def get_input_queue(self) -> Optional[Queue]:
        """Получить очередь ввода (для интерактивного режима)."""
        return self._input_queue
    
    def is_interactive(self) -> bool:
        """Проверить включен ли интерактивный режим."""
        return self._interactive
    
    def is_redirect_enabled(self) -> bool:
        """Проверить включено ли перенаправление stdout/stderr."""
        return self._redirect_enabled

