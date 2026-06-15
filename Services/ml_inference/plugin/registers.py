"""MLInferenceRegisters — параметры инференса для GUI-инспектора.

register = единый источник параметров + FieldMeta для авто-генерации виджетов в
инспекторе Pipeline. Плагин всегда работает через self._reg.

Поле `model` использует кастомный виджет `model_picker` (динамический выпадающий
список моделей из data/models) — регистрируется фабрикой форм фронтенда.
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("MLInferenceRegistersV1")
class MLInferenceRegisters(SchemaBase):
    """Параметры и телеметрия плагина инференса."""

    # --- Выбор модели ---
    model: Annotated[
        str,
        FieldMeta(
            "Модель",
            info="Выбор весов из data/models (нужен sidecar .yaml)",
            widget="model_picker",  # кастомный динамический dropdown
        ),
    ] = ""
    device: Annotated[
        Literal["cpu", "cuda"],
        FieldMeta("Устройство", info="cpu | cuda (если доступна)"),
    ] = "cpu"

    # --- Параметры вывода ---
    confidence_threshold: Annotated[
        float,
        FieldMeta("Порог уверенности", info="Отсекать предсказания ниже порога", min=0.0, max=1.0, round_k=2),
    ] = 0.5
    top_k: Annotated[
        int,
        FieldMeta("Top-K", info="Сколько верхних классов возвращать", min=1, max=20),
    ] = 5

    # --- Производительность ---
    inference_every_n: Annotated[
        int,
        FieldMeta(
            "Инференс каждый N-й кадр",
            info="1 = каждый кадр; >1 снижает нагрузку, между — reuse результата",
            min=1,
            max=60,
        ),
    ] = 1

    # --- Отрисовка ---
    draw_overlay: Annotated[
        bool,
        FieldMeta("Рисовать результат на кадре", info="Топ-1 класс + confidence поверх кадра"),
    ] = True

    # --- Телеметрия (readonly) ---
    loaded_model: Annotated[str, FieldMeta("Загружена модель", readonly=True)] = ""
    active_providers: Annotated[
        str,
        FieldMeta(
            "Активные providers",
            info="Фактическое устройство инференса; показывает молчаливый CPU-fallback при device=cuda",
            readonly=True,
        ),
    ] = ""
    last_label: Annotated[str, FieldMeta("Последний класс", readonly=True)] = ""
    last_confidence: Annotated[float, FieldMeta("Последняя уверенность", readonly=True)] = 0.0
    # КОНТРАКТ: last_angle_deg валиден ТОЛЬКО при last_angle_valid=True. Потребитель
    # (робот-доворот) ОБЯЗАН сначала проверить last_angle_valid; при False — НЕ доворачивать
    # (full-симметрия/нет детекции/нет угла). Иначе доворот по неопределённому углу.
    last_angle_deg: Annotated[float, FieldMeta("Последний угол", readonly=True, unit="°")] = 0.0
    last_angle_valid: Annotated[bool, FieldMeta("Угол определён", readonly=True)] = False
    avg_latency_ms: Annotated[float, FieldMeta("Латентность (сред.)", readonly=True, unit="ms")] = 0.0
    last_latency_ms: Annotated[float, FieldMeta("Латентность (послед.)", readonly=True, unit="ms")] = 0.0
    max_latency_ms: Annotated[float, FieldMeta("Латентность (макс. за окно)", readonly=True, unit="ms")] = 0.0
    inference_fps: Annotated[float, FieldMeta("Инференсов в секунду", readonly=True, unit="fps")] = 0.0
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
