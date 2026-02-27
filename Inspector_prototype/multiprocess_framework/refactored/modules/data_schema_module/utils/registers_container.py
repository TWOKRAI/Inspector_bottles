# -*- coding: utf-8 -*-
"""
Универсальный контейнер регистров.

Назначение:
- Хранить экземпляры Pydantic-моделей *Registers, собранные по mapping'у.
- Предоставлять единый API: model_dump_all / model_validate_all / get_register / reset_all.

Этот класс НЕ знает ничего о метаданных, i18n и TranslationManager —
только о значениях регистров. Логика метаданных реализуется на уровне приложения.
"""
from typing import Dict, Any, Optional, Type

from pydantic import BaseModel


class RegistersContainer:
    """
    Универсальный контейнер для регистров (Pydantic-моделей).

    Регистры передаются через mapping имя_регистра -> класс модели.
    Контейнер создаёт экземпляры моделей и предоставляет базовые операции.
    """

    def __init__(self, register_map: Dict[str, Type[BaseModel]]):
        """
        Args:
            register_map: Словарь {имя_регистра: класс_модели}.
        """
        self._register_map: Dict[str, Type[BaseModel]] = dict(register_map)
        for name, model_class in self._register_map.items():
            setattr(self, name, model_class())

    @classmethod
    def from_package(cls, package_name: str) -> "RegistersContainer":
        """
        Создать контейнер, автоматически обнаружив все *Registers в пакете.

        Args:
            package_name: Имя пакета (например, "App.Registers.models").
        """
        from ..registry.register_discovery import discover_registers_from_package

        register_map = discover_registers_from_package(package_name)
        return cls(register_map)

    def _register_names(self) -> list[str]:
        return list(self._register_map.keys())

    def register_names(self) -> list[str]:
        """Список имён зарегистрированных регистров."""
        return self._register_names()

    def get_register(self, name: str) -> Optional[Any]:
        """
        Получить регистр по имени.

        Args:
            name: Имя регистра (например, 'camera', 'processing').
        """
        return getattr(self, name, None)

    def model_dump_all(self) -> Dict[str, Any]:
        """
        Экспорт всех регистров в словарь.

        Returns:
            dict: {имя_регистра: dict данных модели}
        """
        return {name: getattr(self, name).model_dump() for name in self._register_names()}

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """
        Загрузка всех регистров из словаря.

        Args:
            data: Снимок {имя_регистра: dict данных}.
            strict: Режим строгой валидации Pydantic.
        """
        for name in self._register_names():
            if name in data:
                model_class = self._register_map[name]
                setattr(self, name, model_class.model_validate(data[name], strict=strict))

    def reset_all(self) -> None:
        """Сбросить все регистры к значениям по умолчанию."""
        for name, model_class in self._register_map.items():
            setattr(self, name, model_class())

    def validate_all(self) -> bool:
        """
        Валидация всех регистров.

        Returns:
            True если все регистры успешно сериализуются в dict.
        """
        try:
            self.model_dump_all()
            return True
        except Exception:
            return False

