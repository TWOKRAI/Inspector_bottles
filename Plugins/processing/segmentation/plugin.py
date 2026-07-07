"""SegmentationPlugin — удаление фона (человек на белом) через MediaPipe.

Порт логики из projects_obsidian/sketch_robot/modules/segmentation.py (MediaPipe
selfie segmenter). Вход BGR-кадр → кадр с человеком на белом фоне (для дисплея
«Оригинал») + бинарная маска человека.

MediaPipe лениво инициализируется при первом кадре. Модель selfie_segmenter.tflite
ищется в ~/.cache/sketch_robot/ (там уже лежит) или data/models/.

Graceful degradation: если пакет `mediapipe` не установлен — плагин пропускает
кадр БЕЗ изменений (passthrough) и логирует подсказку один раз. Установка:
    uv pip install mediapipe
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import SegmentationRegisters


def _resolve_model(explicit: str | None) -> str | None:
    """Найти selfie_segmenter.tflite. None если не найден (тогда — деградация)."""
    home = Path.home()
    repo_root = Path(__file__).resolve().parents[3]  # <repo>/Plugins/processing/segmentation/plugin.py → [3]=<repo>
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        home / ".cache" / "sketch_robot" / "selfie_segmenter.tflite",
        home / ".cache" / "inspector_sketch" / "selfie_segmenter.tflite",
        repo_root / "data" / "models" / "selfie_segmenter.tflite",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


@register_plugin(
    "segmentation",
    category="processing",
    description="Удаление фона (человек на белом) через MediaPipe selfie segmenter",
)
class SegmentationPlugin(ProcessModulePlugin):
    """BGR-кадр → человек на белом фоне (frame) + маска человека (mask)."""

    name = "segmentation"
    category = "processing"
    thread_safe = False  # MediaPipe segmenter — stateful

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Человек на белом фоне"),
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска человека 0/255"),
    ]

    commands: dict[str, str] = {}
    register_class = SegmentationRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import SegmentationPluginConfig

        return SegmentationPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: SegmentationRegisters = self._init_register(ctx)
        self._segmenter: Any = None
        self._mp: Any = None
        self._degraded = False  # mediapipe недоступен → passthrough
        ctx.log_info(f"SegmentationPlugin: threshold={self._reg.threshold} bg_white={self._reg.bg_white}")

    def shutdown(self, ctx: PluginContext) -> None:
        if self._segmenter is not None:
            try:
                self._segmenter.close()
            except Exception:  # no-health: defensive close на shutdown
                pass
        self._segmenter = None
        ctx.log_info("SegmentationPlugin: shutdown")

    def _init_model(self) -> bool:
        """Инициализировать MediaPipe. Вернуть False при недоступности (деградация)."""
        try:
            import mediapipe as mp
        except ImportError:  # no-health: optional-import gate (mediapipe) — осознанная деградация
            self._ctx.log_error(
                "SegmentationPlugin: пакет mediapipe не установлен — фон НЕ удаляется "
                "(passthrough). Установите: uv pip install mediapipe"
            )
            return False

        model_path = _resolve_model(self._reg.model_path or None)
        if model_path is None:
            self._ctx.log_error(
                "SegmentationPlugin: модель selfie_segmenter.tflite не найдена "
                "(~/.cache/sketch_robot/ или data/models/) — passthrough"
            )
            return False

        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = mp.tasks.vision.ImageSegmenterOptions(
            base_options=base_options,
            output_confidence_masks=True,
            output_category_mask=False,
        )
        self._mp = mp
        self._segmenter = mp.tasks.vision.ImageSegmenter.create_from_options(options)
        self._ctx.log_info(f"SegmentationPlugin: MediaPipe загружен (model={model_path})")
        return True

    def _degraded_frame(self, frame):
        """Кадр с подсказкой, когда mediapipe недоступен (фон не убран)."""
        out = frame.copy()
        cv2.putText(out, "SEGMENTATION OFF", (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        cv2.putText(out, "install: uv pip install mediapipe", (12, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        return out

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        # Деградация без mediapipe — показываем кадр с подсказкой (не молча).
        if self._degraded:
            return {**item, "frame": self._degraded_frame(frame)}
        if self._segmenter is None:
            if not self._init_model():
                self._degraded = True
                return {**item, "frame": self._degraded_frame(frame)}

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            result = self._segmenter.segment(mp_image)
            confidence = result.confidence_masks[0].numpy_view().squeeze()
        except Exception as exc:  # pragma: no cover - защита горячего пути
            self._ctx.health.report_error(exc, context="segmentation.process")
            self._ctx.log_error(f"SegmentationPlugin: сегментация упала: {exc}")
            self._degraded = True
            return item

        mask = (confidence > float(self._reg.threshold)).astype(np.uint8)
        bg_value = 255 if self._reg.bg_white else 0
        background = np.full_like(frame, bg_value)
        mask_3ch = np.stack([mask, mask, mask], axis=-1)
        masked = np.where(mask_3ch == 1, frame, background)

        return {**item, "frame": masked, "mask": (mask * 255).astype(np.uint8)}
