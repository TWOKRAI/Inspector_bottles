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
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

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
