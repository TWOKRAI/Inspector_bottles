"""
ConsoleManager — менеджер терминальных окон процесса.

Ответственность:
  - Управление основным терминалом (show/hide/write/read_input)
  - Управление дополнительными терминалами (create_console/close_console)
  - Делегирование платформо-зависимых операций в IPlatformConsole

ConsoleManager НЕ логирует, НЕ парсит команды, НЕ маршрутизирует.
"""
import threading
from typing import Callable, Dict, List, Optional, Any, TYPE_CHECKING

from ...base_manager import BaseManager, ObservableMixin
from ..interfaces import IConsoleManager, IPlatformConsole
from ..platforms import create_platform_console
from ..configs.console_config import ConsoleConfig

if TYPE_CHECKING:
    from ..redirectors.console_redirector import ConsoleRedirector


class ConsoleManager(BaseManager, ObservableMixin, IConsoleManager):
    """
    Менеджер терминальных окон.

    Наследование: BaseManager + ObservableMixin + IConsoleManager

    Конфигурация принимается как ConsoleConfig (только внутри модуля).
    На границах процессов — dict (ADR-008).

    Attributes:
        _platform:        Основной терминал (IPlatformConsole)
        _consoles:        Дополнительные терминалы {name: IPlatformConsole}
        _config:          ConsoleConfig
        _input_callback:  Callback для строк ввода
        _input_thread:    Поток чтения stdin
        _redirector:      ConsoleRedirector или None
        _lock:            threading.Lock для thread-safety
    """

    def __init__(
        self,
        manager_name: str = "ConsoleManager",
        process: Optional[Any] = None,
        config: Optional[ConsoleConfig] = None,
        managers: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config={},
            auto_proxy=True,
        )

        self._config: ConsoleConfig = config or ConsoleConfig()
        self._platform: IPlatformConsole = create_platform_console()
        self._consoles: Dict[str, IPlatformConsole] = {}

        self._input_callback: Optional[Callable[[str], None]] = None
        self._input_thread: Optional[threading.Thread] = None
        self._input_thread_running: bool = False

        self._redirector: Optional["ConsoleRedirector"] = None
        self._lock = threading.Lock()

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация: создать и показать терминал согласно конфигу."""
        try:
            if self._config.enabled:
                title = self._config.title or self.manager_name
                self._platform.create(title)
                self._platform.show()

            if self._config.redirect_stdout:
                self.setup_redirect(True)

            # interactive запускается позже из ConsoleAdapter после связки с CommandManager
            self.is_initialized = True
            self._log_info(f"ConsoleManager '{self.manager_name}' initialized")
            return True
        except Exception as exc:
            self._log_error(f"ConsoleManager init failed: {exc}")
            return False

    def shutdown(self) -> bool:
        """Остановить input loop, восстановить stdout, закрыть терминалы."""
        try:
            self.disable_input()
            self.setup_redirect(False)
            with self._lock:
                for name, console in list(self._consoles.items()):
                    try:
                        console.close()
                    except Exception:
                        pass
                self._consoles.clear()
            self._platform.close()
            self.is_initialized = False
            self._log_info("ConsoleManager shutdown completed")
            return True
        except Exception as exc:
            self._log_error(f"ConsoleManager shutdown error: {exc}")
            return False

    # =========================================================================
    # IConsoleManager — основной терминал
    # =========================================================================

    def show(self) -> bool:
        return self._platform.show()

    def hide(self) -> bool:
        return self._platform.hide()

    def is_visible(self) -> bool:
        return self._platform.is_visible()

    def write(
        self,
        text: str,
        level: str = "INFO",
        console_name: Optional[str] = None,
    ) -> bool:
        with self._lock:
            if console_name and console_name in self._consoles:
                return self._consoles[console_name].write(text)
            return self._platform.write(text)

    # =========================================================================
    # IConsoleManager — дополнительные терминалы
    # =========================================================================

    def create_console(self, name: str, title: str = "") -> bool:
        if not self._platform.supports_multiple_windows():
            self._log_warning(
                f"Platform does not support multiple windows; "
                f"cannot create console '{name}'"
            )
            return False
        with self._lock:
            if name in self._consoles:
                return True
            new_console = create_platform_console()
            new_console.create(title or name)
            self._consoles[name] = new_console
            self._log_info(f"Created additional console '{name}'")
            return True

    def close_console(self, name: str) -> bool:
        with self._lock:
            if name not in self._consoles:
                return False
            try:
                self._consoles.pop(name).close()
            except Exception:
                pass
            self._log_info(f"Closed console '{name}'")
            return True

    def list_consoles(self) -> List[str]:
        with self._lock:
            return list(self._consoles.keys())

    # =========================================================================
    # IConsoleManager — input loop
    # =========================================================================

    def enable_input(self, callback: Callable[[str], None]) -> bool:
        """Запустить чтение stdin в отдельном daemon-потоке."""
        if self._input_thread_running:
            return True
        self._input_callback = callback
        self._input_thread_running = True
        self._input_thread = threading.Thread(
            target=self._input_loop,
            name=f"ConsoleInput-{self.manager_name}",
            daemon=True,
        )
        self._input_thread.start()
        self._log_info("Input loop started")
        return True

    def disable_input(self) -> bool:
        """Остановить поток чтения stdin."""
        self._input_thread_running = False
        if self._input_thread and self._input_thread.is_alive():
            self._input_thread.join(timeout=1.0)
        self._input_thread = None
        self._input_callback = None
        return True

    def _input_loop(self) -> None:
        """Блокирующее чтение строк из _platform и вызов callback."""
        while self._input_thread_running:
            line = self._platform.read_input()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            if self._input_callback:
                try:
                    self._input_callback(line)
                except Exception as exc:
                    self._log_error(f"Input callback error: {exc}")
        self._input_thread_running = False

    # =========================================================================
    # IConsoleManager — перенаправление stdout/stderr
    # =========================================================================

    def setup_redirect(self, enabled: bool = True) -> bool:
        if enabled:
            if self._redirector is not None:
                return True
            from ..redirectors.console_redirector import ConsoleRedirector
            import sys
            self._redirector = ConsoleRedirector(self)
            sys.stdout = self._redirector  # type: ignore[assignment]
            sys.stderr = self._redirector  # type: ignore[assignment]
            self._log_info("stdout/stderr redirected to ConsoleManager")
            return True
        else:
            if self._redirector is not None:
                self._redirector.restore()
                self._redirector = None
            return True

    # =========================================================================
    # Совместимость с существующим кодом (backward compat helpers)
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        base = super().get_stats()
        base.update({
            "enabled": self._config.enabled,
            "interactive": self._config.interactive,
            "visible": self._platform.is_visible(),
            "consoles": list(self._consoles.keys()),
            "redirect_active": self._redirector is not None,
            "input_running": self._input_thread_running,
        })
        return base

    def get_debug_info(self) -> Dict[str, Any]:
        return {
            "manager_name": self.manager_name,
            "config": self._config.model_dump(),
            "platform": type(self._platform).__name__,
            "consoles": list(self._consoles.keys()),
            "redirect_active": self._redirector is not None,
            "input_running": self._input_thread_running,
        }
