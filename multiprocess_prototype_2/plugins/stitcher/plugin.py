"""StitcherPlugin — склейка регионов в единый кадр.

Получает region_processed от нескольких процессов → буферизует по seq_id →
когда все регионы собраны (или timeout) → размещает на canvas по координатам →
записывает в SHM → отправляет frame_ready в GUI.

Порядок наложения: сначала default (фон), затем остальные регионы поверх.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("stitcher", category="processing", description="Склейка регионов в единый кадр")
class StitcherPlugin(ProcessModulePlugin):
    """Склейка регионов по координатам на canvas. Processing-плагин."""

    name = "stitcher"
    category = "processing"

    inputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Обработанный регион"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Склеенный кадр"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: ожидаемые регионы, буфер по seq_id."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._expected_regions: list[str] = cfg.get("expected_regions", [])
        self._layout: str = cfg.get("layout", "original")
        self._timeout_sec: float = cfg.get("timeout_sec", 0.5)
        self._target: str = cfg.get("target", "gui")

        # Буфер: {seq_id: {region_name: region_data_dict}}
        self._buffer: dict[int, dict[str, dict]] = {}
        self._buffer_timestamps: dict[int, float] = {}
        self._buffer_lock = threading.Lock()

        self._ctx = ctx

        # Слушаем region_processed от processing-процессов
        ctx.router_manager.register_message_handler(
            "region_processed", self._on_region_processed
        )

        ctx.log_info(
            f"StitcherPlugin[{self._camera_id}]: configured, "
            f"expected_regions={self._expected_regions}, target={self._target}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "stitcher_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"StitcherPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"StitcherPlugin[{self._camera_id}]: shutdown")

    # --- Обработка ---

    def _on_region_processed(self, msg: dict) -> None:
        """Handler: добавить регион в буфер по seq_id."""
        data = msg.get("data", {})
        seq_id = data.get("seq_id", 0)
        region_name = data.get("region_name", "unknown")

        with self._buffer_lock:
            if seq_id not in self._buffer:
                self._buffer[seq_id] = {}
                self._buffer_timestamps[seq_id] = time.monotonic()
            self._buffer[seq_id][region_name] = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: проверяет буфер, собирает готовые кадры."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            ready_seq_id = self._find_ready_frame()
            if ready_seq_id is None:
                time.sleep(0.005)
                continue

            # Извлекаем готовый набор регионов
            with self._buffer_lock:
                regions_data = self._buffer.pop(ready_seq_id, {})
                self._buffer_timestamps.pop(ready_seq_id, None)

            if not regions_data:
                continue

            # Склеиваем canvas
            canvas = self._stitch(regions_data)
            if canvas is None:
                continue

            # Записываем в SHM
            mm = self._ctx.memory_manager
            if mm is None:
                continue

            owner = f"camera_{self._camera_id}"
            slot_name = f"stitched_{self._camera_id}"
            shm_actual = mm.write_images(owner, slot_name, [canvas], 0)

            # Отправляем frame_ready в GUI
            out_data = {
                "camera_id": self._camera_id,
                "shm_name": slot_name,
                "shm_index": 0,
                "shm_owner": owner,
                "shm_actual_name": shm_actual,
                "width": canvas.shape[1],
                "height": canvas.shape[0],
                "channels": 3,
                "dtype": "uint8",
                "seq_id": ready_seq_id,
                "frame_id": ready_seq_id,
                "timestamp": time.monotonic(),
            }
            self._ctx.io.send_data(self._target, "frame_ready", out_data)

    def _find_ready_frame(self) -> int | None:
        """Найти seq_id для которого собраны все регионы или вышел timeout."""
        now = time.monotonic()
        expected_set = set(self._expected_regions)

        with self._buffer_lock:
            for seq_id, regions in list(self._buffer.items()):
                collected = set(regions.keys())
                # Все регионы собраны
                if collected >= expected_set:
                    return seq_id
                # Timeout — отправляем что есть
                ts = self._buffer_timestamps.get(seq_id, now)
                if (now - ts) > self._timeout_sec:
                    return seq_id

            # Очистка очень старых записей (>2с)
            for seq_id, ts in list(self._buffer_timestamps.items()):
                if (now - ts) > 2.0:
                    self._buffer.pop(seq_id, None)
                    self._buffer_timestamps.pop(seq_id, None)

        return None

    def _stitch(self, regions_data: dict[str, dict]) -> np.ndarray | None:
        """Склеить регионы на canvas по координатам из метаданных."""
        mm = self._ctx.memory_manager
        if mm is None:
            return None

        # Определяем canvas size из первого региона
        canvas_w = 0
        canvas_h = 0
        for data in regions_data.values():
            cw = data.get("canvas_width", 0)
            ch = data.get("canvas_height", 0)
            if cw > 0 and ch > 0:
                canvas_w = max(canvas_w, cw)
                canvas_h = max(canvas_h, ch)

        if canvas_w == 0 or canvas_h == 0:
            return None

        # Создаём чёрный canvas
        canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

        # Порядок наложения: сначала default_region (фон), потом остальные поверх
        # Сортируем: default_region первым
        sorted_names = sorted(
            regions_data.keys(),
            key=lambda n: 0 if "default" in n else 1
        )

        for region_name in sorted_names:
            data = regions_data[region_name]
            shm_name = data.get("shm_name")
            shm_index = data.get("shm_index", 0)
            owner = data.get("shm_owner", f"camera_{self._camera_id}")

            if not shm_name:
                continue

            # Читаем обработанный регион из SHM
            # Попытка 1: через MemoryManager (если handles открыты в этом процессе)
            region_frame = mm.read_images(owner, shm_name, shm_index)

            # Попытка 2: прямое чтение по shm_actual_name (cross-process)
            if region_frame is None:
                region_frame = self._read_via_actual_name(data)

            if region_frame is None:
                continue

            # Размещаем по координатам
            ox = int(data.get("original_x", 0))
            oy = int(data.get("original_y", 0))
            rh, rw = region_frame.shape[:2]

            # Safe-clamp к canvas
            x1, y1 = max(0, ox), max(0, oy)
            x2 = min(canvas_w, ox + rw)
            y2 = min(canvas_h, oy + rh)

            # Crop region если выходит за canvas
            src_x1 = x1 - ox
            src_y1 = y1 - oy
            src_x2 = src_x1 + (x2 - x1)
            src_y2 = src_y1 + (y2 - y1)

            if x2 > x1 and y2 > y1:
                canvas[y1:y2, x1:x2] = region_frame[src_y1:src_y2, src_x1:src_x2]

        return canvas

    @staticmethod
    def _read_via_actual_name(data: dict) -> np.ndarray | None:
        """Прочитать кадр напрямую из SharedMemory по shm_actual_name (cross-process).

        Повторяет логику FrameShmMiddleware.on_receive fallback.
        """
        shm_actual_name = data.get("shm_actual_name")
        if not shm_actual_name:
            return None

        try:
            from multiprocessing import shared_memory as _shm_mod
            import struct as _struct

            shm = _shm_mod.SharedMemory(name=shm_actual_name, create=False)
            try:
                buf = shm.buf
                # Заголовок: num_images (uint32)
                num_images = _struct.unpack("I", buf[0:4])[0]
                if num_images > 0:
                    # h, w, c (3x uint32) + dtype char (1 byte)
                    h, w, c = _struct.unpack("III", buf[4:16])
                    dtype_char = chr(buf[16])
                    dtype = np.dtype(dtype_char)
                    offset = 17
                    pixel_count = h * w * c
                    arr = np.frombuffer(buf, dtype=dtype, count=pixel_count, offset=offset)
                    return arr.reshape((h, w, c)).copy()
            finally:
                shm.close()
        except Exception:
            return None
