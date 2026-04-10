# -*- coding: utf-8 -*-
"""
RegistersContainer — универсальный контейнер для набора *Registers-моделей.

Хранит экземпляры Pydantic-моделей (SchemaBase/RegisterBase или BaseModel),
предоставляет единый API:
    - ядро контейнера  — register_names, get_register, __getattr__,
                         __iter__, __len__, __contains__
    - делегирование    — get_field_meta, get_field_metadata, validate_field, ...
    - сериализация     — to_dict / from_dict / to_json / from_json / to_yaml / from_yaml
    - синхронизация    — diff() — что изменилось с момента snapshot-а
    - персистентность  — save / load через ISchemaStorage

Доступ к регистрам:
    container.draw          → DrawRegisters instance (через __getattr__)
    container["camera"]     → CameraRegisters instance (через __getitem__)
    container["cam"] = inst → заменить экземпляр (через __setitem__)
    "draw" in container     → True (через __contains__)
    for name, reg in container: ...  (через __iter__)
    len(container)          → кол-во регистров

Единственный источник правды — self._registers.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Type, cast

from pydantic import BaseModel

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


class RegistersContainer:
    """
    Контейнер для набора *Registers-моделей.

    Регистры передаются через {имя: класс_модели}.
    Единственный источник правды — _registers dict.
    """

    def __init__(self, register_map: dict[str, Any]) -> None:
        """
        Args:
            register_map: {имя_регистра: класс_модели | экземпляр_модели}
                          Класс — создаётся ``model_class()``; экземпляр — сохраняется как есть
                          (для runtime-менеджеров вроде ``RegistersManager``).
        """
        self._register_map: dict[str, Type[BaseModel]] = {}
        self._registers: dict[str, BaseModel] = {}
        for name, val in dict(register_map or {}).items():
            if isinstance(val, type) and issubclass(val, BaseModel):
                model_class = cast(Type[BaseModel], val)
                self._register_map[name] = model_class
                self._registers[name] = model_class()
            elif isinstance(val, BaseModel):
                self._register_map[name] = type(val)
                self._registers[name] = val
            else:
                raise TypeError(
                    f"Регистр '{name}': ожидается подкласс BaseModel или экземпляр, "
                    f"получено {type(val)!r}"
                )

    @classmethod
    def from_package(cls, package_name: str) -> "RegistersContainer":
        """Создать контейнер, автоматически обнаружив все *Registers в пакете."""
        from ..registry.discovery import discover_registers_from_package
        return cls(discover_registers_from_package(package_name))

    # =========================================================================
    # Ядро контейнера
    # =========================================================================

    def __getattr__(self, name: str) -> BaseModel:
        """
        Атрибутный доступ к регистрам: container.draw → DrawRegisters instance.

        Вызывается только когда атрибут не найден стандартным способом.
        """
        try:
            registers = object.__getattribute__(self, "_registers")
            return registers[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' не содержит регистр '{name}'. "
                f"Доступные: {list(registers.keys())}"
            )

    def __getitem__(self, name: str) -> BaseModel:
        """Доступ через индекс: container["draw"] → DrawRegisters instance."""
        try:
            return self._registers[name]
        except KeyError:
            raise KeyError(f"Регистр '{name}' не найден в контейнере.")

    def __setitem__(self, name: str, reg: BaseModel) -> None:
        """Установить или заменить экземпляр регистра (имя → модель)."""
        if not isinstance(reg, BaseModel):
            raise TypeError(f"Ожидается экземпляр BaseModel, получено {type(reg)!r}")
        self._register_map[name] = type(reg)
        self._registers[name] = reg

    def __contains__(self, name: str) -> bool:
        """'draw' in container → True/False."""
        return name in self._registers

    def __iter__(self) -> Iterator[tuple[str, BaseModel]]:
        """for name, reg in container: ..."""
        return iter(self._registers.items())

    def __len__(self) -> int:
        """len(container) → кол-во зарегистрированных регистров."""
        return len(self._registers)

    def __repr__(self) -> str:
        names = list(self._registers.keys())
        return f"{type(self).__name__}({names})"

    def register_names(self) -> list[str]:
        """Список имён зарегистрированных регистров."""
        return list(self._register_map.keys())

    def get_register(self, name: str) -> BaseModel | None:
        """Получить экземпляр регистра по имени (или None)."""
        return self._registers.get(name)

    def has_register(self, name: str) -> bool:
        """Проверить наличие регистра с данным именем."""
        return name in self._registers

    # =========================================================================
    # Делегирование методов SchemaMixin
    # =========================================================================

    def _as_mixin(self, register_name: str) -> Any:
        """Вернуть регистр как SchemaMixin или None."""
        from ..core.schema_mixin import SchemaMixin
        reg = self._registers.get(register_name)
        return reg if isinstance(reg, SchemaMixin) else None

    def get_field_meta(self, register_name: str, field_name: str) -> Any:
        """FieldMeta поля регистра (или None)."""
        reg = self._as_mixin(register_name)
        return reg.get_field_meta(field_name) if reg else None

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        lang: str | None = None,
        translation_manager: Any = None,
    ) -> dict[str, Any]:
        """Словарь метаданных поля: description, info, min, max, unit и т.д."""
        reg = self._as_mixin(register_name)
        return (
            reg.get_field_metadata(field_name, lang, translation_manager)
            if reg
            else {}
        )

    def get_field_description(
        self,
        register_name: str,
        field_name: str,
        lang: str | None = None,
        translation_manager: Any = None,
    ) -> str:
        """Описание / info поля регистра."""
        reg = self._as_mixin(register_name)
        return (
            reg.get_field_description(field_name, lang, translation_manager)
            if reg
            else ""
        )

    def can_modify_field(
        self,
        register_name: str,
        field_name: str,
        access_level: int = 0,
    ) -> bool:
        """True если поле разрешено к изменению."""
        reg = self._as_mixin(register_name)
        return reg.can_modify_field(field_name, access_level) if reg else True

    def validate_field(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        access_level: int = 0,
    ) -> tuple[bool, str | None]:
        """Проверить значение поля регистра."""
        reg = self._as_mixin(register_name)
        return reg.validate_field(field_name, value, access_level) if reg else (True, None)

    def get_all_metadata(
        self,
        access_level: int = 0,
        lang: str | None = None,
    ) -> dict[str, dict[str, dict]]:
        """
        Метаданные всех полей всех регистров.

        Возвращает {register_name: {field_name: metadata_dict}}.
        """
        from ..core.schema_mixin import SchemaMixin
        return {
            name: reg.get_fields_for_access_level(access_level)
            for name, reg in self._registers.items()
            if isinstance(reg, SchemaMixin)
        }

    # =========================================================================
    # Сериализация и синхронизация
    # =========================================================================

    def model_dump_all(self) -> dict[str, Any]:
        """
        Все регистры как вложенный словарь:
        {"draw": {"dp": 1.4, ...}, "camera": {...}, ...}
        """
        return {name: reg.model_dump() for name, reg in self._registers.items()}

    def model_validate_all(
        self,
        data: dict[str, Any],
        strict: bool = False,
    ) -> None:
        """
        Загрузить значения всех регистров из словаря (in-place обновление).

        Незнакомые имена регистров пропускаются.
        """
        for name, values in data.items():
            if name not in self._register_map:
                continue
            model_class = self._register_map[name]
            self._registers[name] = model_class.model_validate(values, strict=strict)

    def reset_all(self) -> None:
        """Сбросить все регистры к значениям по умолчанию."""
        for name, model_class in self._register_map.items():
            self._registers[name] = model_class()

    def validate_all(self) -> bool:
        """Проверить, что все регистры сериализуются без ошибок."""
        try:
            self.model_dump_all()
            return True
        except Exception:
            return False

    def diff(self, reference: dict[str, Any]) -> dict[str, Any]:
        """
        Вернуть только изменённые поля по сравнению с reference.

        reference — словарь в формате model_dump_all() (snapshot прошлого состояния).
        Возвращает {register_name: {field: new_value}} только для изменённых полей.

        Использование для эффективной синхронизации с Router:
            snapshot = container.to_dict()
            # ... пользователь меняет параметры ...
            changes = container.diff(snapshot)
            router.send_batch(changes)
        """
        current = self.model_dump_all()
        result: dict[str, Any] = {}
        for name, values in current.items():
            ref_values = reference.get(name, {})
            changed = {
                k: v
                for k, v in values.items()
                if k not in ref_values or ref_values[k] != v
            }
            if changed:
                result[name] = changed
        return result

    def snapshot(self) -> dict[str, Any]:
        """
        Создать snapshot текущего состояния для последующего diff().

        Эквивалент to_dict(), но с явным семантическим смыслом.
        """
        return self.model_dump_all()

    # =========================================================================
    # Ввод / вывод (встроенный IO слой)
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать все регистры в словарь."""
        return self.model_dump_all()

    def from_dict(self, data: dict[str, Any]) -> None:
        """Обновить все регистры из словаря (in-place)."""
        self.model_validate_all(data)

    def to_json(self, indent: int = 2) -> str:
        """Сериализовать все регистры в JSON-строку."""
        return json.dumps(
            self.model_dump_all(),
            indent=indent,
            ensure_ascii=False,
            default=str,
        )

    def from_json(self, json_str: str) -> None:
        """Обновить все регистры из JSON-строки (in-place)."""
        self.model_validate_all(json.loads(json_str))

    def to_yaml(self) -> str:
        """Сериализовать все регистры в YAML-строку."""
        if not _HAS_YAML:
            raise ImportError("pyyaml не установлен. Выполните: pip install pyyaml")
        return _yaml.dump(
            self.model_dump_all(),
            allow_unicode=True,
            default_flow_style=False,
        )

    def from_yaml(self, yaml_str: str) -> None:
        """Обновить все регистры из YAML-строки (in-place)."""
        if not _HAS_YAML:
            raise ImportError("pyyaml не установлен. Выполните: pip install pyyaml")
        self.model_validate_all(_yaml.safe_load(yaml_str))

    # =========================================================================
    # Персистентное хранение через ISchemaStorage
    # =========================================================================

    def save(self, storage: Any, container_name: str) -> None:
        """
        Сохранить все регистры через объект хранилища.

        storage — любой объект, реализующий ISchemaStorage (FileStorage, ...)
        container_name — имя, под которым сохраняются данные.
        """
        storage.save(container_name, self.model_dump_all())

    def load(self, storage: Any, container_name: str) -> bool:
        """
        Загрузить регистры из хранилища (in-place).

        Возвращает True если данные найдены и загружены.
        """
        data = storage.load(container_name)
        if not data:
            return False
        self.model_validate_all(data)
        return True
