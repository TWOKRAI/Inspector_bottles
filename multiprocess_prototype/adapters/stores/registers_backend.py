# -*- coding: utf-8 -*-
"""
adapters/stores/registers_backend.py — адаптер RegistersManager → RegistersBackend Protocol.

RegistersBackendFromManager оборачивает RegistersManager и реализует domain Protocol
RegistersBackend: get_field_specs / get_value / set_value по координатам
(process_name, plugin_index).

Variant A (решение Q4): adapter знает TopologyRepository + PluginCatalog и
резолвит (process_name, plugin_index) → register_name через:
    1. topology_repo.load() — текущая Topology
    2. topology.processes → process.plugins[plugin_index].plugin_name
    3. plugin_catalog.resolve(plugin_name) → PluginSpec (гарантирует наличие в каталоге)
    4. register_name = plugin_name (convention: RegistersManager ключ == plugin_name)

Semantic mismatch (зафиксировано осознанно):
    - RegistersManager.get_fields(plugin_name) → list[FieldInfo] (framework dtype = type)
    - RegistersBackend.get_field_specs(...) → tuple[FieldSpec, ...] (domain dtype = str)
    - Маппинг: FieldInfo.field_type.__name__ если возможно, иначе str(field_type)

    - RegistersManager.set_field_value(register_name, field_name, value) → (bool, str|None)
    - RegistersManager не знает о (process_name, plugin_index) — это domain-координаты.
    - При set_field_value ошибка пишется в DomainError (не молчит).

    - get_value: RegistersManager.get_register(register_name) → Pydantic instance,
      затем getattr(reg, field) — стандартный Pydantic attribute access.

Phase E: label/metadata из FieldInfo.meta (FieldMeta.description, min, max, unit)
может быть проброшен в FieldSpec.label и metadata. Сейчас label = field_name.

Границы импортов:
    - Разрешено: domain.protocols, domain.errors, multiprocess_framework.modules.registers_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.4)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.registers_backend import FieldSpec, RegistersBackend

if TYPE_CHECKING:
    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.domain.protocols.plugin_catalog import PluginCatalog
    from multiprocess_prototype.domain.protocols.topology_repository import TopologyRepository


def _dtype_str(field_type: type | None) -> str:
    """Конвертировать Python type → строковое обозначение dtype.

    Маппинг: int → 'int', float → 'float', str → 'str',
    bool → 'bool', NoneType → 'Any', прочие → __name__ или str().
    """
    if field_type is None:
        return "Any"
    name = getattr(field_type, "__name__", None)
    return name if name else str(field_type)


class RegistersBackendFromManager:
    """Adapter поверх RegistersManager для domain RegistersBackend Protocol.

    Variant A (Q4): adapter знает TopologyRepository + PluginCatalog,
    резолвит plugin_index → plugin_name → register_name через топологию.

    Жизненный цикл:
        - topology_repo.load() вызывается при каждом методе (без кэша) —
          гарантирует актуальность topology при динамическом редактировании.
        - plugin_catalog.resolve(plugin_name) — read-only lookup, нет side-effects.
        - registers_manager — stateful: get_register / get_fields / set_field_value.

    Соглашение register_name == plugin_name (Convention-based):
        RegistersManager хранит регистры под ключом plugin_name (см. from_registry,
        build_rm_from_topology). Adapter использует эту конвенцию — register_name
        для RegistersManager == plugin_name из topology.plugins[i].plugin_name.
        Это convention, не явный mapping: если имена разойдутся в Phase E —
        здесь нужна таблица explicit mapping (register_class_name из PluginSpec.config_schema).
    """

    def __init__(
        self,
        registers_manager: "RegistersManager",
        topology_repo: "TopologyRepository",
        plugin_catalog: "PluginCatalog",
    ) -> None:
        """Инициализировать адаптер.

        Args:
            registers_manager: Инстанс RegistersManager (framework) для чтения/записи регистров.
            topology_repo: Реализация Protocol TopologyRepository для загрузки Topology.
            plugin_catalog: Реализация Protocol PluginCatalog для резолва plugin_name → PluginSpec.
        """
        self._rm = registers_manager
        self._topology_repo = topology_repo
        self._plugin_catalog = plugin_catalog

    # ------------------------------------------------------------------
    # Внутренние helpers
    # ------------------------------------------------------------------

    def _resolve_register_name(
        self,
        process_name: str,
        plugin_index: int,
    ) -> str:
        """Резолвить (process_name, plugin_index) → register_name через топологию + каталог.

        Алгоритм (Variant A):
            1. Загрузить текущую Topology через topology_repo.load().
            2. Найти Process по process_name.
            3. Проверить plugin_index в пределах plugins.
            4. Получить plugin_name = process.plugins[plugin_index].plugin_name.
            5. Проверить наличие плагина в plugin_catalog (гарантия что каталог знает).
            6. Вернуть plugin_name как register_name (convention: keys совпадают).

        Args:
            process_name: Имя процесса в топологии.
            plugin_index: Индекс плагина в process.plugins (0-based).

        Returns:
            Имя регистра (= plugin_name по конвенции).

        Raises:
            DomainError: process_name не найден, plugin_index вне диапазона,
                         plugin_name не найден в catalog.
        """
        topology = self._topology_repo.load()

        # Шаг 1: найти процесс
        process = topology.find_process(process_name)
        if process is None:
            raise DomainError(
                f"Процесс '{process_name}' не найден в топологии. "
                f"Доступные процессы: {[p.process_name for p in topology.processes]}"
            )

        # Шаг 2: проверить индекс плагина
        if plugin_index < 0 or plugin_index >= len(process.plugins):
            raise DomainError(
                f"plugin_index={plugin_index} вне диапазона для процесса '{process_name}' "
                f"(плагинов: {len(process.plugins)})"
            )

        # Шаг 3: получить plugin_name
        plugin_name = process.plugins[plugin_index].plugin_name

        # Шаг 4: проверить наличие в catalog (Variant A — обязательная валидация)
        spec = self._plugin_catalog.resolve(plugin_name)
        if spec is None:
            raise DomainError(
                f"Плагин '{plugin_name}' (process='{process_name}', "
                f"plugin_index={plugin_index}) не найден в PluginCatalog."
            )

        # Шаг 5: register_name == plugin_name (convention-based, см. docstring)
        return plugin_name

    # ------------------------------------------------------------------
    # RegistersBackend Protocol implementation
    # ------------------------------------------------------------------

    def get_field_specs(
        self,
        process_name: str,
        plugin_index: int,
    ) -> tuple[FieldSpec, ...]:
        """Получить описания полей для плагина по координатам (process_name, plugin_index).

        Делегирует в RegistersManager.get_fields(register_name) → list[FieldInfo].
        Если RegistersManager не знает о данном плагине (нет регистра) — возвращает ().

        Маппинг FieldInfo → FieldSpec:
            field_name → FieldSpec.name
            field_type.__name__ → FieldSpec.dtype (строковое обозначение)
            "" → FieldSpec.label (Phase E заполнит из FieldInfo.title)
            {} → FieldSpec.metadata (Phase E добавит min/max/unit из FieldInfo.meta)

        Args:
            process_name: Имя процесса в топологии.
            plugin_index: Индекс плагина в process.plugins (0-based).

        Returns:
            Tuple[FieldSpec, ...] — описания полей. Пустой tuple если регистр не найден.

        Raises:
            DomainError: process_name не найден или plugin_index вне диапазона.
        """
        register_name = self._resolve_register_name(process_name, plugin_index)

        # get_fields() возвращает [] если регистра нет — не бросает исключение
        field_infos = self._rm.get_fields(register_name)

        return tuple(
            FieldSpec(
                name=fi.field_name,
                dtype=_dtype_str(fi.field_type),
                # Phase E: label = fi.title (человекочитаемое из FieldMeta)
                label="",
                # Phase E: metadata = {"min": fi.min_value, "max": fi.max_value, "unit": fi.unit}
                metadata={},
            )
            for fi in field_infos
        )

    def get_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
    ) -> Any:
        """Получить текущее значение поля плагина.

        Доступ через RegistersManager.get_register(register_name) → Pydantic instance,
        затем getattr(reg, field). Если регистр не найден — DomainError.
        Если поле не найдено — KeyError (сигнализирует об отсутствующем поле).

        Args:
            process_name: Имя процесса в топологии.
            plugin_index: Индекс плагина в process.plugins (0-based).
            field: Имя поля регистра.

        Returns:
            Текущее значение поля.

        Raises:
            DomainError: process_name не найден, plugin_index вне диапазона,
                         plugin не в catalog, или регистр не найден в RegistersManager.
            KeyError: поле field отсутствует в регистре.
        """
        register_name = self._resolve_register_name(process_name, plugin_index)

        reg = self._rm.get_register(register_name)
        if reg is None:
            raise DomainError(
                f"Регистр '{register_name}' не найден в RegistersManager. "
                f"Плагин зарегистрирован в catalog, но не имеет регистра (нет register_classes?)."
            )

        if not hasattr(reg, field):
            raise KeyError(f"Поле '{field}' не найдено в регистре '{register_name}'.")

        return getattr(reg, field)

    def set_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
        value: Any,
    ) -> None:
        """Установить значение поля плагина.

        Делегирует в RegistersManager.set_field_value(register_name, field, value).
        При ошибке (not ok) бросает DomainError с сообщением от RegistersManager.

        Semantic mismatch:
            RegistersManager.set_field_value() возвращает (bool, str|None).
            Этот adapter конвертирует ошибку в DomainError для единообразия.

        Args:
            process_name: Имя процесса в топологии.
            plugin_index: Индекс плагина в process.plugins (0-based).
            field: Имя поля регистра.
            value: Новое значение.

        Raises:
            DomainError: process_name не найден, plugin_index вне диапазона,
                         plugin не в catalog, регистр не найден, или ошибка валидации.
        """
        register_name = self._resolve_register_name(process_name, plugin_index)

        ok, err_msg = self._rm.set_field_value(register_name, field, value)
        if not ok:
            raise DomainError(f"Ошибка set_value для '{register_name}.{field}' = {value!r}: {err_msg}")


# Проверка structural subtyping (import-time, не runtime-checkable)
_: RegistersBackend = RegistersBackendFromManager.__new__(RegistersBackendFromManager)  # type: ignore[assignment]


__all__ = [
    "RegistersBackendFromManager",
]
