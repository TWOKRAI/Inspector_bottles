"""TopologyEditorModel — модель топологии камер и регионов.

Специализация BaseEditorModel для двухслойной модели:
Layer 1 — cameras (CameraSourceConfig), Layer 2 — regions (RegionSourceConfig).
Foreign-key camera_ref связывает регионы с камерами.
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from .base_editor_model import BaseEditorModel

logger = logging.getLogger(__name__)


class TopologyEditorModel(BaseEditorModel):
    """Модель редактора топологии: камеры + регионы.

    Вместо единого _items использует два отдельных словаря:
    - _cameras: dict-представления CameraSourceConfig
    - _regions: dict-представления RegionSourceConfig

    Каждая мутация возвращает (old, new) для поддержки undo.
    Нет зависимостей от Qt — чистая бизнес-логика.
    """

    def __init__(self) -> None:
        super().__init__()
        # Layer 1 — источники (камеры)
        self._cameras: dict[str, dict] = {}
        # Layer 2 — регионы, привязанные к камерам по camera_ref
        self._regions: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Переопределение items (отдаём обе коллекции)
    # ------------------------------------------------------------------

    @property
    def items(self) -> dict[str, Any]:
        """Возвращает топологию как единый dict {"cameras": ..., "regions": ...}."""
        return self.full_snapshot()

    # ------------------------------------------------------------------
    # Загрузка
    # ------------------------------------------------------------------

    def load_from_topology(self, data: dict) -> None:
        """Загрузить топологию из dict {"cameras": {...}, "regions": {...}}.

        Args:
            data: словарь с ключами "cameras" и "regions".
        """
        self._cameras = deepcopy(data.get("cameras", {}))
        self._regions = deepcopy(data.get("regions", {}))
        self._notify()

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    @property
    def cameras(self) -> dict[str, dict]:
        """Копия словаря камер."""
        return dict(self._cameras)

    @property
    def regions(self) -> dict[str, dict]:
        """Копия словаря регионов."""
        return dict(self._regions)

    def regions_for_camera(self, cam_key: str) -> dict[str, dict]:
        """Вернуть все регионы, привязанные к указанной камере.

        Args:
            cam_key: ключ камеры (например, "camera_0").

        Returns:
            Словарь {reg_key: reg_dict} для данной камеры.
        """
        return {
            k: deepcopy(v)
            for k, v in self._regions.items()
            if v.get("camera_ref") == cam_key
        }

    def full_snapshot(self) -> dict:
        """Deepcopy полного состояния модели.

        Returns:
            {"cameras": {...}, "regions": {...}}
        """
        return {
            "cameras": deepcopy(self._cameras),
            "regions": deepcopy(self._regions),
        }

    # ------------------------------------------------------------------
    # Dirty tracking (переопределяем для двухслойной структуры)
    # ------------------------------------------------------------------

    @property
    def dirty(self) -> bool:
        """True если состояние отличается от последнего snapshot."""
        if self._snapshot is None:
            return True
        return self.full_snapshot() != self._snapshot

    def snapshot(self) -> None:
        """Сохранить deepcopy текущего состояния в _snapshot."""
        self._snapshot = self.full_snapshot()

    def mark_clean(self) -> None:
        """Сделать текущее состояние «чистым»."""
        self.snapshot()

    # ------------------------------------------------------------------
    # Мутации камер
    # ------------------------------------------------------------------

    def add_camera(
        self,
        camera_type: str = "simulator",
        camera_id: int | None = None,
    ) -> tuple[None, tuple[str, str]]:
        """Добавить новую камеру с main-регионом.

        Args:
            camera_type: тип камеры (simulator / webcam / hikvision).
            camera_id: явный числовой ID; если None — подбирается автоматически.

        Returns:
            (None, (cam_key, reg_key)) — ключи созданной камеры и main-региона.
        """
        # Подобрать свободный ключ и индекс
        idx = len(self._cameras)
        cam_key = f"camera_{idx}"
        while cam_key in self._cameras:
            idx += 1
            cam_key = f"camera_{idx}"

        # camera_id по умолчанию совпадает с индексом
        if camera_id is None:
            camera_id = idx

        # Defaults для новой камеры
        cam_dict: dict[str, Any] = {
            "camera_id": camera_id,
            "camera_type": camera_type,
            "process_name": f"camera_{idx}",
            "execution_mode": "process",
            "registers": {
                "camera_type": camera_type,
                "fps": 25,
                "resolution_width": 640,
                "resolution_height": 480,
            },
            "shm_config": {
                "name": f"camera_{idx}_frame",
                "width": 640,
                "height": 480,
                "channels": 3,
                "ring_slots": 3,
                "dtype": "uint8",
            },
            "region_processing": "dedicated_processor",
            "region_processor_name": f"processor_{idx}",
        }
        self._cameras[cam_key] = cam_dict

        # Создать main-регион для новой камеры
        reg_key = f"{cam_key}_main"
        self._regions[reg_key] = {
            "camera_ref": cam_key,
            "rect": {"x": 0, "y": 0, "width": 640, "height": 480},
            "enabled": True,
            "is_main": True,
            "processing_enabled": True,
            "sort_order": 0,
            "shm_enabled": False,
            "shm_config": None,
        }

        logger.debug("Добавлена камера '%s' с main-регионом '%s'", cam_key, reg_key)
        self._notify()
        return (None, (cam_key, reg_key))

    def remove_camera(self, cam_key: str) -> tuple[dict, None]:
        """Удалить камеру и все её регионы (каскадное удаление).

        Args:
            cam_key: ключ камеры.

        Returns:
            ({"camera": cam_dict, "regions": {reg_key: reg_dict}}, None)

        Raises:
            KeyError: если камера не найдена.
        """
        if cam_key not in self._cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")

        removed_cam = self._cameras.pop(cam_key)

        # Каскадное удаление всех регионов, привязанных к данной камере
        removed_regs: dict[str, dict] = {}
        for reg_key in list(self._regions.keys()):
            if self._regions[reg_key].get("camera_ref") == cam_key:
                removed_regs[reg_key] = self._regions.pop(reg_key)

        logger.debug(
            "Удалена камера '%s' и %d регионов", cam_key, len(removed_regs)
        )
        self._notify()
        return ({"camera": removed_cam, "regions": removed_regs}, None)

    def modify_camera(
        self, cam_key: str, fields: dict[str, Any]
    ) -> tuple[dict, dict]:
        """Обновить поля камеры.

        Если обновляются registers.resolution_width/height —
        автоматически синхронизирует shm_config.width/height.

        Args:
            cam_key: ключ камеры.
            fields: словарь изменяемых полей верхнего уровня.

        Returns:
            (old_fields, new_fields) — только переданные ключи.

        Raises:
            KeyError: если камера не найдена.
        """
        if cam_key not in self._cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")

        cam = self._cameras[cam_key]
        old_fields = {k: deepcopy(cam.get(k)) for k in fields}

        cam.update(fields)

        # Авто-синхронизация разрешения: registers → shm_config
        if "registers" in fields:
            regs = cam.get("registers", {})
            shm = cam.get("shm_config", {})
            if isinstance(regs, dict) and isinstance(shm, dict):
                if "resolution_width" in regs:
                    shm["width"] = regs["resolution_width"]
                if "resolution_height" in regs:
                    shm["height"] = regs["resolution_height"]

        new_fields = {k: deepcopy(cam[k]) for k in fields}

        logger.debug("Изменена камера '%s': %s", cam_key, list(fields.keys()))
        self._notify()
        return (old_fields, new_fields)

    # ------------------------------------------------------------------
    # Мутации регионов
    # ------------------------------------------------------------------

    def add_region(self, camera_ref: str) -> tuple[None, str]:
        """Добавить новый (не main) регион к камере.

        Args:
            camera_ref: ключ камеры-источника.

        Returns:
            (None, reg_key) — ключ созданного региона.
        """
        # Подобрать свободный ключ для региона
        existing = self.regions_for_camera(camera_ref)
        sort_order = len(existing)

        idx = 0
        reg_key = f"{camera_ref}_region_{idx}"
        while reg_key in self._regions:
            idx += 1
            reg_key = f"{camera_ref}_region_{idx}"

        self._regions[reg_key] = {
            "camera_ref": camera_ref,
            "rect": {"x": 0, "y": 0, "width": 100, "height": 100},
            "enabled": True,
            "is_main": False,
            "processing_enabled": True,
            "sort_order": sort_order,
            "shm_enabled": False,
            "shm_config": None,
        }

        logger.debug("Добавлен регион '%s' для камеры '%s'", reg_key, camera_ref)
        self._notify()
        return (None, reg_key)

    def remove_region(self, reg_key: str) -> tuple[dict, None]:
        """Удалить регион (нельзя удалить main-регион).

        Args:
            reg_key: ключ региона.

        Returns:
            (removed_dict, None)

        Raises:
            KeyError: если регион не найден.
            ValueError: если регион является main (is_main=True).
        """
        if reg_key not in self._regions:
            raise KeyError(f"Регион '{reg_key}' не найден")

        reg = self._regions[reg_key]
        if reg.get("is_main"):
            raise ValueError(
                f"Нельзя удалить основной (main) регион '{reg_key}'"
            )

        removed = self._regions.pop(reg_key)
        logger.debug("Удалён регион '%s'", reg_key)
        self._notify()
        return (removed, None)

    def modify_region(
        self, reg_key: str, fields: dict[str, Any]
    ) -> tuple[dict, dict]:
        """Обновить поля региона.

        Args:
            reg_key: ключ региона.
            fields: словарь изменяемых полей верхнего уровня.

        Returns:
            (old_fields, new_fields) — только переданные ключи.

        Raises:
            KeyError: если регион не найден.
        """
        if reg_key not in self._regions:
            raise KeyError(f"Регион '{reg_key}' не найден")

        reg = self._regions[reg_key]
        old_fields = {k: deepcopy(reg.get(k)) for k in fields}
        reg.update(fields)
        new_fields = {k: deepcopy(reg[k]) for k in fields}

        logger.debug("Изменён регион '%s': %s", reg_key, list(fields.keys()))
        self._notify()
        return (old_fields, new_fields)

    # ------------------------------------------------------------------
    # Переупорядочивание
    # ------------------------------------------------------------------

    def reorder_cameras(
        self, cam_key: str, direction: int
    ) -> tuple[list[str], list[str]]:
        """Переместить камеру на одну позицию вверх (-1) или вниз (+1).

        Args:
            cam_key: ключ перемещаемой камеры.
            direction: -1 (вверх) или +1 (вниз).

        Returns:
            (old_order, new_order) — списки ключей до и после.

        Raises:
            KeyError: если камера не найдена.
        """
        if cam_key not in self._cameras:
            raise KeyError(f"Камера '{cam_key}' не найдена")

        keys = list(self._cameras.keys())
        old_order = list(keys)
        idx = keys.index(cam_key)
        target = idx + direction

        # Выход за границы — ничего не меняем
        if target < 0 or target >= len(keys):
            return (old_order, list(old_order))

        # Меняем позиции (Python 3.7+ dict сохраняет порядок вставки)
        keys[idx], keys[target] = keys[target], keys[idx]
        self._cameras = {k: self._cameras[k] for k in keys}

        new_order = list(keys)
        logger.debug("Камера '%s' перемещена: %s → %s", cam_key, old_order, new_order)
        self._notify()
        return (old_order, new_order)

    def reorder_regions(
        self, reg_key: str, direction: int
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Поменять sort_order региона с соседним регионом той же камеры.

        Args:
            reg_key: ключ перемещаемого региона.
            direction: -1 (вверх) или +1 (вниз).

        Returns:
            (old_orders, new_orders) — dict {reg_key: sort_order} до и после.

        Raises:
            KeyError: если регион не найден.
        """
        if reg_key not in self._regions:
            raise KeyError(f"Регион '{reg_key}' не найден")

        cam_key = self._regions[reg_key].get("camera_ref", "")

        # Регионы той же камеры, отсортированные по sort_order
        cam_regions = {
            k: v
            for k, v in self._regions.items()
            if v.get("camera_ref") == cam_key
        }
        sorted_keys = sorted(cam_regions, key=lambda k: cam_regions[k].get("sort_order", 0))

        old_orders = {k: self._regions[k].get("sort_order", 0) for k in sorted_keys}

        idx = sorted_keys.index(reg_key)
        target = idx + direction

        # Выход за границы — ничего не меняем
        if target < 0 or target >= len(sorted_keys):
            return (dict(old_orders), dict(old_orders))

        # Обменять sort_order между соседями
        neighbor_key = sorted_keys[target]
        self._regions[reg_key]["sort_order"], self._regions[neighbor_key]["sort_order"] = (
            self._regions[neighbor_key]["sort_order"],
            self._regions[reg_key]["sort_order"],
        )

        new_orders = {k: self._regions[k].get("sort_order", 0) for k in sorted_keys}
        logger.debug("Регион '%s' переупорядочен", reg_key)
        self._notify()
        return (old_orders, new_orders)

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Валидировать топологию через SourceTopology.model_validate().

        Returns:
            Список строк с ошибками (пустой список = всё ок).
        """
        # Ленивый импорт — не тянуть схемы на верхний уровень
        from multiprocess_prototype.registers.sources.schemas import SourceTopology  # noqa: PLC0415

        try:
            SourceTopology.model_validate(self.full_snapshot())
            return []
        except Exception as exc:  # noqa: BLE001
            errors = []
            # Pydantic ValidationError содержит список ошибок
            if hasattr(exc, "errors"):
                for err in exc.errors():
                    loc = " → ".join(str(p) for p in err.get("loc", []))
                    msg = err.get("msg", str(err))
                    errors.append(f"{loc}: {msg}" if loc else msg)
            else:
                errors.append(str(exc))
            return errors
