"""camera_state_adapter.py — Адаптер камер через StateProxy.

Подписывается на cameras.*.state.* через GuiStateProxy и предоставляет
callback-API для виджетов (обратная совместимость с CameraRegistry).

Заменяет CameraRegistry — данные берутся из StateStore, а не из IPC напрямую.

Паттерны путей:
    cameras.{id}.state.status       — статус камеры: stopped | running | error
    cameras.{id}.state.actual_fps   — текущий FPS
    cameras.{id}.state.drops_count  — счётчик дропнутых кадров
    cameras.{id}.state.last_frame_seq — порядковый номер последнего кадра
"""
from __future__ import annotations

import contextlib
import logging
import re
from typing import Any, Callable

from multiprocess_framework.modules.state_store_module import Delta

logger = logging.getLogger(__name__)

# Regex для разбора пути cameras.{id}.state.{field}
_CAMERA_STATE_RE = re.compile(r"^cameras\.(\d+)\.state\.(.+)$")

# Поля, которые транслируются в callback (camera_id, field, value)
_TRACKED_FIELDS = frozenset({"status", "actual_fps", "drops_count", "last_frame_seq"})


class CameraStateAdapter:
    """Адаптер камер: читает данные из StateProxy вместо CameraRegistry.

    Подписывается на cameras.*.state.** через StateProxy.
    При получении дельт — нотифицирует зарегистрированные callbacks.

    Обратная совместимость: callback сигнатура (camera_id: int, field: str, value: Any)
    аналогична CameraRegistry.

    Пример использования::

        adapter = CameraStateAdapter(state_proxy, num_cameras=2)
        adapter.connect()
        adapter.add_callback(lambda cid, field, val: print(cid, field, val))

        # Читать состояние камеры
        state = adapter.get_camera_state(0)  # {"status": "running", "actual_fps": 29.5, ...}
    """

    def __init__(self, state_proxy: Any, num_cameras: int) -> None:
        """
        Args:
            state_proxy: GuiStateProxy или StateProxy (duck-typing).
            num_cameras: ожидаемое количество камер (используется для инициализации кэша).
        """
        self._proxy = state_proxy
        self._num_cameras = num_cameras
        # Локальный кэш состояния: camera_id -> {field: value}
        self._camera_states: dict[int, dict[str, Any]] = {}
        # Инициализируем пустые записи для всех камер
        for cid in range(num_cameras):
            self._camera_states[cid] = {
                "status": "stopped",
                "actual_fps": 0.0,
                "drops_count": 0,
                "last_frame_seq": 0,
            }
        # Список callbacks вида (camera_id, field, value)
        self._callbacks: list[Callable[[int, str, Any], None]] = []
        # ID подписки на StateProxy (для disconnect)
        self._sub_id: str | None = None
        # Состояние подключения
        self._connected = False

    # ------------------------------------------------------------------
    # Публичный API — lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Подключить адаптер: подписаться на cameras.*.state.** через StateProxy."""
        if self._connected:
            logger.warning("CameraStateAdapter: уже подключён, connect() игнорируется")
            return

        self._sub_id = self._proxy.subscribe(
            "cameras.*.state.**",
            self._on_state_deltas,
            exclude_self=False,
        )
        self._connected = True
        logger.info(
            "CameraStateAdapter: подключён, num_cameras=%d, sub_id=%s",
            self._num_cameras,
            self._sub_id,
        )

    def disconnect(self) -> None:
        """Отключить адаптер: отписаться от StateProxy."""
        if not self._connected:
            logger.warning("CameraStateAdapter: не подключён, disconnect() игнорируется")
            return

        if self._sub_id is not None:
            self._proxy.unsubscribe(self._sub_id)
            self._sub_id = None

        self._connected = False
        logger.info("CameraStateAdapter: отключён")

    @property
    def is_connected(self) -> bool:
        """True если адаптер подключён."""
        return self._connected

    # ------------------------------------------------------------------
    # Публичный API — чтение
    # ------------------------------------------------------------------

    def get_camera_state(self, camera_id: int) -> dict:
        """Вернуть текущее состояние камеры из локального кэша.

        Args:
            camera_id: идентификатор камеры.

        Returns:
            dict с полями status, actual_fps, drops_count, last_frame_seq.
            Пустой dict если camera_id неизвестен.
        """
        return dict(self._camera_states.get(camera_id, {}))

    def camera_ids(self) -> list[int]:
        """Вернуть список всех известных camera_id, отсортированных по возрастанию."""
        return sorted(self._camera_states.keys())

    # ------------------------------------------------------------------
    # Публичный API — управление callbacks
    # ------------------------------------------------------------------

    def add_callback(self, callback: Callable[[int, str, Any], None]) -> None:
        """Зарегистрировать callback для получения уведомлений об изменениях.

        Args:
            callback: функция вида ``callback(camera_id: int, field: str, value: Any)``.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[int, str, Any], None]) -> None:
        """Удалить ранее зарегистрированный callback."""
        with contextlib.suppress(ValueError):
            self._callbacks.remove(callback)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _on_state_deltas(self, deltas: list[Delta]) -> None:
        """Callback для StateProxy.subscribe.

        Вызывается при получении дельт от StateStore.
        Разбирает пути cameras.{id}.state.{field}, обновляет кэш
        и нотифицирует зарегистрированные callbacks.

        Args:
            deltas: список Delta от StateProxy.
        """
        for delta in deltas:
            match = _CAMERA_STATE_RE.match(delta.path)
            if match is None:
                continue

            camera_id = int(match.group(1))
            field = match.group(2)

            if field not in _TRACKED_FIELDS:
                logger.debug(
                    "CameraStateAdapter: поле '%s' не отслеживается, пропуск", field
                )
                continue

            # Убедиться что запись для этой камеры существует
            if camera_id not in self._camera_states:
                self._camera_states[camera_id] = {
                    "status": "stopped",
                    "actual_fps": 0.0,
                    "drops_count": 0,
                    "last_frame_seq": 0,
                }

            # Обновить кэш
            self._camera_states[camera_id][field] = delta.new_value

            logger.debug(
                "CameraStateAdapter: camera_id=%d, %s=%r",
                camera_id,
                field,
                delta.new_value,
            )

            # Нотифицировать callbacks
            self._notify_callbacks(camera_id, field, delta.new_value)

    def _notify_callbacks(self, camera_id: int, field: str, value: Any) -> None:
        """Вызвать все зарегистрированные callbacks.

        Ошибка в одном callback не прерывает остальные.

        Args:
            camera_id: идентификатор камеры.
            field: имя изменившегося поля.
            value: новое значение.
        """
        for callback in self._callbacks:
            with contextlib.suppress(Exception):
                callback(camera_id, field, value)


__all__ = ["CameraStateAdapter"]
