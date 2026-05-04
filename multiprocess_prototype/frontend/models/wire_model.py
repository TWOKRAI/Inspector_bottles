"""WireEditorModel -- бизнес-логика wire-редактора.

Тонкий слой поверх WiresSectionView: добавляет port resolution
через PluginRegistry и валидацию совместимости портов.
Без Qt-зависимостей.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.sections.wires_section import (
        WiresSectionView,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortAddress:
    """Адрес порта плагина: process.plugin.port."""

    process: str
    plugin: str
    port: str
    direction: str  # "input" | "output"

    @property
    def address(self) -> str:
        return f"{self.process}.{self.plugin}.{self.port}"

    @staticmethod
    def parse(addr: str, direction: str = "") -> PortAddress | None:
        """Разобрать строку 'process.plugin.port' в PortAddress."""
        parts = addr.split(".")
        if len(parts) != 3:
            return None
        return PortAddress(
            process=parts[0], plugin=parts[1], port=parts[2], direction=direction
        )


def _get_registry():
    """Lazy-импорт PluginRegistry с graceful degradation."""
    try:
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )

        return PluginRegistry
    except ImportError:
        return None


def _get_port_compat():
    """Lazy-импорт are_ports_compatible."""
    try:
        from multiprocess_framework.modules.process_module.plugins.port import (
            are_ports_compatible,
        )

        return are_ports_compatible
    except ImportError:
        return None


class WireEditorModel:
    """Бизнес-логика wire-редактора.

    Делегирует CRUD в WiresSectionView, добавляет:
    - Port resolution (какие порты доступны у процесса)
    - Валидация совместимости портов при создании wire
    - Query: wires по процессу, по порту
    """

    def __init__(self, wires_section: WiresSectionView) -> None:
        self._section = wires_section

    # ------------------------------------------------------------------
    # CRUD (делегация в section view)
    # ------------------------------------------------------------------

    def add_wire(
        self,
        source: str,
        target: str,
        description: str = "",
        transport: str = "router",
        shm_config: dict[str, Any] | None = None,
    ) -> str:
        """Добавить wire с валидацией совместимости портов.

        Returns:
            wire_key или пустая строка при ошибке валидации.
        """
        errors = self.validate_wire(source, target)
        if errors:
            logger.warning("Wire %s -> %s отклонён: %s", source, target, errors)
            return ""

        return self._section.add_wire(
            source=source,
            target=target,
            description=description,
            transport=transport,
            shm_config=shm_config,
        )

    def remove_wire(self, wire_key: str) -> None:
        self._section.remove_wire(wire_key)

    def modify_wire(self, wire_key: str, fields: dict) -> None:
        self._section.modify_wire(wire_key, fields)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def wires(self) -> dict[str, dict]:
        return self._section.wires

    def wires_for_process(self, proc_key: str) -> dict[str, dict]:
        return self._section.wires_for_process(proc_key)

    # ------------------------------------------------------------------
    # Port Resolution
    # ------------------------------------------------------------------

    def available_ports(self, proc_key: str) -> list[PortAddress]:
        """Все порты (input + output) плагинов процесса.

        Использует PluginRegistry для получения портов.
        Graceful degradation: пустой список если registry недоступен.
        """
        registry = _get_registry()
        if registry is None:
            return []

        processes = self._section._editor._data.get("processes", {})
        proc_data = processes.get(proc_key)
        if proc_data is None:
            return []

        ports: list[PortAddress] = []
        for plugin_dict in proc_data.get("plugins", []):
            plugin_name = plugin_dict.get("plugin_name", "")
            entry = registry.get(plugin_name)
            if entry is None:
                continue

            for p in entry.inputs:
                ports.append(
                    PortAddress(proc_key, plugin_name, p.name, "input")
                )
            for p in entry.outputs:
                ports.append(
                    PortAddress(proc_key, plugin_name, p.name, "output")
                )

        return ports

    def available_outputs(self, proc_key: str) -> list[PortAddress]:
        """Выходные порты процесса."""
        return [p for p in self.available_ports(proc_key) if p.direction == "output"]

    def available_inputs(self, proc_key: str) -> list[PortAddress]:
        """Входные порты процесса."""
        return [p for p in self.available_ports(proc_key) if p.direction == "input"]

    def compatible_targets(self, source_addr: str) -> list[PortAddress]:
        """Все входные порты, совместимые с указанным выходом.

        Полезно для UI: подсветить допустимые target'ы при drag wire.
        """
        compat_fn = _get_port_compat()
        registry = _get_registry()
        if compat_fn is None or registry is None:
            return []

        src = PortAddress.parse(source_addr, "output")
        if src is None:
            return []

        # Найти Port-объект источника
        src_entry = registry.get(src.plugin)
        if src_entry is None:
            return []
        src_port = next((p for p in src_entry.outputs if p.name == src.port), None)
        if src_port is None:
            return []

        # Перебрать все процессы, найти совместимые входы
        result: list[PortAddress] = []
        processes = self._section._editor._data.get("processes", {})
        for pk, proc in processes.items():
            if pk == src.process:
                continue  # Не ссылаемся на свой же процесс
            for plugin_dict in proc.get("plugins", []):
                pname = plugin_dict.get("plugin_name", "")
                entry = registry.get(pname)
                if entry is None:
                    continue
                for inp in entry.inputs:
                    if compat_fn(src_port, inp):
                        result.append(PortAddress(pk, pname, inp.name, "input"))

        return result

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate_wire(self, source: str, target: str) -> list[str]:
        """Валидация одного wire: формат адресов + совместимость портов.

        Returns:
            Список ошибок (пустой = валиден).
        """
        errors: list[str] = []

        src = PortAddress.parse(source, "output")
        tgt = PortAddress.parse(target, "input")

        if src is None:
            errors.append(f"Некорректный формат source: '{source}'")
        if tgt is None:
            errors.append(f"Некорректный формат target: '{target}'")
        if errors:
            return errors

        # Проверка что source и target в разных процессах
        if src.process == tgt.process:
            errors.append("Wire внутри одного процесса не нужен (auto-wired chain)")

        # Проверка совместимости портов через PluginRegistry (graceful)
        registry = _get_registry()
        compat_fn = _get_port_compat()
        if registry is not None and compat_fn is not None:
            src_entry = registry.get(src.plugin)
            tgt_entry = registry.get(tgt.plugin)

            if src_entry is not None and tgt_entry is not None:
                src_port = next(
                    (p for p in src_entry.outputs if p.name == src.port), None
                )
                tgt_port = next(
                    (p for p in tgt_entry.inputs if p.name == tgt.port), None
                )

                if src_port is None:
                    errors.append(
                        f"Порт '{src.port}' не найден в выходах плагина '{src.plugin}'"
                    )
                elif tgt_port is None:
                    errors.append(
                        f"Порт '{tgt.port}' не найден во входах плагина '{tgt.plugin}'"
                    )
                elif not compat_fn(src_port, tgt_port):
                    errors.append(
                        f"Порты несовместимы: {src_port.dtype} -> {tgt_port.dtype}"
                    )

        return errors

    def validate_all(self) -> list[str]:
        """Валидация всех wires."""
        errors: list[str] = []
        for wk, wire in self.wires.items():
            wire_errors = self.validate_wire(
                wire.get("source", ""), wire.get("target", "")
            )
            for err in wire_errors:
                errors.append(f"Wire '{wk}': {err}")
        return errors


__all__ = ["WireEditorModel", "PortAddress"]
