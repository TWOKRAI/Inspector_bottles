"""RendererCompositorPlugin -- compositing нескольких кадров в один.

Processing-плагин: process(items) → items — объединяет кадры в сетку/side-by-side/PiP.
Работает с ПОЛНЫМ списком items (batch), без @for_each.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin

from .registers import RendererCompositorRegisters


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

    register_class = RendererCompositorRegisters

    # --- Инициализация ---

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        ctx.log_info(
            f"RendererCompositorPlugin: layout={self._reg.layout_mode}, "
            f"output={self._reg.output_width}x{self._reg.output_height}, "
            f"overlay={self._reg.overlay_enabled}"
        )

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
        if self._reg.layout_mode == "side_by_side":
            composite = self._compose_side_by_side(frames)
        elif self._reg.layout_mode == "pip":
            composite = self._compose_pip(frames)
        else:
            # По умолчанию — grid
            composite = self._compose_grid(frames)

        # Текстовый overlay при необходимости
        if self._reg.overlay_enabled:
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
        grid_cols = max(1, self._reg.grid_cols)
        grid_rows = max(1, self._reg.grid_rows)
        canvas = np.zeros(
            (self._reg.output_height, self._reg.output_width, 3), dtype=np.uint8
        )
        cell_w = self._reg.output_width // grid_cols
        cell_h = self._reg.output_height // grid_rows

        for i, frame in enumerate(frames):
            if i >= grid_cols * grid_rows:
                # Ячейки заполнены — остальные кадры пропускаем
                break
            row = i // grid_cols
            col = i % grid_cols
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
        cell_w = self._reg.output_width // max(n, 1)

        # Масштабируем каждый кадр до размера ячейки
        resized = [cv2.resize(f, (cell_w, self._reg.output_height)) for f in frames]

        # Создаём canvas и размещаем кадры горизонтально
        canvas = np.zeros(
            (self._reg.output_height, self._reg.output_width, 3), dtype=np.uint8
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
        main = cv2.resize(frames[0], (self._reg.output_width, self._reg.output_height))
        canvas = main.copy()

        pip_w = int(self._reg.output_width * self._reg.pip_scale)
        pip_h = int(self._reg.output_height * self._reg.pip_scale)

        # Словарь допустимых позиций PiP-окна
        positions = {
            "top_right": (self._reg.output_width - pip_w - 10, 10),
            "top_left": (10, 10),
            "bottom_right": (self._reg.output_width - pip_w - 10, self._reg.output_height - pip_h - 10),
            "bottom_left": (10, self._reg.output_height - pip_h - 10),
        }

        pos_keys = list(positions.keys())

        # Размещаем дополнительные кадры как PiP
        for i, frame in enumerate(frames[1:], 1):
            if i > 4:
                # Максимум 4 PiP-окна
                break
            # Первое дополнительное — в заданную позицию, остальные — по кругу
            if i == 1:
                pos_key = self._reg.pip_position
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
            self._reg.overlay_font_scale,
            (255, 255, 255),
            1,
        )

    # --- Команды ---

    def set_layout(self, data: dict) -> dict:
        """Изменить layout в runtime."""
        mode = data.get("layout_mode", self._reg.layout_mode)
        if mode in ("grid", "side_by_side", "pip"):
            self._reg.layout_mode = mode

        # Обновляем остальные поля кроме layout_mode (он уже обработан выше с валидацией)
        for field in type(self._reg).model_fields:
            if field in data and field != "layout_mode":
                setattr(self._reg, field, data[field])

        self._ctx.log_info(
            f"RendererCompositorPlugin: layout обновлён → {self._reg.layout_mode}, "
            f"grid={self._reg.grid_cols}x{self._reg.grid_rows}"
        )
        return {"status": "ok", "layout_mode": self._reg.layout_mode}

    def toggle_overlay(self, data: dict) -> dict:
        """Переключить видимость текстового overlay."""
        self._reg.overlay_enabled = not self._reg.overlay_enabled
        self._ctx.log_info(
            f"RendererCompositorPlugin: overlay → {self._reg.overlay_enabled}"
        )
        return {"status": "ok", "overlay_enabled": self._reg.overlay_enabled}
