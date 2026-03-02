# -*- coding: utf-8 -*-
"""
Тонкий фасад регистров: только пути к пакетам и вызовы фреймворка.

Вся логика discovery и регистрации схем инкапсулирована в data_schema_module:
- discover_registers_from_package(package_name, suffix) — универсально для *Registers и *Data;
- register_package_schemas(package_name, suffix) — регистрация в SchemaManager.

Для другого процесса достаточно указать свои registers_package и data_package.
"""
from typing import Any, Dict, Optional

from multiprocess_framework.refactored.modules.data_schema_module import (
    RegistersContainer,
    discover_registers_from_package,
    register_package_schemas,
)
from App.Registers.models.field_registers.data_schema import RegistersContainerMetadataMixin


# Пакеты по умолчанию для этого приложения; в другом процессе можно передать свои
DEFAULT_REGISTERS_PACKAGE = "App.Registers.models.field_registers"
DEFAULT_DATA_PACKAGE = "App.Registers.models.field_data"


class RegistersManager(RegistersContainer, RegistersContainerMetadataMixin):
    """
    Контейнер регистров с делегированием метаданных в экземпляры *Registers.
    Discovery и регистрация дата-схем выполняются фреймворком по именам пакетов.
    """
    def __init__(
        self,
        registers_package: str = DEFAULT_REGISTERS_PACKAGE,
        data_package: Optional[str] = DEFAULT_DATA_PACKAGE,
        translation_manager: Optional[Any] = None,
    ):
        register_map = discover_registers_from_package(registers_package, suffix="Registers")
        if not register_map:
            raise RuntimeError(
                f"Не удалось обнаружить модели регистров в пакете {registers_package!r}. "
                "Убедитесь, что пакет доступен и экспортирует классы *Registers."
            )
        super().__init__(register_map)
        if data_package:
            register_package_schemas(data_package, suffix="Data")
        self._translation_manager = translation_manager

    def get_field_description(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return RegistersContainerMetadataMixin.get_field_description(
            self, register_name, field_name,
            language=language,
            translation_manager=kwargs.get("translation_manager") or self._translation_manager,
        )

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return RegistersContainerMetadataMixin.get_field_metadata(
            self, register_name, field_name,
            language=language,
            translation_manager=kwargs.get("translation_manager") or self._translation_manager,
        )


__all__ = ["RegistersManager", "DEFAULT_REGISTERS_PACKAGE", "DEFAULT_DATA_PACKAGE"]
