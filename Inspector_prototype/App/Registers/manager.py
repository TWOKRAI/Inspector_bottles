# -*- coding: utf-8 -*-
"""
RegistersManager — тонкий фасад регистров для App Inspector.

Поддерживает два режима обнаружения регистров:

1. Режим пакета (по умолчанию, обратная совместимость):
        discover_registers_from_package("App.Registers.models.registers")
        Читает __init__.py и __all__ пакета.

2. Режим сканирования директории (рекомендуется):
        RegistersScanner.scan_directory("App/Registers/models/registers")
        Не требует ручного обновления __init__.py — добавь файл и он подхватится.
        Передаётся через параметр scan_path:
            rm = RegistersManager(scan_path=Path(__file__).parent / "models/registers")

    При использовании scan_path регистры также автоматически регистрируются
    в ProcessRegistersRegistry под именем auto_register_as (по умолчанию "app_process").

Observer API (реактивность без Qt-зависимости):
    Позволяет нескольким виджетам или другим потребителям подписаться на изменение
    конкретного поля регистра.  Framework-слой остаётся свободен от Qt.

    # Подписка на конкретное поле (UI-компонент):
        rm.subscribe("draw", "dp", my_widget._update_value_silent)

    # Подписка на все поля сразу (например, router-хук в main_window):
        rm.subscribe_all(self._on_any_register_changed)

    # Отмена подписки:
        rm.unsubscribe("draw", "dp", my_widget._update_value_silent)
        rm.unsubscribe_all(self._on_any_register_changed)

    # Установить значение + уведомить всех подписчиков:
        rm.set_field_value("draw", "dp", 1.8)

    # Только уведомить (значение уже обновлено снаружи):
        rm.notify_field_changed("draw", "dp", 1.8)
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from multiprocess_framework.refactored.modules.data_schema_module import (
    RegistersContainer,
    RegistersScanner,
    ProcessRegistersRegistry,
    RegistersMeta,
    discover_registers_from_package,
    register_package_schemas,
)

# Пакеты по умолчанию для App Inspector
DEFAULT_REGISTERS_PACKAGE = "App.Registers.models.registers"
DEFAULT_DATA_PACKAGE = "App.Registers.models.data"

# Путь к папке с регистрами (для scan_path режима)
DEFAULT_REGISTERS_DIR = Path(__file__).parent / "models" / "registers"


class RegistersManager(RegistersContainer):
    """
    Контейнер регистров App Inspector.

    Расширяет RegistersContainer:
        - задаёт пакеты и пути по умолчанию
        - поддерживает режим scan_path (без ручного __init__.py)
        - хранит translation_manager для локализации метаданных
        - при scan_path регистрирует себя в ProcessRegistersRegistry
        - реактивный observer-паттерн без Qt-зависимостей

    Параметры:
        registers_package:  Пакет с *Registers-классами (режим пакета).
                            Игнорируется, если передан scan_path.
        data_package:       Пакет с *Data-классами (регистрируются в SchemaManager).
        translation_manager: Менеджер переводов для локализации.
        scan_path:          Путь к директории с .py файлами регистров.
                            Если передан — используется RegistersScanner вместо
                            discover_registers_from_package.
        auto_register_as:   Имя процесса для регистрации в ProcessRegistersRegistry.
                            Если пустая строка — в реестр не регистрируется.
                            Используется только при scan_path.
        process_meta:       RegistersMeta для ProcessRegistersRegistry.
                            Если None — создаётся базовый с display_name=auto_register_as.
    """

    def __init__(
        self,
        registers_package: str = DEFAULT_REGISTERS_PACKAGE,
        data_package: Optional[str] = DEFAULT_DATA_PACKAGE,
        translation_manager: Optional[Any] = None,
        scan_path: "Path | str | None" = None,
        auto_register_as: str = "app_process",
        process_meta: "RegistersMeta | None" = None,
    ) -> None:
        if scan_path is not None:
            register_map = RegistersScanner.scan_directory(
                scan_path, suffix="Registers"
            )
            if not register_map:
                raise RuntimeError(
                    f"Не удалось обнаружить *Registers-модели в директории {scan_path!r}. "
                    "Убедитесь, что директория содержит .py файлы с классами *Registers."
                )
        else:
            register_map = discover_registers_from_package(
                registers_package, suffix="Registers"
            )
            if not register_map:
                raise RuntimeError(
                    f"Не удалось обнаружить модели регистров в пакете {registers_package!r}. "
                    "Убедитесь, что пакет доступен и экспортирует классы *Registers в __all__."
                )

        super().__init__(register_map)

        # Регистрируем дата-схемы в SchemaManager для использования через ModelFactory
        if data_package:
            register_package_schemas(data_package, suffix="Data")

        self._translation_manager = translation_manager

        # Observer storage — нет Qt-зависимости, любой callable подходит.
        # Поле-специфичные: (register_name, field_name) -> [callback(value)]
        self._field_observers: dict[Tuple[str, str], List[Callable[[Any], None]]] = defaultdict(list)
        # Глобальные: [callback(register_name, field_name, value)]
        self._global_observers: List[Callable[[str, str, Any], None]] = []

        # Регистрируем контейнер в глобальном реестре процессов
        if scan_path is not None and auto_register_as:
            meta = process_meta or RegistersMeta(
                display_name=auto_register_as,
                process_type="main",
            )
            registry = ProcessRegistersRegistry()
            # Безопасная регистрация: если уже зарегистрирован — обновляем
            if registry.has_process(auto_register_as):
                registry.update_process(auto_register_as, container=self, meta=meta)
            else:
                registry.register_process(auto_register_as, self, meta=meta)

    # =========================================================================
    # Observer API — подписка / отмена / уведомление
    # =========================================================================

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Подписать callback(value) на изменение конкретного поля.

        Можно подписать несколько callbacks на одно поле — все получат уведомление.
        Повторная подписка одного и того же объекта игнорируется.
        """
        key = (register_name, field_name)
        if callback not in self._field_observers[key]:
            self._field_observers[key].append(callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Отписать callback от изменений конкретного поля."""
        key = (register_name, field_name)
        try:
            self._field_observers[key].remove(callback)
        except ValueError:
            pass

    def subscribe_all(
        self,
        callback: Callable[[str, str, Any], None],
    ) -> None:
        """Подписать callback(register_name, field_name, value) на любое изменение.

        Используется, например, router-хуком в main_window для отправки
        любого изменения регистра в бэкенд через RouterManager.
        """
        if callback not in self._global_observers:
            self._global_observers.append(callback)

    def unsubscribe_all(
        self,
        callback: Callable[[str, str, Any], None],
    ) -> None:
        """Отписать глобальный observer."""
        try:
            self._global_observers.remove(callback)
        except ValueError:
            pass

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Установить значение поля в регистре и уведомить всех подписчиков.

        Единственная точка записи значений в регистры.
        Pydantic validate_assignment=True автоматически проверит ограничения.

        Returns:
            (True, None) при успехе, (False, error_message) при ошибке.
        """
        register = self.get_register(register_name)
        if register is None:
            return False, f"Регистр '{register_name}' не найден"
        if not hasattr(register, field_name):
            return False, f"Поле '{field_name}' не найдено в регистре '{register_name}'"
        try:
            setattr(register, field_name, value)
        except Exception as exc:
            return False, str(exc)
        self._notify_observers(register_name, field_name, value)
        return True, None

    def notify_field_changed(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить ТОЛЬКО field-специфичных подписчиков об изменении.

        Используется слайдером когда:
          - значение уже установлено в модели через setattr (или будет
            отправлено на бэкенд напрямую через send_register_update),
          - нужно лишь синхронизировать другие UI-компоненты на том же поле.

        НЕ вызывает глобальные observers (subscribe_all) — чтобы не дублировать
        отправку в роутер, если слайдер уже делает это самостоятельно.

        Для полного fan-out (model + UI + backend + DB) используй set_field_value().
        """
        self._notify_field_observers(register_name, field_name, value)

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Алиас для validate_field — обратная совместимость с ConfigurableWidget."""
        return self.validate_field(register_name, field_name, value, access_level)

    def _notify_field_observers(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить только field-специфичных подписчиков (без глобальных)."""
        for cb in list(self._field_observers.get((register_name, field_name), [])):
            try:
                cb(value)
            except Exception:
                pass

    def _notify_observers(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить все подписанные callbacks: field-специфичные + глобальные.

        Итерируемся по копии списка — безопасно если callback отпишется в процессе.
        Исключения в callbacks подавляются, чтобы один сломанный подписчик
        не прерывал уведомление остальных.
        """
        self._notify_field_observers(register_name, field_name, value)

        for cb in list(self._global_observers):
            try:
                cb(register_name, field_name, value)
            except Exception:
                pass

    # =========================================================================
    # Переопределяем get_field_metadata / get_field_description
    # для автоматической подстановки translation_manager
    # =========================================================================

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        lang: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Метаданные поля с учётом translation_manager."""
        tm = kwargs.get("translation_manager") or self._translation_manager
        return super().get_field_metadata(register_name, field_name, lang, tm)

    def get_field_description(
        self,
        register_name: str,
        field_name: str,
        lang: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Описание поля с учётом translation_manager."""
        tm = kwargs.get("translation_manager") or self._translation_manager
        return super().get_field_description(register_name, field_name, lang, tm)


__all__ = [
    "RegistersManager",
    "DEFAULT_REGISTERS_PACKAGE",
    "DEFAULT_DATA_PACKAGE",
    "DEFAULT_REGISTERS_DIR",
]
