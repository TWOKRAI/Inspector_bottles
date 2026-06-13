"""CenterCropPlugin -- динамический квадратный crop вокруг найденного центра.

Processing-плагин (fan-out 1→N): на вход — merged item (Join кадр+overlay),
несущий frame и filtered (сработавшие на line_filter центры, item["filtered"][*]["xy"]).
На каждый сработавший центр вырезает квадрат side_px и эмитит отдельный item с
вырезанным кадром и sidecar-метаданными (для frame_saver write_sidecar).

Сценарий: камера → ROI → circle_detector → line_filter(enter_zone) →[Join]→ center_crop → frame_saver.
Назначение — сбор датасета: один пойманный объект = один квадратный кадр + .json рядом.

Координата центра берётся ТОЛЬКО из filtered (триггер line_filter). Нет filtered → 0 выходов
(ничего не сохраняется). radius для sidecar восстанавливается сопоставлением xy с detections.

Stateless относительно кадров (вся темпоральная логика — в line_filter) → thread_safe=True.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from .registers import CenterCropRegisters

# Ключи, прокидываемые из входного item в каждый выходной (корреляция/трассировка).
_CARRY_KEYS = ("seq_id", "camera_id", "frame_id", "timestamp")


@register_plugin(
    "center_crop",
    category="processing",
    description="Квадратный crop вокруг сработавшего центра (line_filter) → кадр + sidecar",
)
class CenterCropPlugin(ProcessModulePlugin):
    """filtered (xy) + frame → N квадратных вырезов side_px + sidecar."""

    name = "center_crop"
    category = "processing"
    thread_safe = True

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр для выреза (ROI)"),
        Port(name="trigger_in", dtype="dict", shape="-", description="Overlay-item line_filter (несёт filtered)"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(side, side, 3)", description="Вырезанный квадрат"),
    ]

    commands = {
        "set_side": "set_side",
    }

    register_class = CenterCropRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg: CenterCropRegisters = self._init_register(ctx)
        ctx.log_info(
            f"CenterCropPlugin: side={self._reg.side_px}px, drop_partial={self._reg.drop_partial}, "
            f"pad_if_oob={self._reg.pad_if_oob}"
        )

    # --- Обработка (fan-out: один вход → N вырезов) ---

    def process(self, items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for item in items:
            frame = item.get("frame")
            if frame is None:
                continue
            filtered = item.get("filtered")
            if not isinstance(filtered, list) or not filtered:
                continue  # нет сработавших центров → нечего вырезать/сохранять
            detections = item.get("detections") if isinstance(item.get("detections"), list) else []

            for k, event in enumerate(filtered):
                xy = self._event_xy(event)
                if xy is None:
                    continue
                cx, cy = xy
                crop = self._crop_square(frame, cx, cy)
                if crop is None:
                    continue  # drop_partial: вырез вышел за границу
                out.append(self._build_item(item, crop, cx, cy, detections, event, k))
        return out

    @staticmethod
    def _event_xy(event: object) -> tuple[int, int] | None:
        """Достать координату центра из события line_filter (xy) — толерантно."""
        if not isinstance(event, dict):
            return None
        xy = event.get("xy") or event.get("center")
        if not isinstance(xy, (list, tuple)) or len(xy) < 2:
            return None
        return int(round(float(xy[0]))), int(round(float(xy[1])))

    # --- Вырез квадрата с учётом границ кадра ---

    def _crop_square(self, frame: np.ndarray, cx: int, cy: int) -> np.ndarray | None:
        """Квадрат side_px вокруг (cx, cy). Поведение у границы — по register.

        Возвращает ndarray (копию) или None, если drop_partial и вырез частично вне кадра.
        """
        side = int(self._reg.side_px)
        half = side // 2
        x0, y0 = cx - half, cy - half
        x1, y1 = x0 + side, y0 + side  # ширина/высота ровно = side
        h, w = frame.shape[:2]

        if x0 >= 0 and y0 >= 0 and x1 <= w and y1 <= h:
            return frame[y0:y1, x0:x1].copy()  # copy: отвязать от SHM-буфера

        # Частично (или полностью) вне кадра.
        if self._reg.drop_partial:
            return None

        # Перекрытие выреза с кадром.
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(w, x1), min(h, y1)

        if self._reg.pad_if_oob:
            canvas = self._pad_canvas(side, frame)
            if sx1 > sx0 and sy1 > sy0:
                dx0, dy0 = sx0 - x0, sy0 - y0
                canvas[dy0 : dy0 + (sy1 - sy0), dx0 : dx0 + (sx1 - sx0)] = frame[sy0:sy1, sx0:sx1]
            return canvas

        # clamp: вырез обрезан к границам (меньше стороны).
        if sx1 <= sx0 or sy1 <= sy0:
            return None  # центр вне кадра целиком — выреза нет
        return frame[sy0:sy1, sx0:sx1].copy()

    def _pad_canvas(self, side: int, frame: np.ndarray) -> np.ndarray:
        """side×side холст, залитый pad_color (под формат/каналы кадра)."""
        color = [int(c) for c in self._reg.pad_color_bgr]
        if frame.ndim == 3:
            c = frame.shape[2]
            canvas = np.zeros((side, side, c), dtype=frame.dtype)
            canvas[:] = (color + [0, 0, 0])[:c]
        else:  # grayscale
            canvas = np.full((side, side), color[0] if color else 0, dtype=frame.dtype)
        return canvas

    # --- Радиус для sidecar: сопоставить xy с detection-кругом ---

    def _match_radius(self, cx: int, cy: int, detections: list) -> int | None:
        dist = int(self._reg.radius_match_dist)
        if dist <= 0 or not detections:
            return None
        best_r: int | None = None
        best_d2 = dist * dist
        for d in detections:
            if not isinstance(d, dict):
                continue
            ctr = d.get("center")
            if not isinstance(ctr, (list, tuple)) or len(ctr) < 2:
                continue
            dx, dy = cx - float(ctr[0]), cy - float(ctr[1])
            d2 = dx * dx + dy * dy
            if d2 <= best_d2:
                best_d2 = d2
                best_r = int(d.get("radius", 0))
        return best_r

    # --- Сборка выходного item ---

    def _build_item(
        self,
        src: dict,
        crop: np.ndarray,
        cx: int,
        cy: int,
        detections: list,
        event: dict,
        index: int,
    ) -> dict:
        radius = self._match_radius(cx, cy, detections)
        sidecar = {
            "center_px": [cx, cy],
            "radius_px": radius,
            "side_px": int(self._reg.side_px),
            "crop_h": int(crop.shape[0]),
            "crop_w": int(crop.shape[1]),
            "track_id": event.get("id"),
            "direction": event.get("direction"),
        }
        for key in _CARRY_KEYS:
            if key in src:
                sidecar[key] = src[key]

        result: dict = {"data_type": "frame", "frame": crop, "sidecar": sidecar, "crop_index": index}
        for key in _CARRY_KEYS:
            if key in src:
                result[key] = src[key]
        return result

    # --- Команды ---

    def set_side(self, data: dict) -> dict:
        """Изменить сторону квадрата в runtime."""
        ok, _err = self._reg.update_field("side_px", data.get("side_px"))
        return {"status": "ok" if ok else "error", "side_px": self._reg.side_px}
