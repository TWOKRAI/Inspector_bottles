# -*- coding: utf-8 -*-
"""
Публичный контракт frontend_module.

Единственный файл, от которого разрешено зависеть другим модулям.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable


@runtime_checkable
class SupportsCommandMessage(Protocol):
    """
    Фабрика outbound COMMAND (например MessageAdapter).

    Возвращаемый объект должен иметь to_dict() для передачи в send_message (Dict at Boundary).
    """

    def command(
        self,
        targets: Union[List[str], str],
        command: str,
        args: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        need_ack: bool = False,
        priority: Any = "normal",
        **kwargs: Any,
    ) -> Any:
        """Собрать сообщение типа command; результат — объект с методом to_dict().

        Единый конверт (Ф7 G.2): payload под ``data``; явный ``data`` приоритетнее ``args``.
        """


@runtime_checkable
class IRouterLike(Protocol):
    """
    Протокол объекта, способного отправлять сообщения в backend.

    ProcessModule реализует этот контракт: send_message делегирует в
    ProcessCommunication → RouterManager. FrontendManager принимает router: IRouterLike.
    """

    def send_message(self, target: str, msg: Dict[str, Any]) -> bool:
        """Отправить сообщение целевому процессу. Возвращает True при успехе."""


@runtime_checkable
class IRegistersManager(Protocol):
    """
    Протокол менеджера регистров.

    Виджеты получают данные и метаданные через этот интерфейс.
    Реализации: registers_module.RegistersManager, RegistersContainer.
    """

    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Метаданные поля (min, max, unit, routing, access_level и т.д.)."""

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> tuple[bool, Optional[str]]:
        """Валидация значения поля. Возвращает (is_valid, error_message)."""


@runtime_checkable
class IRegistersManagerGui(Protocol):
    """
    Минимальный интерфейс для GUI (компоненты контролов, вкладки, register_ops).

    Расширяет чтение (`get_register`, `get_field_metadata`) записью `set_field_value`.
    Реализации: registers_module.RegistersManager, FrontendRegistersBridge.
    """

    def set_field_value(self, register_name: str, field_name: str, value: Any) -> tuple[bool, Optional[str]]:
        """Записать значение поля; (success, error_message)."""

    def get_register(self, register_name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""

    def get_field_metadata(self, register_name: str, field_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Метаданные поля (min, max, unit и т.д.)."""


@runtime_checkable
class IConfigurableWidget(Protocol):
    """
    Протокол виджета, привязанного к регистру.

    Виджет знает register_name и field_name, получает/устанавливает
    значение через IRegistersManager.
    """

    @property
    def register_name(self) -> Optional[str]:
        """Имя регистра."""

    @property
    def field_name(self) -> Optional[str]:
        """Имя поля."""

    def get_field_value(self) -> Any:
        """Получить текущее значение поля из регистра."""

    def set_field_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """Установить значение с валидацией. Возвращает (success, error_message)."""


@runtime_checkable
class IWidgetFactory(Protocol):
    """
    Протокол фабрики виджетов.

    Создаёт виджет по дескриптору (dict или SchemaBase).
    """

    def create(
        self,
        widget_type: str,
        descriptor: Dict[str, Any],
        registers_manager: Optional[IRegistersManager] = None,
        parent: Optional[Any] = None,
    ) -> Optional[Any]:
        """
        Создать виджет.

        Args:
            widget_type: Тип виджета (slider, checkbox, table, ...)
            descriptor: Параметры виджета (register_name, field_name, ...)
            registers_manager: Менеджер регистров для привязки
            parent: Родительский виджет

        Returns:
            Созданный виджет или None
        """


@runtime_checkable
class IWidgetRegistry(Protocol):
    """
    Протокол реестра типов виджетов.

    Регистрирует фабрики по типу виджета.
    """

    def register(self, widget_type: str, factory: IWidgetFactory) -> None:
        """Зарегистрировать фабрику для типа виджета."""

    def get_factory(self, widget_type: str) -> Optional[IWidgetFactory]:
        """Получить фабрику по типу."""

    def list_types(self) -> List[str]:
        """Список зарегистрированных типов виджетов."""


@runtime_checkable
class ISignalProvider(Protocol):
    """
    Протокол виджета, предоставляющего каталог своих сигналов.

    Виджет реализует get_signal_map() для подключения к backend/другим виджетам
    по конфигу signal_bindings без необходимости знать внутреннюю структуру класса.
    """

    def get_signal_map(self) -> Dict[str, Any]:
        """Возвращает {signal_name: signal_object} для подключения."""


@runtime_checkable
class IWindowRegistry(Protocol):
    """
    Протокол реестра окон.

    Регистрирует фабрики окон по имени.
    """

    def register(self, window_name: str, factory: Any) -> None:
        """Зарегистрировать фабрику окна."""

    def create(self, window_name: str, **kwargs: Any) -> Optional[Any]:
        """Создать окно по имени."""

    def list_windows(self) -> List[str]:
        """Список зарегистрированных окон."""


@runtime_checkable
class IFrontendManager(Protocol):
    """
    Протокол менеджера frontend (BaseManager).

    Единая точка входа: регистры, конфиг, окна, потоки.
    """

    def get_registers(self) -> Any:
        """FrontendRegistersBridge (IRegistersManager)."""

    def get_window_manager(self) -> Optional[Any]:
        """WindowManager или None."""

    def get_thread_manager(self) -> Optional[Any]:
        """ThreadManager или None."""

    def get_config(self) -> Dict[str, Any]:
        """Текущий конфиг."""

    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфиг (hot-reload)."""

    def set_connection_map(self, connection_map: Dict[str, str]) -> None:
        """Привязка регистров к backend-каналам."""


# ---------------------------------------------------------------------------
# Механизм вкладок (NEW-D1) — публичный API реестра табов.
# ---------------------------------------------------------------------------
#
# Generic-механизм: приложение описывает вкладки как ``list[TabSpec]`` в своём
# composition root и строит их через ``TabRegistry``. Реестр не знает
# конкретных вкладок и не импортирует прикладной слой (0 обратных импортов).
# Реэкспорт здесь — чтобы контракт модуля был виден из единого interfaces.py;
# импортировать можно и напрямую из ``frontend_module.tabs``.
from multiprocess_framework.modules.frontend_module.tabs import (  # noqa: E402
    AccessContextSource,
    LazyTab,
    PlaceholderFactory,
    TabRegistry,
    TabSpec,
)

__all__ = [
    # Протоколы контракта модуля (объявлены выше в этом файле).
    "SupportsCommandMessage",
    "IRouterLike",
    "IRegistersManager",
    "IRegistersManagerGui",
    "IConfigurableWidget",
    "IWidgetFactory",
    "IWidgetRegistry",
    "ISignalProvider",
    "IWindowRegistry",
    "IFrontendManager",
    # Механизм вкладок (NEW-D1, реэкспорт из frontend_module.tabs).
    "TabSpec",
    "TabRegistry",
    "LazyTab",
    "AccessContextSource",
    "PlaceholderFactory",
]
