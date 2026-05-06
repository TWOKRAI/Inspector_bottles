"""SourceProducer — produce()-loop для source-плагинов.

plugin.produce() → FrameShmMiddleware.strip_and_write() → IPC send в chain_targets.
Smart sleep для target FPS.

Используется GenericProcess как LOOP worker.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ..plugins.base import ProcessModulePlugin
from .frame_shm_middleware import FrameShmMiddleware


class SourceProducer:
    """Produce-loop для source-плагинов.

    Args:
        plugin: source-плагин с методом produce()
        shm_middleware: для записи frame в SHM
        send_fn: callable для отправки IPC
        chain_targets: куда отправлять items
        target_fps: целевой FPS (для throttle)
        log_info: callback
        log_error: callback
    """

    def __init__(
        self,
        plugin: ProcessModulePlugin,
        shm_middleware: FrameShmMiddleware | None,
        send_fn: Callable,
        chain_targets: list[str],
        target_fps: float = 25.0,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._plugin = plugin
        self._shm = shm_middleware
        self._send = send_fn
        self._chain_targets = chain_targets
        self._target_interval = 1.0 / max(target_fps, 1.0)
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """LOOP worker: produce() → SHM write → IPC send.

        Smart sleep: вычитает время produce() из target_interval.
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            t_start = time.monotonic()

            try:
                items = self._plugin.produce()
            except NotImplementedError:
                self._log_error(
                    f"SourceProducer: {self._plugin.name} не реализует produce()"
                )
                stop_event.set()
                return
            except Exception as e:
                self._log_error(f"SourceProducer: {self._plugin.name}.produce() error: {e}")
                items = []

            # Отправить каждый item
            for item in items:
                self._send_item(item)

            # Smart sleep
            elapsed = time.monotonic() - t_start
            sleep_time = self._target_interval - elapsed
            if sleep_time > 0:
                # Спим порциями для отзывчивости на stop_event
                deadline = time.monotonic() + sleep_time
                while time.monotonic() < deadline and not stop_event.is_set():
                    time.sleep(min(0.01, deadline - time.monotonic()))

    def _send_item(self, item: dict) -> None:
        """SHM write + IPC send одного item."""
        # SHM write: убрать frame, записать в SHM
        if self._shm and "frame" in item:
            item = self._shm.strip_and_write(item)

        # Routing: item["target"] → per-item, else chain_targets
        per_item_target = item.pop("target", None)
        targets = [per_item_target] if per_item_target else self._chain_targets

        for target in targets:
            msg = {
                "target": target,
                "type": "data",
                "channel": "data",
                "data": item,
            }
            self._send(target, msg)
