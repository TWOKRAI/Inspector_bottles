"""CircleDetectorPlugin -- детекция окружностей через cv2.HoughCircles.

Processing-плагин: process(items) → items с найденными окружностями.

Универсальная обёртка с выбором режима детектора (классический HOUGH_GRADIENT
и точный HOUGH_GRADIENT_ALT) и настраиваемым препроцессингом. Возвращает
список детекций вида {"center": [x, y], "radius": r} и опционально рисует
окружности на кадре.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import CircleDetectorRegisters


@register_plugin(
    "circle_detector",
    category="processing",
    description="Детекция окружностей (центр + радиус) через cv2.HoughCircles",
)
class CircleDetectorPlugin(ProcessModulePlugin):
    """Grayscale → blur → HoughCircles → detections (center, radius)."""

    name = "circle_detector"
    category = "processing"

    # Источник детекции выбирается register'ом input_key. Оба входа optional:
    #   input_key=frame — детекция по сырому кадру (порт frame, дефолт);
    #   input_key=mask  — по бинарной маске (порт mask, напр. от hsv_mask в чейне).
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (input_key=frame)"),
        Port(name="mask", dtype="image/gray", shape="(H, W)", optional=True, description="Маска (input_key=mask)"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр (опционально с окружностями)"),
        Port(name="detections", dtype="list[dict]", shape="N", description="Список окружностей (center, radius)"),
        Port(name="mask", dtype="image/gray", shape="(H, W)", optional=True, description="Маска (при keep_mask)"),
    ]

    commands = {
        "set_hough_params": "set_hough_params",
        "set_mode": "set_mode",
        "set_radius_range": "set_radius_range",
        "toggle_draw_circles": "toggle_draw_circles",
    }

    register_class = CircleDetectorRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        ctx.log_info(
            f"CircleDetectorPlugin: mode={self._reg.mode}, blur={self._reg.blur_method}"
            f"({self._reg.blur_ksize}), dp={self._reg.dp}, min_dist={self._reg.min_dist}, "
            f"param1={self._reg.param1}, param2={self._reg.param2}, "
            f"radius=[{self._reg.min_radius}, {self._reg.max_radius}], draw={self._reg.draw_circles}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """[input_key] → grayscale → blur → HoughCircles → detections.

        input_key='frame' — детекция по сырому кадру (по умолчанию).
        input_key='mask'  — по бинарной маске от hsv_mask (Hough по чистой маске
        даёт меньше ложных). Потреблённый ключ-маска дропается (не гоним по IPC).
        """
        src = item.get(self._reg.input_key)
        if src is None:
            return None

        gray = self._to_gray(src)
        gray = self._apply_blur(gray)

        method, args = self._safe_hough_args()
        try:
            circles = cv2.HoughCircles(gray, method, **args)
        except Exception as exc:
            # HoughCircles на вырожденном содержимом (полностью белый/чёрный кадр,
            # degenerate-аккумулятор) кидает НЕ только cv2.error, но и generic C++
            # exception ("Unknown C++ exception from OpenCV code"). Ловим всё — иначе
            # необработанное исключение уходит в PipelineExecutor → circuit breaker
            # (5 подряд → детекция стоит 60с). Плагин самодостаточен: вернуть [] детекций.
            self._ctx.health.report_error(exc, context="circle_detector.hough", throttle=30.0)
            self._ctx.log_error(f"CircleDetectorPlugin: HoughCircles failed ({args}): {exc}")
            return self._finish(item, [])

        detections: list[dict] = []
        if circles is not None:
            # HoughCircles → ndarray формы (1, N, 3): [x, y, r]
            for x, y, r in np.around(circles[0]).astype(int):
                detections.append({"center": [int(x), int(y)], "radius": int(r)})

        # Рисуем только на 3-канальном кадре (на бинарной маске цветной круг бессмыслен).
        # На КОПИИ, не на src: src может быть SHM-буфером / общим кадром для других веток
        # (detector → line/crop/draw/maskview) — мутация загрязнила бы их (и датасет).
        if self._reg.draw_circles and detections and src.ndim == 3:
            drawn = src.copy()
            self._draw(drawn, detections)
            item = {**item, "frame": drawn}

        return self._finish(item, detections)

    def _finish(self, item: dict, detections: list[dict]) -> dict:
        """Собрать выход: добавить detections, дропнуть потреблённую маску.

        Маску дропаем (не гоним по IPC), КРОМЕ keep_mask=true — тогда оставляем
        (нужна display-ветке, напр. показать маску на отдельном дисплее).
        """
        out = {**item, "detections": detections}
        if self._reg.input_key != "frame" and not self._reg.keep_mask:
            out.pop(self._reg.input_key, None)
        return out

    # --- Вспомогательные ---

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        """Привести кадр к одноканальному grayscale."""
        if frame.ndim == 3 and frame.shape[2] == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.ndim == 3 and frame.shape[2] == 1:
            return frame[:, :, 0]
        return frame

    def _apply_blur(self, gray: np.ndarray) -> np.ndarray:
        """Сглаживание по выбранному методу. Ядро приводится к нечётному ≥ 1."""
        method = self._reg.blur_method
        if method == "none":
            return gray
        k = int(self._reg.blur_ksize)
        if k < 1:
            k = 1
        if k % 2 == 0:
            k += 1  # ksize обязан быть нечётным
        if method == "gaussian":
            return cv2.GaussianBlur(gray, (k, k), 0)
        # median по умолчанию
        return cv2.medianBlur(gray, k)

    def _resolve_method(self) -> tuple[int, bool]:
        """Константа метода Хафа + флаг «это ALT-режим».

        HOUGH_GRADIENT_ALT доступен с OpenCV 4.3; при отсутствии — fallback
        на классический (тогда и границы параметров считаем по классике).
        """
        if self._reg.mode == "gradient_alt" and hasattr(cv2, "HOUGH_GRADIENT_ALT"):
            return cv2.HOUGH_GRADIENT_ALT, True
        return cv2.HOUGH_GRADIENT, False

    def _safe_hough_args(self) -> tuple[int, dict]:
        """Собрать kwargs для HoughCircles с клампингом под выбранный режим.

        cv2.HoughCircles кидает cv2.error при недопустимых значениях, причём
        допустимый диапазон param2 зависит от метода:
          - HOUGH_GRADIENT     — param2 > 0 (порог аккумулятора);
          - HOUGH_GRADIENT_ALT — 0.0 ≤ param2 < 1.0 (кругловатость).
        Дефолтное param2=30 валидно для gradient, но падает в alt — поэтому
        нормализуем здесь, а не полагаемся на static-границы register/команд.
        """
        method, is_alt = self._resolve_method()

        # dp > 0 (иначе деление на ноль в аккумуляторе)
        dp = max(0.1, float(self._reg.dp))
        # minDist > 0, param1 > 0 — оба кидают cv2.error при ≤ 0
        min_dist = max(1.0, float(self._reg.min_dist))
        param1 = max(1.0, float(self._reg.param1))

        param2 = float(self._reg.param2)
        if is_alt:
            # ALT: строго < 1.0. Значение из классики (напр. 30) клампим к 0.9.
            param2 = param2 if 0.0 <= param2 < 1.0 else 0.9
        else:
            # GRADIENT: строго > 0.
            param2 = max(1.0, param2)

        # Радиусы ≥ 0; при max < min (оба > 0) меняем местами, чтобы не терять круги
        min_r = max(0, int(self._reg.min_radius))
        max_r = max(0, int(self._reg.max_radius))
        if 0 < max_r < min_r:
            min_r, max_r = max_r, min_r

        return method, {
            "dp": dp,
            "minDist": min_dist,
            "param1": param1,
            "param2": param2,
            "minRadius": min_r,
            "maxRadius": max_r,
        }

    def _draw(self, frame: np.ndarray, detections: list[dict]) -> None:
        """Нарисовать окружности и (опц.) центры на кадре."""
        color = tuple(int(c) for c in self._reg.circle_color_bgr)
        thickness = int(self._reg.circle_thickness)
        for det in detections:
            cx, cy = det["center"]
            r = det["radius"]
            cv2.circle(frame, (cx, cy), r, color, thickness)
            if self._reg.draw_center:
                cv2.circle(frame, (cx, cy), 2, color, -1)

    # --- Команды ---

    def _apply_fields(self, data: dict, fields: tuple[str, ...]) -> list[str]:
        """Присвоить разрешённые поля register, отсеивая невалидные значения.

        Используем update_field() — он валидирует значение ДО setattr
        (FieldMeta.validate_value), поэтому отклонённое значение не попадает
        в модель и не оставляет её в битом состоянии (validate_assignment
        ревалидирует всю модель и «застрявшее» плохое поле сломало бы
        последующие присваивания). Возвращаем список отклонённых полей.
        """
        rejected: list[str] = []
        for field in fields:
            if field not in data:
                continue
            ok, _err = self._reg.update_field(field, data[field])
            if not ok:
                rejected.append(field)
        return rejected

    def set_hough_params(self, data: dict) -> dict:
        """Обновить параметры HoughCircles (dp, min_dist, param1, param2) в runtime."""
        rejected = self._apply_fields(data, ("dp", "min_dist", "param1", "param2"))
        return {
            "status": "ok" if not rejected else "partial",
            "rejected": rejected,
            "dp": self._reg.dp,
            "min_dist": self._reg.min_dist,
            "param1": self._reg.param1,
            "param2": self._reg.param2,
        }

    def set_mode(self, data: dict) -> dict:
        """Переключить режим детектора и/или метод препроцессинга."""
        rejected = self._apply_fields(data, ("mode", "blur_method", "blur_ksize"))
        return {
            "status": "ok" if not rejected else "partial",
            "rejected": rejected,
            "mode": self._reg.mode,
            "blur_method": self._reg.blur_method,
        }

    def set_radius_range(self, data: dict) -> dict:
        """Обновить min/max радиус в runtime."""
        rejected = self._apply_fields(data, ("min_radius", "max_radius"))
        return {
            "status": "ok" if not rejected else "partial",
            "rejected": rejected,
            "min_radius": self._reg.min_radius,
            "max_radius": self._reg.max_radius,
        }

    def toggle_draw_circles(self, data: dict) -> dict:
        """Переключить отрисовку окружностей."""
        self._reg.draw_circles = not self._reg.draw_circles
        return {"status": "ok", "draw_circles": self._reg.draw_circles}
