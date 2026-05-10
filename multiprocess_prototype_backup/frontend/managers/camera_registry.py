"""CameraRegistry — frontend-реестр N камер с callback-ами для UI-обновлений (Task 3.9)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema


@register_schema("CameraEntryV3")
class CameraEntry(SchemaBase):
    """Запись о камере в frontend-реестре."""

    camera_id: int = 0
    camera_type: str = "simulator"
    # Статус камеры: stopped | running | error
    status: str = "stopped"
    process_name: str = "camera_0"
    fps: float = 0.0
    last_frame_ts: float = 0.0
    drops_count: int = 0


class CameraRegistry:
    """Frontend-реестр N камер с callback-ами для UI-обновлений.

    Хранит текущее состояние каждой камеры (статус, fps, дропы) и
    уведомляет подписчиков при любом изменении.

    Пример использования::

        registry = CameraRegistry([
            {"camera_id": 0, "camera_type": "webcam"},
            {"camera_id": 1, "camera_type": "hikvision"},
        ])
        registry.add_callback(lambda cid, field, val: print(cid, field, val))
        registry.update_status(0, "running")
    """

    def __init__(self, camera_configs: list | None = None) -> None:
        """Инициализация реестра из списка конфигов камер.

        Args:
            camera_configs: Список dict или объектов с атрибутами
                            camera_id / camera_type / process_name.
                            Если None — реестр создаётся пустым.
        """
        self._entries: dict[int, CameraEntry] = {}
        # Список callback-функций вида (camera_id, field, value)
        self._callbacks: list[Callable[[int, str, Any], None]] = []

        if camera_configs:
            for cfg in camera_configs:
                self._register_from_config(cfg)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _register_from_config(self, cfg: Any) -> None:
        """Добавить запись в реестр из dict или объекта конфига."""
        if isinstance(cfg, dict):
            camera_id = int(cfg.get("camera_id", 0))
            camera_type = str(cfg.get("camera_type", "simulator"))
            process_name = str(cfg.get("process_name", f"camera_{camera_id}"))
        else:
            # Поддержка объектов (CameraConfig и аналогов)
            camera_id = int(getattr(cfg, "camera_id", 0))
            camera_type = str(getattr(cfg, "camera_type", "simulator"))
            process_name = str(getattr(cfg, "process_name", f"camera_{camera_id}"))

        self._entries[camera_id] = CameraEntry(
            camera_id=camera_id,
            camera_type=camera_type,
            process_name=process_name,
        )

    def _notify_callbacks(self, camera_id: int, field: str, value: Any) -> None:
        """Вызвать все зарегистрированные callback-и с изменением поля."""
        for callback in self._callbacks:
            # Ошибка в callback не должна прерывать обновление реестра
            with contextlib.suppress(Exception):
                callback(camera_id, field, value)

    # ------------------------------------------------------------------
    # Публичный API — чтение
    # ------------------------------------------------------------------

    def get_entry(self, camera_id: int) -> CameraEntry | None:
        """Вернуть запись о камере по camera_id или None, если не найдена."""
        return self._entries.get(camera_id)

    def all_entries(self) -> list[CameraEntry]:
        """Вернуть список всех записей, отсортированный по camera_id."""
        return [self._entries[cid] for cid in sorted(self._entries)]

    def camera_count(self) -> int:
        """Количество камер в реестре."""
        return len(self._entries)

    # ------------------------------------------------------------------
    # Публичный API — обновление состояния
    # ------------------------------------------------------------------

    def update_status(self, camera_id: int, status: str) -> None:
        """Обновить статус камеры и уведомить подписчиков.

        Args:
            camera_id: Идентификатор камеры.
            status: Новый статус — "stopped" | "running" | "error".
        """
        entry = self._entries.get(camera_id)
        if entry is None:
            return
        entry.status = status
        self._notify_callbacks(camera_id, "status", status)

    def update_fps(self, camera_id: int, fps: float) -> None:
        """Обновить значение FPS камеры и уведомить подписчиков."""
        entry = self._entries.get(camera_id)
        if entry is None:
            return
        entry.fps = fps
        self._notify_callbacks(camera_id, "fps", fps)

    def update_drops(self, camera_id: int, drops_count: int) -> None:
        """Обновить счётчик дропнутых кадров и уведомить подписчиков."""
        entry = self._entries.get(camera_id)
        if entry is None:
            return
        entry.drops_count = drops_count
        self._notify_callbacks(camera_id, "drops_count", drops_count)

    def update_last_frame_ts(self, camera_id: int, timestamp: float) -> None:
        """Обновить временну́ю метку последнего кадра и уведомить подписчиков."""
        entry = self._entries.get(camera_id)
        if entry is None:
            return
        entry.last_frame_ts = timestamp
        self._notify_callbacks(camera_id, "last_frame_ts", timestamp)

    # ------------------------------------------------------------------
    # Публичный API — управление подписчиками
    # ------------------------------------------------------------------

    def add_callback(self, callback: Callable[[int, str, Any], None]) -> None:
        """Зарегистрировать callback для получения уведомлений об изменениях.

        Args:
            callback: Функция вида ``callback(camera_id: int, field: str, value: Any)``.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[int, str, Any], None]) -> None:
        """Удалить ранее зарегистрированный callback."""
        with contextlib.suppress(ValueError):
            self._callbacks.remove(callback)


__all__ = [
    "CameraEntry",
    "CameraRegistry",
]
