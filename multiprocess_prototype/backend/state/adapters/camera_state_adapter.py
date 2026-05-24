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
import re
from typing import Any, Callable

from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase

# Regex для разбора пути cameras.{id}.state.{field}
_CAMERA_STATE_RE = re.compile(r"^cameras\.(\d+)\.state\.(.+)$")

# Поля, которые транслируются в callback (camera_id, field, value)
_TRACKED_FIELDS = frozenset({"status", "actual_fps", "drops_count", "last_frame_seq"})


class CameraStateAdapter(StateAdapterBase):
    """Адаптер камер: читает данные из StateProxy вместо CameraRegistry.

    Подписывается на cameras.*.state.** через StateProxy.
    При получении дельт — нотифицирует зарегистрированные callbacks.

    Обратная совместимость: callback-сигнатура (camera_id: int, field: str, value: Any)
    аналогична CameraRegistry.

    Пример использования::

        adapter = CameraStateAdapter(num_cameras=2)
        adapter.bind(state_proxy)
        adapter.connect()
        adapter.add_callback(lambda cid, field, val: print(cid, field, val))

        # Читать состояние камеры
        state = adapter.get_camera_state(0)  # {"status": "running", "actual_fps": 29.5, ...}

    Args:
        num_cameras: ожидаемое количество камер (используется для инициализации кэша).
        state_proxy: GuiStateProxy или StateProxy (опционален, можно bind() позже).
        logger: менеджер логирования (LoggerManager или совместимый).
        stats: менеджер статистики.
        error: менеджер ошибок.
    """

    def __init__(
        self,
        num_cameras: int = 0,
        state_proxy: Any | None = None,
        logger: Any | None = None,
        stats: Any | None = None,
        error: Any | None = None,
    ) -> None:
        super().__init__(state_proxy=state_proxy, logger=logger, stats=stats, error=error)
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

    # -------------------------------------------------------------------
    # StateAdapterBase — реализация абстрактных методов
    # -------------------------------------------------------------------

    def _subscribe_all(self) -> None:
        """Подписаться на cameras.*.state.** через StateProxy.

        Вызывается базовым классом из connect().
        """
        sub_id = self._proxy.subscribe(
            "cameras.*.state.**",
            self._on_state_deltas,
            exclude_self=False,
        )
        self._sub_ids.append(sub_id)
        self._log_info(
            f"CameraStateAdapter: подписан на cameras.*.state.**, num_cameras={self._num_cameras}, sub_id={sub_id}"
        )

    def _unsubscribe_all(self) -> None:
        """Отписаться от StateProxy.

        Вызывается базовым классом из disconnect().
        """
        for sub_id in self._sub_ids:
            self._proxy.unsubscribe(sub_id)
        self._log_info("CameraStateAdapter: подписки отменены")

    def sync_domain_to_state(self) -> None:
        """Записать локальный кэш камер -> StateProxy.

        Полезно для начальной инициализации StateStore с заглушечными значениями.
        """
        if self._proxy is None:
            self._log_warning("CameraStateAdapter: sync_domain_to_state — нет proxy")
            return

        for camera_id, state_dict in self._camera_states.items():
            for field, value in state_dict.items():
                path = f"cameras.{camera_id}.state.{field}"
                try:
                    self._mark_pending(path)
                    self._proxy.set(path, value)
                except Exception:
                    self._pending_paths.discard(path)

    def sync_state_to_domain(self) -> None:
        """Прочитать состояние камер из StateProxy -> локальный кэш.

        Полезно при начальном подключении для получения актуальных данных.
        """
        if self._proxy is None:
            self._log_warning("CameraStateAdapter: sync_state_to_domain — нет proxy")
            return

        for camera_id in list(self._camera_states.keys()):
            for field in _TRACKED_FIELDS:
                path = f"cameras.{camera_id}.state.{field}"
                try:
                    value = self._proxy.get(path)
                    if value is not None:
                        self._camera_states[camera_id][field] = value
                except Exception:  # nosec B110 — graceful: поле отсутствует в store, пропускаем
                    pass

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
            # Anti-loop: пропускаем эхо собственных set() из sync_domain_to_state
            if self._check_and_clear_pending(delta.path):
                continue

            match = _CAMERA_STATE_RE.match(delta.path)
            if match is None:
                continue

            camera_id = int(match.group(1))
            field = match.group(2)

            if field not in _TRACKED_FIELDS:
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
