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
from ...observability_declarations import declared_metrics


def ensure_framework_producers() -> None:
    """Втянуть модули-производители метрик ФРЕЙМВОРКА, чтобы каталог был полон к чтению.

    **Почему это вообще нужно.** Каталог наполняется ИМПОРТОМ: ``declare_metric``
    стоит рядом с вычислением величины. До Ф0.3 «полон ли он» решал порядок
    импортов вызывающего кода — ``shm`` объявляет ``heartbeat/process_heartbeat.py``
    на уровне модуля, а ``fps`` / ``latency_ms`` / ``effective_hz`` /
    ``cycle_duration_ms`` — ``heartbeat/telemetry.py``, который на дороге загрузки
    процесса втягивался ЛЕНИВО, из ``ProcessHeartbeat._make_gate``. Первая сверка
    конфига с каталогом случалась РАНЬШЕ этого импорта и объявляла живые метрики
    опечатками (ревью 2026-08-28, находка M1: семь ложных WARNING за один boot
    ``webcam_sketch``). Неполный каталог при этом не пуст — ``shm`` в нём уже
    есть, — поэтому страж «пустой каталог → судить не по чему» в
    :meth:`TelemetryPublishConfig.unknown_metrics` его не ловил и поймать не мог.

    **Почему функция лежит здесь, а не в ``observability_declarations``.** Тот
    модуль намеренно сделан листом без зависимостей: он объявляет лог-источники
    для модулей, которые сам логгер и импортирует, и обратный импорт оттуда
    замыкал кольцо — воспроизведённый ``ImportError: partially initialized
    module`` описан в его же докстроке. Здесь зависимость направлена «вверх», к
    heartbeat, и кольца не образует.

    **Почему импорт локальный, внутри функции.** ``heartbeat/telemetry.py`` сам
    импортирует :func:`gated_metrics` из ЭТОГО файла на уровне модуля. Импорт
    производителей на уровне модуля был бы тем самым кольцом; внутри функции он
    исполняется, когда оба модуля уже собраны.

    **Цена повторного вызова — поиск в ``sys.modules`` и ничего сверх.** Оператор
    ``import`` после первого раза не исполняет модуль и даже не доходит до
    ``sys.meta_path``; это измерено, а не предположено — см.
    ``tests/test_metric_catalog_producer_hazards.py::TestCatalogWarmupCost``.

    **Ошибка импорта не глушится.** Производитель, который не импортируется, —
    это сломанный фреймворк, а не «каталог чуть беднее»: молчаливый ``except``
    здесь вернул бы ровно тот дефект, ради которого функция и заведена, только
    уже без единого следа в логе.
    """
    from ..heartbeat import process_heartbeat, telemetry  # noqa: F401


