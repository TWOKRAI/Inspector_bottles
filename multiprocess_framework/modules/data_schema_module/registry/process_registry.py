# -*- coding: utf-8 -*-
"""
ProcessRegistersRegistry — централизованный реестр регистров всех процессов.

Singleton. Каждый процесс регистрирует свой RegistersContainer с метаданными
(имя процесса, тип, версия, routing-канал и т.д.).

Реестр предоставляет:
    - единую точку учёта всех регистров системы
    - агрегацию метаданных: routing-каналы, форматы, версии
    - быстрый доступ к любому регистру по пути "process/register_name"
    - сводку (summary) для мониторинга и отладки
    - экспорт полного состояния системы в dict / JSON

Пример использования:

    # В основном (или любом другом) процессе:
    from multiprocess_framework.modules.data_schema_module import (
        ProcessRegistersRegistry, RegistersMeta
    )

    registry = ProcessRegistersRegistry()
    registry.register_process(
        "app_process",
        container,
        meta=RegistersMeta(display_name="Интерфейс", routing_channel="ui_control")
    )

    # Доступ к регистру из любого места:
    draw = registry.get_register("app_process", "draw")
    all_channels = registry.collect_routing_channels()
    summary = registry.summary()
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RegistersMeta:
    """
    Метаданные процесса при регистрации в ProcessRegistersRegistry.

    Attributes:
        display_name:    Человекочитаемое имя процесса ("App UI", "Camera Process").
        process_type:    Тип процесса ("main", "worker", "service", ...).
        routing_channel: Основной канал роутера для этого процесса.
        version:         Версия конфигурации регистров (для отслеживания миграций).
        tags:            Произвольные теги для группировки и фильтрации.
        extra:           Дополнительные произвольные метаданные.
    """

    display_name: str = ""
    process_type: str = "worker"
    routing_channel: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "process_type": self.process_type,
            "routing_channel": self.routing_channel,
            "version": self.version,
            "tags": list(self.tags),
            "extra": dict(self.extra),
        }


@dataclass
class _ProcessEntry:
    """Внутренняя запись зарегистрированного процесса."""

    process_name: str
    container: Any  # RegistersContainer
    meta: RegistersMeta


class ProcessRegistersRegistry:
    """
    Singleton-реестр RegistersContainer для всех процессов системы.

    Thread-safe: используется threading.Lock для параллельных регистраций.

    Создание Singleton:
        registry = ProcessRegistersRegistry()         # первый вызов — создание
        registry2 = ProcessRegistersRegistry()        # тот же объект

    Сброс (только для тестов):
        ProcessRegistersRegistry.reset()
    """

    _instance: "ProcessRegistersRegistry | None" = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "ProcessRegistersRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._processes: dict[str, _ProcessEntry] = {}
                    instance._registry_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Полностью сбросить Singleton (только для юнит-тестов!).

        Не вызывать в production-коде.
        """
        with cls._lock:
            cls._instance = None

    # =========================================================================
    # Регистрация процессов
    # =========================================================================

    def register_process(
        self,
        process_name: str,
        container: Any,
        meta: "RegistersMeta | None" = None,
    ) -> None:
        """
        Зарегистрировать контейнер регистров для процесса.

        Args:
            process_name: Уникальное имя процесса ("app_process", "camera_process").
            container:    Экземпляр RegistersContainer.
            meta:         Метаданные процесса (RegistersMeta). Если None — создаётся
                          базовый RegistersMeta с display_name=process_name.

        Raises:
            ValueError: Если process_name уже зарегистрирован.
        """
        with self._registry_lock:
            if process_name in self._processes:
                raise ValueError(
                    f"Процесс '{process_name}' уже зарегистрирован. Используйте update_process() для обновления."
                )
            self._processes[process_name] = _ProcessEntry(
                process_name=process_name,
                container=container,
                meta=meta or RegistersMeta(display_name=process_name),
            )
        logger.info(
            "ProcessRegistersRegistry: зарегистрирован процесс '%s' (%d регистров)",
            process_name,
            len(container),
        )

    def update_process(
        self,
        process_name: str,
        container: Any = None,
        meta: "RegistersMeta | None" = None,
    ) -> None:
        """
        Обновить контейнер или метаданные зарегистрированного процесса.

        Если process_name не существует — регистрирует как новый.
        Параметры container и meta опциональны: None означает "не менять".
        """
        with self._registry_lock:
            if process_name not in self._processes:
                self._processes[process_name] = _ProcessEntry(
                    process_name=process_name,
                    container=container,
                    meta=meta or RegistersMeta(display_name=process_name),
                )
                logger.info(
                    "ProcessRegistersRegistry: добавлен новый процесс '%s'",
                    process_name,
                )
                return

            entry = self._processes[process_name]
            if container is not None:
                entry.container = container
            if meta is not None:
                entry.meta = meta
        logger.debug("ProcessRegistersRegistry: обновлён процесс '%s'", process_name)

    def unregister_process(self, process_name: str) -> bool:
        """
        Удалить процесс из реестра.

        Returns:
            True если процесс был найден и удалён, False если не найден.
        """
        with self._registry_lock:
            if process_name in self._processes:
                del self._processes[process_name]
                logger.info(
                    "ProcessRegistersRegistry: снят с регистрации '%s'",
                    process_name,
                )
                return True
        return False

    # =========================================================================
    # Доступ к данным
    # =========================================================================

    @property
    def process_names(self) -> list[str]:
        """Имена всех зарегистрированных процессов."""
        return list(self._processes.keys())

    def get_container(self, process_name: str) -> Any:
        """
        Вернуть RegistersContainer для указанного процесса.

        Returns:
            RegistersContainer или None если процесс не найден.
        """
        entry = self._processes.get(process_name)
        return entry.container if entry else None

    def get_meta(self, process_name: str) -> "RegistersMeta | None":
        """Вернуть RegistersMeta для указанного процесса."""
        entry = self._processes.get(process_name)
        return entry.meta if entry else None

    def get_register(self, process_name: str, register_name: str) -> Any:
        """
        Получить конкретный регистр по имени процесса и имени регистра.

        Эквивалент: registry.get_container("app").draw
        Но с безопасным доступом и понятной ошибкой.

        Returns:
            Экземпляр RegisterBase/BaseModel или None.
        """
        container = self.get_container(process_name)
        if container is None:
            return None
        return container.get_register(register_name)

    def has_process(self, process_name: str) -> bool:
        """Проверить, зарегистрирован ли процесс."""
        return process_name in self._processes

    # =========================================================================
    # Агрегация метаданных
    # =========================================================================

    def collect_routing_channels(self) -> dict[str, str]:
        """
        Собрать routing_channel всех зарегистрированных процессов.

        Returns:
            {process_name: routing_channel}
            Пустой channel ("") пропускается.
        """
        return {
            name: entry.meta.routing_channel for name, entry in self._processes.items() if entry.meta.routing_channel
        }

    def collect_field_routing(self) -> dict[str, dict[str, dict]]:
        """
        Собрать routing-метаданные со всех полей всех регистров.

        Returns:
            {
                "process_name": {
                    "register_name.field_name": {routing_dict}
                }
            }
            Поля без routing пропускаются.
        """
        from ..core.schema_mixin import RegisterMixin

        result: dict[str, dict[str, dict]] = {}
        for proc_name, entry in self._processes.items():
            proc_routing: dict[str, dict] = {}
            for reg_name, reg in entry.container:
                if not isinstance(reg, RegisterMixin):
                    continue
                for field_name, meta in type(reg).get_all_fields_meta().items():
                    if meta and meta.routing:
                        key = f"{reg_name}.{field_name}"
                        proc_routing[key] = dict(meta.routing)
            if proc_routing:
                result[proc_name] = proc_routing
        return result

    def collect_all_registers_meta(self) -> dict[str, dict[str, Any]]:
        """
        Собрать метаданные всех регистров всех процессов.

        Returns:
            {
                "process_name": {
                    "register_name": {
                        "class": "DrawRegisters",
                        "fields": {"dp": {...}, ...}
                    }
                }
            }
        """
        from ..core.schema_mixin import RegisterMixin

        result: dict[str, dict[str, Any]] = {}
        for proc_name, entry in self._processes.items():
            proc_regs: dict[str, Any] = {}
            for reg_name, reg in entry.container:
                reg_info: dict[str, Any] = {
                    "class": type(reg).__name__,
                }
                if isinstance(reg, RegisterMixin):
                    fields_meta: dict[str, Any] = {}
                    for fn, meta in type(reg).get_all_fields_meta().items():
                        if meta:
                            fields_meta[fn] = {k: v for k, v in meta.to_dict().items() if v not in (None, "", {}, [])}
                    reg_info["fields"] = fields_meta
                else:
                    reg_info["fields"] = list(reg.model_fields.keys())
                proc_regs[reg_name] = reg_info
            result[proc_name] = proc_regs
        return result

    # =========================================================================
    # Сводка и экспорт
    # =========================================================================

    def summary(self) -> dict[str, Any]:
        """
        Краткая сводка реестра для мониторинга и отладки.

        Returns::

            {
                "total_processes": 3,
                "processes": {
                    "app_process": {
                        "display_name": "Интерфейс",
                        "process_type": "main",
                        "routing_channel": "ui_control",
                        "version": "1.0.0",
                        "tags": [],
                        "registers": ["draw", "camera", "conveyor"],
                        "total_registers": 3,
                    },
                    ...
                }
            }
        """
        processes: dict[str, Any] = {}
        for proc_name, entry in self._processes.items():
            reg_names = list(entry.container.register_names())
            processes[proc_name] = {
                **entry.meta.to_dict(),
                "registers": reg_names,
                "total_registers": len(reg_names),
            }
        return {
            "total_processes": len(self._processes),
            "processes": processes,
        }

    def export_state(self) -> dict[str, Any]:
        """
        Экспортировать полное текущее состояние всех регистров всех процессов.

        Возвращает словарь:
            {process_name: {register_name: {field: value, ...}}}

        Используется для глобального snapshot / сохранения.
        """
        return {proc_name: entry.container.to_dict() for proc_name, entry in self._processes.items()}

    def to_json(self, indent: int = 2) -> str:
        """Полное состояние реестра в JSON (только данные, без метаданных)."""
        return json.dumps(
            self.export_state(),
            indent=indent,
            ensure_ascii=False,
            default=str,
        )

    def __repr__(self) -> str:
        procs = list(self._processes.keys())
        return f"ProcessRegistersRegistry(processes={procs})"

    def __len__(self) -> int:
        """Количество зарегистрированных процессов."""
        return len(self._processes)

    def __contains__(self, process_name: str) -> bool:
        return process_name in self._processes
