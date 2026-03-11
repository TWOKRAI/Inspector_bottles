"""
error_module — публичный контракт (interfaces.py).

Единственный файл, от которого должны зависеть другие модули.
Не импортировать напрямую из core/ или config/ снаружи модуля.
"""

from typing import Optional, Any, Union, Dict, Protocol, runtime_checkable


@runtime_checkable
class IErrorManager(Protocol):
    """Интерфейс менеджера ошибок."""

    def error(self, message: str, module: str = "errors") -> None:
        """Записать сообщение уровня ERROR."""
        ...

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """Логировать исключение с опциональным traceback."""
        ...

    def initialize(self) -> bool:
        """Инициализация менеджера. Возвращает True при успехе."""
        ...

    def shutdown(self) -> None:
        """Корректное завершение работы."""
        ...


# Типы для type hints при передаче конфигурации
ErrorConfigLike = Union[Dict[str, Any], Any]
"""
Конфиг ErrorManager:
- dict: напрямую используется
- объект с build() -> (str, dict): вызывается build()
- None: используется дефолтный конфиг
"""