def gated_metrics() -> tuple[str, ...]:
    """Каталог метрик под publisher-gate — Ф8.1, вместо кортежа-литерала.

    Раньше здесь стоял ``GATED_METRICS = ("fps", …)``: завести метрику значило
    править файл фреймворка, то есть конструктор требовал правки конструктора.
    Теперь каталог наполняется объявлениями рядом с вычислением метрики
    (:func:`~...observability_declarations.declare_metric`), и приложение либо
    плагин заводит свою метрику, не трогая фреймворк вовсе.

    **Функция, а не константа-снимок.** Реестр наполняется импортом, и снимок,
    взятый на импорте ЭТОГО модуля, застал бы только тех производителей, что
    успели импортироваться раньше, — то есть каталог зависел бы от порядка
    импортов, ровно от чего реестр объявлений и защищает.

    ``status`` воркеров и health/errors в каталог не входят — они публикуются
    всегда (инвариант плана «errors/status always-on»), и гейта у них нет.

    Ф0.3: перед чтением реестра каталог ДОБИРАЕТСЯ до полного
    (:func:`ensure_framework_producers`) — «функция, а не снимок» защищала от
    устаревания, но не от чтения раньше производителя. Добор стоит здесь, а не у
    каждого вызывающего: читателей каталога пятеро (гейт heartbeat, readback
    ``introspect.telemetry``, строки GUI, ``unknown_metrics``, тесты), и правило
    «сначала импортируй производителей» пришлось бы помнить всем пятерым.
    """
    ensure_framework_producers()
    return declared_metrics()


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

    - ``default_enabled`` — что делать с метрикой, для которой в ``metrics`` нет
      правила. ``True`` (дефолт, обратная совместимость) — конфиг только
      сужает/переопределяет: неизвестная метрика включена. ``False`` —
      переворачивает секцию в белый список: неизвестная метрика ВЫКЛЮЧЕНА, и
      публикуют только те, что явно перечислены в ``metrics`` с ``enabled=True``.
    - ``default_interval_sec`` — интервал публикации по умолчанию для метрик без
      явного ``interval_sec`` (и для неизвестных метрик).
    - ``metrics`` — per-метрика/группа override по суффиксу пути публикации.

    Неизвестная (не перечисленная в ``metrics``) метрика резолвится в
    ``(default_enabled, default_interval_sec)`` — при дефолтном
    ``default_enabled=True`` это дословно прежнее поведение («по умолчанию
    ВКЛЮЧЕНА»); при ``default_enabled=False`` конфиг работает белым списком.
    """

    default_enabled: Annotated[
        bool,
        FieldMeta(
            "Публиковать неперечисленные метрики по умолчанию",
            info="False переворачивает секцию в белый список: метрика без "
            "явного правила в metrics не публикуется и не считается, пока её "
            "не включит metrics[<имя>].enabled=true. True (по умолчанию) — "
            "прежнее поведение: неизвестная метрика включена.",
        ),
    ] = True
    default_interval_sec: Annotated[
        float,
        FieldMeta("Интервал публикации метрики по умолчанию, сек", min=0.0),
    ] = 1.0
    tick_sec: Annotated[
        Optional[float],
        FieldMeta(
            "Период телеметрийного тика, сек — как часто процесс просыпается публиковать "
            "телеметрию (верхняя ступень частотной лестницы, Task 1.2). None → наследовать "
            "heartbeat_interval процесса (backward-compat: прежние 5.0с). Эффективный тик = "
            "min(heartbeat_interval, tick_sec); метрика не публикуется чаще этого тика.",
            min=0.0,
        ),
    ] = None
    metrics: Annotated[
        Dict[str, MetricRule],
        FieldMeta(
            "Правила per-метрика/группа (ключ — суффикс пути: fps/latency_ms/effective_hz/cycle_duration_ms/shm)"
        ),  # noqa: E501
    ] = Field(default_factory=dict)

    def resolve(self, metric_name: str) -> tuple[bool, float]:
        """Разрешить (enabled, interval_sec) для метрики по её суффиксу.

        Наследование:
          - метрика не в ``metrics`` → ``(default_enabled, default_interval_sec)``
            (по умолчанию ``default_enabled=True`` — конфиг не «белый список»;
            при ``default_enabled=False`` неперечисленная метрика выключена);
          - правило есть, ``interval_sec is None`` → интервал = ``default_interval_sec``;
          - правило есть, ``interval_sec`` задан → его значение.

        Returns:
            ``(enabled, interval_sec)`` — enabled=False означает «не публиковать
            и не считать» метрику.
        """
        rule = self.metrics.get(metric_name)
        if rule is None:
            return self.default_enabled, self.default_interval_sec
        interval = rule.interval_sec if rule.interval_sec is not None else self.default_interval_sec
        return rule.enabled, interval

    def unknown_metrics(self) -> set[str]:
        """Ключи ``metrics``, отсутствующие в каталоге :func:`gated_metrics` — опечатка.

        Task 2.3: правило на несуществующий суффикс (например ``latency`` вместо
        ``latency_ms``) раньше было тихим no-op — ``resolve()`` его просто никогда не
        находит (метрика не публикуется, но и никакой диагностики). Метод НЕ отвергает
        такие ключи (forward-compat: новая метрика в старом процессе не должна ронять
        reload) — только позволяет вызывающему коду залогировать/вернуть предупреждение.

        **Пустой каталог означает «судить не по чему», а не «известных нет»** (Ф8.1).
        Пока каталог был литералом, он существовал всегда; теперь он наполняется
        импортом производителей, и в процессе, который телеметрию не считает, он пуст
        законно. Без этой ветки КАЖДЫЙ ключ там объявлялся бы опечаткой — ложная
        тревога на ровном месте, класс «молчащий детектор» наоборот. Ветка не
        прикрывает настоящий промах: как только хоть один производитель импортирован,
        неизвестный ключ снова слышен, и это стережёт отдельный тест.

        Returns:
            Множество ключей ``metrics``, которых нет в каталоге (пусто — все ключи
            известны либо каталог пуст).
        """
        catalog = gated_metrics()
        if not catalog:
            return set()
        return set(self.metrics) - set(catalog)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализовать в dict (Dict at Boundary — уходит в IPC/конфиг)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Any) -> "TelemetryPublishConfig":
        """Собрать из dict (граница процесса). ``None``/частичный → дефолты."""
        return cls.model_validate(data or {})


__all__ = ["ensure_framework_producers", "gated_metrics", "MetricRule", "TelemetryPublishConfig"]
