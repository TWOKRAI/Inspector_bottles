"""InspectorManager — буферизация items по (camera_id, seq_id) для fan-in.

Без fan-in (нет total_regions или == 0/1) — немедленный pass-through.
С fan-in — буферизация до полной коллекции или timeout.

Используется DataReceiver внутри GenericProcess.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class InspectorManager:
    """Буферизация items по (camera_id, seq_id) для fan-in сценариев.

    Логика:
    - item без total_regions (или == 0, 1) → немедленно on_ready([item])
    - item с total_regions > 1 → буфер по (camera_id, seq_id)
    - Коллекция готова → on_ready(items)
    - Timeout → flush неполной коллекции
    """

    def __init__(
        self,
        timeout_sec: float = 0.5,
        on_ready: Callable[[list[dict]], None] | None = None,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._timeout_sec = timeout_sec
        self._on_ready = on_ready or (lambda items: None)
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)

        # Буфер: {(camera_id, seq_id): {"region_name": item, ...}}
        self._buffer: dict[tuple[int, int], dict[str, dict]] = {}
        # Время первого item в коллекции: {(camera_id, seq_id): monotonic timestamp}
        self._timestamps: dict[tuple[int, int], float] = {}
        # Ожидаемое количество регионов: {(camera_id, seq_id): total_regions}
        self._expected: dict[tuple[int, int], int] = {}

        self._lock = threading.Lock()

    def on_item(self, item: dict) -> None:
        """Принять один item.

        Без fan-in (нет total_regions или <= 1) → сразу on_ready([item]).
        С fan-in → буферизация по (camera_id, seq_id).
        """
        total_regions = item.get("total_regions", 0)

        # Pass-through: нет fan-in
        if not total_regions or total_regions <= 1:
            self._on_ready([item])
            return

        camera_id = item.get("camera_id", 0)
        seq_id = item.get("seq_id", 0)
        region_name = item.get("region_name", f"region_{camera_id}_{seq_id}")
        key = (camera_id, seq_id)

        with self._lock:
            # Инициализация буфера для новой коллекции
            if key not in self._buffer:
                self._buffer[key] = {}
                self._timestamps[key] = time.monotonic()
                self._expected[key] = total_regions

            # Дубликат region_name — перезапись с warning
            if region_name in self._buffer[key]:
                self._log_error(
                    f"InspectorManager: дубликат region_name='{region_name}' "
                    f"для (camera_id={camera_id}, seq_id={seq_id}), перезапись"
                )

            self._buffer[key][region_name] = item

            # Проверка готовности
            if len(self._buffer[key]) >= self._expected[key]:
                items = list(self._buffer[key].values())
                del self._buffer[key]
                del self._timestamps[key]
                del self._expected[key]
                # Вызов on_ready вне lock для избежания deadlock
                ready_items = items
            else:
                ready_items = None

        if ready_items is not None:
            self._on_ready(ready_items)

    def check_timeouts(self) -> None:
        """Проверить и выдать просроченные коллекции.

        Вызывается периодически из Data Worker.
        Также удаляет записи старше 2 * timeout_sec.
        """
        now = time.monotonic()
        flush_keys: list[tuple[int, int]] = []
        flush_items: list[list[dict]] = []

        with self._lock:
            keys_to_check = list(self._timestamps.keys())
            for key in keys_to_check:
                elapsed = now - self._timestamps[key]
                if elapsed > self._timeout_sec:
                    # Timeout — flush неполной коллекции
                    items = list(self._buffer[key].values())
                    flush_keys.append(key)
                    flush_items.append(items)
                    self._log_info(
                        f"InspectorManager: timeout flush (camera_id={key[0]}, "
                        f"seq_id={key[1]}), got {len(items)}/{self._expected[key]}"
                    )

            # Удаление flushed записей
            for key in flush_keys:
                del self._buffer[key]
                del self._timestamps[key]
                del self._expected[key]

        # Вызов on_ready вне lock
        for items in flush_items:
            self._on_ready(items)

    @property
    def pending_count(self) -> int:
        """Количество незавершённых коллекций в буфере."""
        with self._lock:
            return len(self._buffer)
