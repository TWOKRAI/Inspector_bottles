"""RendererCompositorPlugin -- compositing нескольких кадров в один.

Processing-плагин: process(items) → items — объединяет кадры в сетку/side-by-side/PiP.
Работает с ПОЛНЫМ списком items (batch), без @for_each.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin(
    "renderer_compositor",
    category="processing",
    description="Compositing нескольких кадров в один",
)
class RendererCompositorPlugin(ProcessModulePlugin):
    """Compositing нескольких кадров: grid, side-by-side, picture-in-picture."""

    name = "renderer_compositor"
    category = "processing"

    inputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="BGR-кадры от разных источников",
        ),
    ]
    outputs = [
        Port(
            name="composite_frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Составной кадр",
        ),
    ]

    commands = {
        "set_layout": "set_layout",
        "toggle_overlay": "toggle_overlay",
    }

    # --- Инициализация ---

    def configure(self, ctx: PluginContext) -> None:
        """Парсинг параметров конфигурации."""
        cfg = ctx.config
        self._ctx = ctx

        self._layout_mode: str = cfg.get("layout_mode", "grid")
        self._grid_cols: int = max(1, int(cfg.get("grid_cols", 2)))
        self._grid_rows: int = max(1, int(cfg.get("grid_rows", 2)))
        self._output_width: int = int(cfg.get("output_width", 1280))
        self._output_height: int = int(cfg.get("output_height", 720))
        self._pip_scale: float = float(cfg.get("pip_scale", 0.25))
        self._pip_position: str = cfg.get("pip_position", "top_right")
        self._overlay_enabled: bool = bool(cfg.get("overlay_enabled", True))
        self._overlay_font_scale: float = float(cfg.get("overlay_font_scale", 0.5))

        ctx.log_info(
            f"RendererCompositorPlugin: layout={self._layout_mode}, "
            f"output={self._output_width}x{self._output_height}, "
            f"overlay={self._overlay_enabled}"
        )

    def start(self, ctx: PluginContext) -> None:
        """No-op — обработка через process()."""

    # --- Основная обработка (batch, без @for_each) ---

    def process(self, items: list[dict]) -> list[dict]:
        """Compositing всех кадров из items в один составной кадр.

        Принимает список items, извлекает кадры, возвращает список
        с одним item содержащим составной кадр.
        """
        # Извлечь валидные кадры из всех items
        frames = [item["frame"] for item in items if item.get("frame") is not None]

        if not frames:
            # Нет кадров — вернуть входные items без изменений
            return items

        # Compositing по выбранному layout
        if self._layout_mode == "side_by_side":
            composite = self._compose_side_by_side(frames)
        elif self._layout_mode == "pip":
            composite = self._compose_pip(frames)
        else:
            # По умолчанию — grid
            composite = self._compose_grid(frames)

        # Текстовый overlay при необходимости
        if self._overlay_enabled:
            self._add_overlay(composite, len(frames))

        # Возвращаем один item с составным кадром
        # Оба ключа для совместимости с pipeline
        return [
            {
                "frame": composite,
                "composite_frame": composite,
                "source_count": len(frames),
            }
        ]

    # --- Layout-методы ---

    def _compose_grid(self, frames: list[np.ndarray]) -> np.ndarray:
        """Grid layout: NxM ячеек.

        Распределяет кадры по ячейкам сетки grid_cols × grid_rows.
        Лишние кадры (свыше cols*rows) игнорируются.
        """
        canvas = np.zeros(
            (self._output_height, self._output_width, 3), dtype=np.uint8
        )
        cell_w = self._output_width // self._grid_cols
        cell_h = self._output_height // self._grid_rows

        for i, frame in enumerate(frames):
            if i >= self._grid_cols * self._grid_rows:
                # Ячейки заполнены — остальные кадры пропускаем
                break
            row = i // self._grid_cols
            col = i % self._grid_cols
            resized = cv2.resize(frame, (cell_w, cell_h))
            y0 = row * cell_h
            x0 = col * cell_w
            canvas[y0 : y0 + cell_h, x0 : x0 + cell_w] = resized

        return canvas

    def _compose_side_by_side(self, frames: list[np.ndarray]) -> np.ndarray:
        """Side-by-side layout: кадры расположены горизонтально.

        Каждый кадр масштабируется до output_height, ширина делится поровну.
        """
        n = len(frames)
        cell_w = self._output_width // max(n, 1)

        # Масштабируем каждый кадр до размера ячейки
        resized = [cv2.resize(f, (cell_w, self._output_height)) for f in frames]

        # Создаём canvas и размещаем кадры горизонтально
        canvas = np.zeros(
            (self._output_height, self._output_width, 3), dtype=np.uint8
        )
        x = 0
        for r in resized:
            w = r.shape[1]
            canvas[:, x : x + w] = r
            x += w

        return canvas

    def _compose_pip(self, frames: list[np.ndarray]) -> np.ndarray:
        """Picture-in-Picture layout.

        Первый кадр — основной (полный размер), остальные — мини-окна в углу.
        Поддерживает до 4 PiP-окон, позиция задаётся pip_position.
        """
        # Основной кадр занимает весь output
        main = cv2.resize(frames[0], (self._output_width, self._output_height))
        canvas = main.copy()

        pip_w = int(self._output_width * self._pip_scale)
        pip_h = int(self._output_height * self._pip_scale)

        # Словарь допустимых позиций PiP-окна
        positions = {
            "top_right": (self._output_width - pip_w - 10, 10),
            "top_left": (10, 10),
            "bottom_right": (self._output_width - pip_w - 10, self._output_height - pip_h - 10),
            "bottom_left": (10, self._output_height - pip_h - 10),
        }

        pos_keys = list(positions.keys())

        # Размещаем дополнительные кадры как PiP
        for i, frame in enumerate(frames[1:], 1):
            if i > 4:
                # Максимум 4 PiP-окна
                break
            # Первое дополнительное — в заданную позицию, остальные — по кругу
            if i == 1:
                pos_key = self._pip_position
                if pos_key not in positions:
                    pos_key = "top_right"
            else:
                pos_key = pos_keys[(i - 1) % len(pos_keys)]

            x0, y0 = positions[pos_key]
            pip_frame = cv2.resize(frame, (pip_w, pip_h))
            canvas[y0 : y0 + pip_h, x0 : x0 + pip_w] = pip_frame

        return canvas

    # --- Overlay ---

    def _add_overlay(self, canvas: np.ndarray, source_count: int) -> None:
        """Добавить текстовый overlay с количеством источников."""
        text = f"Sources: {source_count}"
        cv2.putText(
            canvas,
            text,
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            self._overlay_font_scale,
            (255, 255, 255),
            1,
        )

    # --- Команды ---

    def set_layout(self, data: dict) -> dict:
        """Изменить layout в runtime."""
        mode = data.get("layout_mode", self._layout_mode)
        if mode in ("grid", "side_by_side", "pip"):
            self._layout_mode = mode

        if "grid_cols" in data:
            self._grid_cols = max(1, int(data["grid_cols"]))
        if "grid_rows" in data:
            self._grid_rows = max(1, int(data["grid_rows"]))

        self._ctx.log_info(
            f"RendererCompositorPlugin: layout обновлён → {self._layout_mode}, "
            f"grid={self._grid_cols}x{self._grid_rows}"
        )
        return {"status": "ok", "layout_mode": self._layout_mode}

    def toggle_overlay(self, data: dict) -> dict:
        """Переключить видимость текстового overlay."""
        self._overlay_enabled = not self._overlay_enabled
        self._ctx.log_info(
            f"RendererCompositorPlugin: overlay → {self._overlay_enabled}"
        )
        return {"status": "ok", "overlay_enabled": self._overlay_enabled}
