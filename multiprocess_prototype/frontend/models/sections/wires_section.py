"""WiresSectionView -- управление секцией wires (межпроцессные связи).

CRUD для wire-соединений между портами плагинов разных процессов.
Каждый wire описывает маршрут данных: source port -> target port
через RouterManager + SharedMemory.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List

from multiprocess_prototype.registers.system_topology.schemas import SECTION_WIRES

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import (
        SystemTopologyEditor,
    )

logger = logging.getLogger(__name__)


class WiresSectionView:
    """Section View для межпроцессных wire-связей."""

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor

    @property
    def wires(self) -> Dict[str, dict]:
        """Текущие wire-связи."""
        return self._editor._data.get("wires", {})

    @property
    def dirty(self) -> bool:
        return self._editor.is_dirty(SECTION_WIRES)

    def add_wire(
        self,
        source: str,
        target: str,
        description: str = "",
        transport: str = "router",
        shm_config: dict[str, Any] | None = None,
    ) -> str:
        """Доба��ить wire-связь.

        Args:
            source: Адрес выходного порта "process.plugin.port".
            target: Адрес входног�� порта "process.plugin.port".
            description: Описание связи.
            transport: Тип транспорта ("router" | "direct").
            shm_config: Конфигурация SHM-канала (dict из ShmWireConfig).

        Returns:
            Ключ (UUID) созданного wire.
        """
        wire_key = f"wire_{uuid.uuid4().hex[:8]}"

        wire_data: dict[str, Any] = {
            "source": source,
            "target": target,
            "description": description,
            "transport": transport,
            "shm_config": shm_config or {},
        }

        self._editor.update_item("wires", wire_key, wire_data)

        logger.info(
            "WiresSectionView: добавлен wire '%s': %s -> %s",
            wire_key,
            source,
            target,
        )
        return wire_key

    def remove_wire(self, wire_key: str) -> None:
        """Удалить wire-связь.

        Args:
            wire_key: Ключ wire.
        """
        if wire_key not in self.wires:
            raise KeyError(f"Wire '{wire_key}' не найден")
        self._editor.remove_item("wires", wire_key)
        logger.info("WiresSectionView: удалён wire '%s'", wire_key)

    def modify_wire(self, wire_key: str, fields: dict) -> None:
        """Обновить поля wire.

        Args:
            wire_key: ��люч wire.
            fields: Dict с обновляемыми полями.
        """
        if wire_key not in self.wires:
            raise KeyError(f"Wire '{wire_key}' не найден")
        self.wires[wire_key].update(fields)
        self._editor._notify_section(SECTION_WIRES)

    def wires_for_process(self, proc_key: str) -> Dict[str, dict]:
        """Все wires, связанные с процессом (как source или target).

        Args:
            proc_key: Ключ процесса.

        Returns:
            Подмножество wires, где proc_key фигурирует в source или target.
        """
        result: dict[str, dict] = {}
        for wk, wire in self.wires.items():
            src_proc = wire.get("source", "").split(".")[0]
            tgt_proc = wire.get("target", "").split(".")[0]
            if proc_key in (src_proc, tgt_proc):
                result[wk] = wire
        return result

    def wires_from_port(self, address: str) -> Dict[str, dict]:
        """Все wires, исходящие из указанного адреса (source = address)."""
        return {
            wk: w for wk, w in self.wires.items() if w.get("source") == address
        }

    def wires_to_port(self, address: str) -> Dict[str, dict]:
        """Все wires, входящие в указанный адрес (target = address)."""
        return {
            wk: w for wk, w in self.wires.items() if w.get("target") == address
        }

    def full_snapshot(self) -> dict:
        """Снимок секции для undo/redo."""
        return deepcopy(self.wires)

    def load_from_snapshot(self, data: dict) -> None:
        """Загрузить из snapshot."""
        self._editor._data["wires"] = deepcopy(data)
        self._editor._notify_section(SECTION_WIRES)

    def validate(self) -> List[str]:
        """Валидация FK-ссылок в wires."""
        return self._editor.validate(SECTION_WIRES)


__all__ = ["WiresSectionView"]
