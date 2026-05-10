"""DisplaysPresenter — бизнес-логика таба дисплеев."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


# Пресеты раскладок дисплеев
DISPLAY_PRESETS: dict[str, list[str]] = {
    "none": [],
    "1×1": ["main"],
    "1+1": ["left", "right"],
    "2×2": ["top_left", "top_right", "bottom_left", "bottom_right"],
}


class DisplaysPresenter:
    """Presenter для DisplaysTab.

    Управляет пресетами, CRUD слотов, привязкой к source процессам.
    """

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx
        self._slots: list[dict[str, str]] = []  # {slot_id, source, label}

    @property
    def slots(self) -> list[dict[str, str]]:
        return list(self._slots)

    def get_available_sources(self) -> list[str]:
        """Список процессов-источников из topology."""
        topology = self._ctx.config.get("topology", {})
        processes = topology.get("processes", [])

        if not processes:
            topo = self._ctx.extras.get("topology", {})
            processes = topo.get("processes", []) if isinstance(topo, dict) else []

        names = []
        for p in processes:
            if isinstance(p, dict):
                name = p.get("process_name", "")
            else:
                name = getattr(p, "process_name", "")
            if name:
                names.append(name)
        return names

    def apply_preset(self, preset_name: str) -> list[dict[str, str]]:
        """Применить пресет — заменить все слоты."""
        slot_ids = DISPLAY_PRESETS.get(preset_name, [])
        self._slots = [
            {"slot_id": sid, "source": "", "label": sid}
            for sid in slot_ids
        ]
        return list(self._slots)

    def add_slot(self, slot_id: str = "") -> dict[str, str]:
        """Добавить новый слот."""
        if not slot_id:
            slot_id = f"display_{len(self._slots)}"
        slot = {"slot_id": slot_id, "source": "", "label": slot_id}
        self._slots.append(slot)
        return slot

    def remove_slot(self, index: int) -> None:
        """Удалить слот по индексу."""
        if 0 <= index < len(self._slots):
            self._slots.pop(index)

    def set_slot_source(self, index: int, source: str) -> None:
        """Привязать слот к source процессу."""
        if 0 <= index < len(self._slots):
            self._slots[index]["source"] = source
