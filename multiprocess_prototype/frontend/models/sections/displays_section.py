"""DisplaysSectionView — управление секцией displays.

CRUD для display-окон. Поддержка пресетов (SINGLE/DUAL/QUAD).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, TYPE_CHECKING

from multiprocess_prototype.registers.system_topology.schemas import SECTION_DISPLAYS

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)


class DisplaysSectionView:
    """Section View для display-окон."""

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor

    @property
    def displays(self) -> Dict[str, dict]:
        """Текущие display-окна."""
        return self._editor._data.get("displays", {})

    @property
    def dirty(self) -> bool:
        return self._editor.is_dirty(SECTION_DISPLAYS)

    def add_display(
        self,
        name: str,
        source_ref: str,
        fps_limit: int = 30,
    ) -> str:
        """Добавить display-окно.

        Args:
            name: Отображаемое имя.
            source_ref: Ссылка на источник (camera_0, processor_0...).
            fps_limit: Лимит FPS.

        Returns:
            Ключ созданного display.
        """
        idx = len(self.displays)
        display_key = f"win_{idx}"

        self._editor.update_item("displays", display_key, {
            "name": name,
            "source_ref": source_ref,
            "fps_limit": fps_limit,
        })

        logger.info("DisplaysSectionView: добавлен display '%s' → '%s'", display_key, source_ref)
        return display_key

    def remove_display(self, display_key: str) -> None:
        """Удалить display-окно.

        Args:
            display_key: Ключ дисплея.
        """
        if display_key not in self.displays:
            raise KeyError(f"Display '{display_key}' не найден")
        self._editor.remove_item("displays", display_key)

    def modify_display(self, display_key: str, fields: dict) -> None:
        """Обновить поля display.

        Args:
            display_key: Ключ дисплея.
            fields: Dict с обновляемыми полями.
        """
        if display_key not in self.displays:
            raise KeyError(f"Display '{display_key}' не найден")
        self.displays[display_key].update(fields)
        self._editor._notify_section(SECTION_DISPLAYS)

    def apply_preset(self, preset_name: str, camera_keys: List[str]) -> List[str]:
        """Применить layout-пресет: заменить все displays на пресетные.

        Args:
            preset_name: Имя пресета (single/dual/quad).
            camera_keys: Список ключей камер.

        Returns:
            Список созданных display ключей.
        """
        # Очистить текущие displays
        self._editor._data["displays"] = {}

        created: list[str] = []
        if preset_name == "single" and camera_keys:
            cam = camera_keys[0]
            cam_data = self._editor._data.get("cameras", {}).get(cam, {})
            cam_id = cam_data.get("camera_id", 0)
            key = "win_0"
            self._editor._data["displays"][key] = {
                "name": f"Display {cam_id}",
                "source_ref": f"camera_{cam_id}",
                "fps_limit": 30,
            }
            created.append(key)

        elif preset_name == "dual":
            for i, cam in enumerate(camera_keys[:2]):
                cam_data = self._editor._data.get("cameras", {}).get(cam, {})
                cam_id = cam_data.get("camera_id", 0)
                key = f"win_{i}"
                self._editor._data["displays"][key] = {
                    "name": f"Display {cam_id}",
                    "source_ref": f"camera_{cam_id}",
                    "fps_limit": 30,
                }
                created.append(key)

        elif preset_name == "quad":
            for i, cam in enumerate(camera_keys[:4]):
                cam_data = self._editor._data.get("cameras", {}).get(cam, {})
                cam_id = cam_data.get("camera_id", 0)
                key = f"win_{i}"
                self._editor._data["displays"][key] = {
                    "name": f"Display {cam_id}",
                    "source_ref": f"camera_{cam_id}",
                    "fps_limit": 30,
                }
                created.append(key)

        self._editor._notify_section(SECTION_DISPLAYS)
        logger.info(
            "DisplaysSectionView: пресет '%s' → %d displays",
            preset_name, len(created),
        )
        return created

    def full_snapshot(self) -> dict:
        """Снимок секции для undo/redo."""
        return deepcopy(self.displays)

    def load_from_snapshot(self, data: dict) -> None:
        """Загрузить из snapshot."""
        self._editor._data["displays"] = deepcopy(data)
        self._editor._notify_section(SECTION_DISPLAYS)

    def validate(self) -> List[str]:
        return self._editor.validate(SECTION_DISPLAYS)


__all__ = ["DisplaysSectionView"]
