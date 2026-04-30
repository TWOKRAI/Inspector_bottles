"""SourcesSectionView — управление секцией cameras/regions.

API совместим с TopologyEditorModel для минимальных изменений в UI.
Бизнес-логика: auto-main-region, camera_id auto-increment, cascade delete.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from multiprocess_prototype.registers.system_topology.schemas import SECTION_SOURCES

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)


class SourcesSectionView:
    """Section View для камер и регионов.

    Делегирует хранение в SystemTopologyEditor._data["cameras"] и ["regions"].
    Каждая мутация уведомляет подписчиков секции SECTION_SOURCES.
    """

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor

    # ------------------------------------------------------------------
    # Properties (read)
    # ------------------------------------------------------------------

    @property
    def cameras(self) -> Dict[str, dict]:
        """Текущие камеры."""
        return self._editor._data.get("cameras", {})

    @property
    def regions(self) -> Dict[str, dict]:
        """Текущие регионы."""
        return self._editor._data.get("regions", {})

    @property
    def dirty(self) -> bool:
        """Есть ли несохранённые изменения."""
        return self._editor.is_dirty(SECTION_SOURCES)

    # ------------------------------------------------------------------
    # Camera CRUD
    # ------------------------------------------------------------------

    def add_camera(
        self,
        camera_type: str = "simulator",
        camera_id: Optional[int] = None,
    ) -> tuple[str, str]:
        """Добавить камеру + автоматически создать main-регион.

        Args:
            camera_type: Тип камеры (simulator/webcam/hikvision).
            camera_id: ID камеры (auto-increment если None).

        Returns:
            Tuple (camera_key, region_key).
        """
        if camera_id is None:
            camera_id = self._next_camera_id()

        cam_key = f"camera_{camera_id}"

        self._editor.update_item("cameras", cam_key, {
            "camera_id": camera_id,
            "camera_type": camera_type,
            "process_name": f"camera_{camera_id}",
            "execution_mode": "process",
            "region_processing": "dedicated_processor",
            "region_processor_name": f"processor_{camera_id}",
        })

        # Автоматически создаём main-регион
        reg_key = f"{cam_key}_main"
        self._editor._data.setdefault("regions", {})[reg_key] = {
            "camera_ref": cam_key,
            "enabled": True,
            "is_main": True,
            "processing_enabled": True,
            "sort_order": 0,
        }
        # Notification уже отправлен из update_item

        logger.info(
            "SourcesSectionView: добавлена камера '%s' (type=%s) + main region",
            cam_key, camera_type,
        )
        return cam_key, reg_key

    def remove_camera(self, cam_key: str) -> None:
        """Удалить камеру и все её регионы (cascade delete).

        Args:
            cam_key: Ключ камеры.

        Raises:
            KeyError: Если камера не найдена.
        """
        if cam_key not in self.cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")

        # Cascade: удалить все регионы камеры
        region_keys = [
            rk for rk, r in self.regions.items()
            if r.get("camera_ref") == cam_key
        ]
        for rk in region_keys:
            self._editor._data["regions"].pop(rk, None)

        self._editor.remove_item("cameras", cam_key)
        logger.info(
            "SourcesSectionView: удалена камера '%s' + %d регионов",
            cam_key, len(region_keys),
        )

    def modify_camera(self, cam_key: str, fields: dict) -> None:
        """Обновить поля камеры.

        Args:
            cam_key: Ключ камеры.
            fields: Dict с обновляемыми полями.
        """
        if cam_key not in self.cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")
        self.cameras[cam_key].update(fields)
        self._editor._notify_section(SECTION_SOURCES)

    # ------------------------------------------------------------------
    # Region CRUD
    # ------------------------------------------------------------------

    def add_region(self, cam_key: str) -> str:
        """Добавить регион к камере.

        Args:
            cam_key: Ключ камеры-владельца.

        Returns:
            Ключ созданного региона.

        Raises:
            KeyError: Если камера не найдена.
        """
        if cam_key not in self.cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")

        idx = len(self.regions_for_camera(cam_key))
        reg_key = f"{cam_key}_region_{idx}"

        self._editor.update_item("regions", reg_key, {
            "camera_ref": cam_key,
            "enabled": True,
            "is_main": False,
            "processing_enabled": True,
            "sort_order": idx,
        })

        logger.info("SourcesSectionView: добавлен регион '%s' → '%s'", reg_key, cam_key)
        return reg_key

    def remove_region(self, reg_key: str) -> None:
        """Удалить регион.

        Args:
            reg_key: Ключ региона.

        Raises:
            KeyError: Если регион не найден.
        """
        if reg_key not in self.regions:
            raise KeyError(f"Регион '{reg_key}' не найден")
        self._editor.remove_item("regions", reg_key)
        logger.info("SourcesSectionView: удалён регион '%s'", reg_key)

    def modify_region(self, reg_key: str, fields: dict) -> None:
        """Обновить поля региона.

        Args:
            reg_key: Ключ региона.
            fields: Dict с обновляемыми полями.
        """
        if reg_key not in self.regions:
            raise KeyError(f"Регион '{reg_key}' не найден")
        self.regions[reg_key].update(fields)
        self._editor._notify_section(SECTION_SOURCES)

    def regions_for_camera(self, cam_key: str) -> Dict[str, dict]:
        """Все регионы камеры.

        Args:
            cam_key: Ключ камеры.

        Returns:
            Dict[region_key, region_dict].
        """
        return {
            k: v for k, v in self.regions.items()
            if v.get("camera_ref") == cam_key
        }

    # ------------------------------------------------------------------
    # Snapshot для ActionBus undo/redo
    # ------------------------------------------------------------------

    def full_snapshot(self) -> dict:
        """Полный снимок секции (для undo/redo).

        Returns:
            {"cameras": {...}, "regions": {...}} — deepcopy.
        """
        return {
            "cameras": deepcopy(self.cameras),
            "regions": deepcopy(self.regions),
        }

    def load_from_snapshot(self, data: dict) -> None:
        """Загрузить состояние из snapshot (для undo/redo).

        Args:
            data: {"cameras": {...}, "regions": {...}}.
        """
        self._editor.set_section_data(SECTION_SOURCES, data)

    # ------------------------------------------------------------------
    # Переупорядочивание
    # ------------------------------------------------------------------

    def reorder_cameras(self, cam_key: str, direction: int) -> None:
        """Переместить камеру вверх (direction=-1) или вниз (direction=+1).

        Пересчитывает sort_order у всех камер.

        Args:
            cam_key: Ключ перемещаемой камеры.
            direction: -1 (вверх) или +1 (вниз).
        """
        cameras = self._editor._data.get("cameras", {})
        keys = sorted(cameras.keys(), key=lambda k: cameras[k].get("sort_order", 0))
        idx = keys.index(cam_key) if cam_key in keys else -1
        if idx < 0:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(keys):
            return
        # Поменять sort_order местами
        keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
        for order, key in enumerate(keys):
            cameras[key]["sort_order"] = order
        self._editor._notify_section(SECTION_SOURCES)
        logger.debug("SourcesSectionView: камера '%s' перемещена (direction=%d)", cam_key, direction)

    def reorder_regions(self, reg_key: str, direction: int) -> None:
        """Переместить регион вверх (direction=-1) или вниз (direction=+1).

        Args:
            reg_key: Ключ перемещаемого региона.
            direction: -1 (вверх) или +1 (вниз).
        """
        regions = self._editor._data.get("regions", {})
        # Найти камеру-владельца региона
        cam_key = regions[reg_key].get("camera_ref", "") if reg_key in regions else ""
        # Отфильтровать регионы той же камеры
        cam_regions = {k: v for k, v in regions.items() if v.get("camera_ref") == cam_key}
        keys = sorted(cam_regions.keys(), key=lambda k: cam_regions[k].get("sort_order", 0))
        idx = keys.index(reg_key) if reg_key in keys else -1
        if idx < 0:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(keys):
            return
        keys[idx], keys[new_idx] = keys[new_idx], keys[idx]
        for order, key in enumerate(keys):
            regions[key]["sort_order"] = order
        self._editor._notify_section(SECTION_SOURCES)
        logger.debug("SourcesSectionView: регион '%s' перемещён (direction=%d)", reg_key, direction)

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Валидация секции источников."""
        return self._editor.validate(SECTION_SOURCES)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_camera_id(self) -> int:
        """Следующий свободный camera_id."""
        existing_ids = {
            c.get("camera_id", 0)
            for c in self.cameras.values()
        }
        cid = 0
        while cid in existing_ids:
            cid += 1
        return cid


__all__ = ["SourcesSectionView"]
