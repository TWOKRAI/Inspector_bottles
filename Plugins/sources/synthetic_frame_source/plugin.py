"""SyntheticFrameSourcePlugin -- генератор синтетических кадров БЕЗ реального железа.

Source-плагин: produce() возвращает BGR-кадры заданного размера с дешёвым
детерминированным содержимым (без cv2/np.random — не хотим, чтобы стоимость
генерации пикселей маскировала IPC/SHM-накладные в perf-замерах). Throttle до
целевого FPS делает SourceProducer (source_target_fps в топологии) — плагин
сам никакой паузы не делает, ровно как CapturePlugin полагается на блокирующее
чтение камеры (здесь вместо этого — синтетическая генерация, мгновенная).

Назначение (Ф7 G.1): tier «синтетика» для baseline.md — тракт camera→consumer
без зависимости от вебкамеры/Hikvision, воспроизводимый на любой машине CI.
НЕ регистрируется ни в одном прод-рецепте — только в отдельном perf-рецепте
(``multiprocess_prototype/recipes/g1_perf_probe.yaml``).
"""

from __future__ import annotations

import time

import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

# Максимальное значение счётчика кадров (с rollover как в capture/camera_service).
_FRAME_ID_MODULO = 100_000


@register_plugin(
    "synthetic_frame_source",
    category="source",
    description="Синтетический генератор кадров (без камеры) — perf-baseline Ф7 G.1",
)
class SyntheticFrameSourcePlugin(ProcessModulePlugin):
    """Генерирует BGR-кадры заданного размера без обращения к железу.

    Lifecycle:
        configure() -- параметры кадра (ширина/высота/канал)
        produce()   -- вернуть один синтетический кадр (вызывается SourceProducer)
    """

    name = "synthetic_frame_source"
    category = "source"

    inputs = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Синтетический BGR-кадр"),
    ]
    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка размера кадра. Без сети/устройств — конфигурировать нечего."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._frame_count = 0

        # Базовый кадр выделяется один раз (lazy allocation избыточна — размер
        # известен из конфига сразу); produce() отдаёт .copy() — как реальная
        # камера, каждый кадр независимый объект, а не общий буфер.
        self._base_frame = np.full((self._height, self._width, 3), 128, dtype=np.uint8)

        ctx.log_info(f"SyntheticFrameSourcePlugin[{self._camera_id}]: {self._width}x{self._height} (без камеры)")

    def produce(self) -> list[dict]:
        """Вернуть один синтетический кадр.

        Дешёвая генерация: копия базового кадра + штамп счётчика в верхней
        строке (первые min(frame_count, width) байт первого канала) — узнаваемо
        меняется от кадра к кадру, не требует cv2.putText/np.random.
        """
        self._frame_count = (self._frame_count % _FRAME_ID_MODULO) + 1
        frame = self._base_frame.copy()
        stamp_len = min(self._frame_count, self._width)
        frame[0, :stamp_len, 0] = 255

        return [
            {
                "frame": frame,
                "camera_id": self._camera_id,
                "seq_id": self._frame_count,
                "frame_id": self._frame_count,
                "timestamp": time.monotonic(),
                "width": self._width,
                "height": self._height,
                "channels": 3,
                "dtype": "uint8",
            }
        ]
