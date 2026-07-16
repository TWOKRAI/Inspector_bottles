# -*- coding: utf-8 -*-
"""
TelemetryPublishConfig — декларативный контракт публикации телеметрии процесса.

Одна секция ``telemetry.publish`` в конфиге процесса управляет тем, КАКИЕ метрики
процесс вообще считает и публикует в дерево StateStore и КАК ЧАСТО (per-метрика/
группа вкл/выкл + интервал). Это **publisher-gate** — главный рычаг «не грузить,
если не надо»: выключенная метрика не кладётся в merge → нет записи в дерево/IPC/GUI.

Ключи ``metrics`` — имя МЕТРИКИ/группы по СУФФИКСУ пути публикации, не полный путь:
``fps`` / ``latency_ms`` (агрегат карточки процесса), ``effective_hz`` /
``cycle_duration_ms`` (per-worker строки), ``shm`` (счётчики кадрового транспорта).

Инвариант плана: ошибки и ``status`` воркеров/health публикуются ВСЕГДА — они не
проходят через этот конфиг (см. ``plans/telemetry-publish-control.md``, «Errors always-on»).

Dict at Boundary: между процессами едет dict (``from_dict`` / ``to_dict``); Pydantic
живёт только внутри процесса. Схема — framework-контракт; приложение задаёт значения
рецептом/``system.yaml`` (плумбинг — отдельная задача PC 1.3, здесь только контракт).
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from ...data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("MetricRule")
class MetricRule(SchemaBase):
    """Правило публикации одной метрики/группы.

    ``interval_sec is None`` → наследовать ``default_interval_sec`` родителя
    (``TelemetryPublishConfig``). ``enabled=False`` → метрика не считается и не
    публикуется (максимум «не грузить»).
    """

    enabled: Annotated[bool, FieldMeta("Публиковать метрику")] = True
    interval_sec: Annotated[
        Optional[float],
        FieldMeta("Мин. интервал публикации, сек (None → наследовать default_interval_sec)", min=0.0),
    ] = None


@register_schema("TelemetryPublishConfig")
class TelemetryPublishConfig(SchemaBase):
    """Секция публикации телеметрии процесса (per-метрика вкл/выкл + частота).

    - ``default_interval_sec`` — интервал публикации по умолчанию для метрик без
      явного ``interval_sec`` (и для неизвестных метрик).
    - ``metrics`` — per-метрика/группа override по суффиксу пути публикации.

    Неизвестная (не перечисленная в ``metrics``) метрика по умолчанию ВКЛЮЧЕНА с
    ``default_interval_sec`` — конфиг только сужает/переопределяет, а не «включает
    белый список».
    """

    default_interval_sec: Annotated[
        float,
        FieldMeta("Интервал публикации метрики по умолчанию, сек", min=0.0),
    ] = 1.0
    metrics: Annotated[
        Dict[str, MetricRule],
        FieldMeta(
            "Правила per-метрика/группа (ключ — суффикс пути: fps/latency_ms/effective_hz/cycle_duration_ms/shm)"
        ),  # noqa: E501
    ] = Field(default_factory=dict)

    def resolve(self, metric_name: str) -> tuple[bool, float]:
        """Разрешить (enabled, interval_sec) для метрики по её суффиксу.

        Наследование:
          - метрика не в ``metrics`` → ``(True, default_interval_sec)`` (по умолчанию
            включена — конфиг не «белый список»);
          - правило есть, ``interval_sec is None`` → интервал = ``default_interval_sec``;
          - правило есть, ``interval_sec`` задан → его значение.

        Returns:
            ``(enabled, interval_sec)`` — enabled=False означает «не публиковать
            и не считать» метрику.
        """
        rule = self.metrics.get(metric_name)
        if rule is None:
            return True, self.default_interval_sec
        interval = rule.interval_sec if rule.interval_sec is not None else self.default_interval_sec
        return rule.enabled, interval

    def to_dict(self) -> Dict[str, Any]:
        """Сериализовать в dict (Dict at Boundary — уходит в IPC/конфиг)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Any) -> "TelemetryPublishConfig":
        """Собрать из dict (граница процесса). ``None``/частичный → дефолты."""
        return cls.model_validate(data or {})


__all__ = ["MetricRule", "TelemetryPublishConfig"]
