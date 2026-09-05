# -*- coding: utf-8 -*-
"""
NumberRecord — ОДНА форма числа на всю плоскость наблюдаемости (Task 3.1, К3).

**Зачем.** До этой задачи одно и то же число существовало в трёх несовместимых
диалектах, и каждый читатель знал все три:

  1. агрегат окна — ``MetricRecord.aggregate()``: ``{name, type, tags, count |
     value | min/max/avg/p95/sum/buckets}``;
  2. hub-запись сырой метрики — ``{metric, value, metric_type, tags}``;
  3. запись порта наблюдений — ``{writer, metric, value}``.

Имя метрики звалось в них ``name``, ``metric`` и снова ``metric``; тип —
``type``, ``metric_type`` и никак; писателя знал только третий. Нормализатор
display-вида различал их тремя ветками, засыпка колонки ``metric`` — ещё двумя,
GUI — своими. Каждая такая ветка есть место, где четвёртый диалект появится
молча.

Здесь диалекты СХОДЯТСЯ: :meth:`NumberRecord.from_hub_record` — единственная
точка чтения, и новая форма числа добавляется в неё, а не рядом с ней.

**Что эта форма НЕ делает — сказано вслух, потому что граница неочевидна.**
Она не является форматом провода. Записи между процессами по-прежнему едут
теми же тремя dict'ами (их форму пинят и приёмочные тесты, и живой GUI, и
дореформенные строки стора), и подменять их пришлось бы вместе с миграцией
читателей — это отдельная задача. ``NumberRecord`` — форма ВНУТРИ процесса:
её строит тот, кому нужно спросить у числа «как тебя зовут», «одно ты значение
или распределение», «кто тебя написал».

**``value`` и ``aggregate`` — два поля, а не одно.** Число бывает скаляром
(``counter``/``gauge``: «сейчас 29.7») и распределением (``timing``/
``histogram``: «за окно 214 наблюдений, p95 = 3 мс»). Свернуть их в одно поле
значило бы заставить каждого читателя проверять тип значения перед чтением —
то есть вернуть развилку, ради снятия которой форма и заводится.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional

from ...channel_routing_module.observability.observability_hub import (
    KIND_OBSERVATION,
    KIND_STATS,
    METRIC_GAUGE,
    STATS_AGGREGATE_KEY,
)
from ...channel_routing_module.observability.record_display import number_metric_identity
from ...data_schema_module import FieldMeta, SchemaBase

#: Роды числа — те же четыре, что у :class:`..core.metric_record.MetricType`.
#: Продублированы литералами намеренно: ``Literal[...]`` в аннотации Pydantic
#: требует констант времени определения класса, а импорт ``MetricType`` сюда
#: втянул бы весь ``metric_record`` в модуль-схему. Расхождение с живым
#: перечислением ловит контракт-тест, а не глаз.
NumberKind = Literal["counter", "gauge", "timing", "histogram"]


class NumberRecord(SchemaBase):
    """Одно число плоскости наблюдаемости — имя, род, значение и кто его написал.

    Dict at Boundary (правило проекта №1): наружу отдаётся только
    :meth:`to_dict` — plain pickle-safe dict. Внутри процесса — Pydantic-модель,
    как у всех регистров/конфигов на ``SchemaBase`` (тот же приём, что у
    ``ObservationRecord``, ``process_module/plugins/port.py``).
    """

    name: Annotated[
        str,
        FieldMeta("Имя", info="Имя метрики без писателя — 'drops', не 'capture.drops'"),
    ]
    kind: Annotated[
        NumberKind,
        FieldMeta("Род", info="counter | gauge | timing | histogram — тот же словарь, что у MetricType"),
    ]
    value: Annotated[
        Optional[float],
        FieldMeta("Значение", info="Скаляр — для counter/gauge; None, если число пришло распределением"),
    ] = None
    aggregate: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Распределение", info="Агрегат окна (count/min/max/avg/p95/…); None у скаляра"),
    ] = None
    tags: Annotated[
        Dict[str, Any],
        FieldMeta("Теги", info="Серия = имя × теги; у одного имени столько серий, сколько сочетаний"),
    ] = {}
    unit: Annotated[
        str,
        FieldMeta("Единица", info="Единица измерения ('s', 'Hz', 'count'); пусто — не объявлена"),
    ] = ""
    ts: Annotated[
        float,
        FieldMeta("Отметка времени", info="Момент эмиссии, wall-часы процесса-источника"),
    ] = 0.0
    writer: Annotated[
        str,
        FieldMeta("Писатель", info="Плагин/компонент, опубликовавший число; пусто у метрик самого процесса"),
    ] = ""

    def to_dict(self) -> Dict[str, Any]:
        """Plain dict для границы процесса — Dict at Boundary."""
        return self.model_dump()

    @property
    def metric_identity(self) -> Optional[str]:
        """Полное имя числа — то, что ложится в колонку ``metric`` стора (К4).

        Считается НЕ здесь: правило живёт в
        :func:`...channel_routing_module.observability.record_display.number_metric_identity`,
        потому что тем же правилом пользуется нормализатор display-вида, а он
        лежит слоем ниже и импортировать ``statistics_module`` не может (обратный
        импорт замкнул бы кольцо ``statistics → channel_routing → statistics``).
        Второе написание «writer точка name» разошлось бы с первым молча — и
        разошлось бы именно на пустых значениях, где разница между ``None`` и
        ``"capture."`` решает, найдётся ли ряд.
        """
        return number_metric_identity(self.writer, self.name)

    @classmethod
    def from_hub_record(cls, record: Dict[str, Any]) -> Optional["NumberRecord"]:
        """Прочитать ЛЮБОЙ из трёх диалектов числа в одну форму.

        Единственная точка чтения — в этом и весь смысл класса. Четвёртый
        диалект (появится он у телеметрии или у метрик плагина) добавляется
        сюда, и все читатели получают его разом; добавленный «рядом» он
        достался бы только тому читателю, который о нём знает.

        Распознаются:

        * ``kind='observation'`` → ``{writer, metric, value}`` — число порта
          наблюдений. Род — ``gauge``: порт публикует «сколько СЕЙЧАС», иного
          рода у него нет вовсе (см. ``ObservationManager``).
        * ``kind='stats'`` БЕЗ :data:`STATS_AGGREGATE_KEY` → ``{metric, value,
          metric_type, tags}`` — одиночная метрика менеджера.
        * агрегат ОДНОЙ метрики (``{name, type, tags, …}``, как его отдаёт
          ``MetricRecord.aggregate()``) → распределение в поле ``aggregate``.
          Скалярное ``value`` у ``gauge``-агрегата поднимается в ``value``: там
          оно и есть значение, а не статистика.

        **Снапшот окна (``kind='stats'`` С маркером агрегата) — НЕ число, и
        здесь возвращается ``None``.** Он несёт 24.8 метрики в среднем (замер на
        живом файле, максимум 214), единственного имени у него нет, и попытка
        назвать его одним ``NumberRecord`` завела бы имя, которого у строки не
        существует. Разложить снапшот на записи по метрике — отдельное решение
        с известной ценой: горизонт стора упал бы с 47.5 ч до ~1.4 ч (замер),
        поэтому здесь его раскладывает только тот, кто явно этого хочет, обойдя
        ``metrics`` сам.

        Returns:
            ``NumberRecord`` — или ``None``, если запись числом не является
            (снапшот окна, лог, ошибка, мусор). ``None`` здесь — ответ, а не
            отказ: у вызывающего есть ветка «это не число», и молчаливое
            превращение лога в число было бы хуже.
        """
        if not isinstance(record, dict):
            return None
        kind = record.get("kind", "")

        if kind == KIND_OBSERVATION:
            return cls._build(
                name=record.get("metric", ""),
                metric_type=METRIC_GAUGE,
                value=record.get("value"),
                tags=record.get("tags"),
                ts=record.get("ts"),
                writer=record.get("writer", ""),
            )
        if kind == KIND_STATS:
            if record.get(STATS_AGGREGATE_KEY):
                return None
            return cls._build(
                name=record.get("metric", ""),
                metric_type=record.get("metric_type"),
                value=record.get("value"),
                tags=record.get("tags"),
                ts=record.get("ts"),
                writer=record.get("writer", ""),
            )
        # Диалект агрегата ОДНОЙ метрики: у него нет ``kind`` вовсе — это не
        # запись хаба, а элемент списка ``metrics`` внутри снапшота.
        if "name" in record and "type" in record:
            return cls._build(
                name=record.get("name", ""),
                metric_type=record.get("type"),
                value=record.get("value"),
                tags=record.get("tags"),
                ts=record.get("ts"),
                writer=record.get("writer", ""),
                aggregate=record,
            )
        return None

    @classmethod
    def _build(
        cls,
        *,
        name: Any,
        metric_type: Any,
        value: Any,
        tags: Any,
        ts: Any,
        writer: Any,
        aggregate: Optional[Dict[str, Any]] = None,
    ) -> Optional["NumberRecord"]:
        """Собрать запись из СЫРЫХ значений провода, не роняя вызывающего.

        **Схема строгая, а вход — чужой.** ``metric_type`` приезжает с провода
        и бывает пустым (у записи порта его нет), незнакомым (опечатка
        плагина), не-строкой. Дай мы ``ValidationError`` подняться из
        нормализатора — одна кривая запись уронила бы весь дренаж пачки, то
        есть плоскость наблюдаемости упала бы от того, что кто-то неверно назвал
        метрику. Поэтому непригодный вход даёт ``None`` («это не число»), а не
        исключение: у вызывающего эта ветка уже есть.

        ``value`` приводится к ``float`` тут же и своим ``try``: у ``gauge``
        значением бывает строка/``None``, и ``Optional[float]`` Pydantic'а
        отверг бы ВСЮ запись из-за одного поля, потеряв заодно имя и теги.
        """
        text_name = str(name or "").strip()
        if not text_name:
            return None
        kind = str(metric_type or "").strip().lower()
        if kind not in ("counter", "gauge", "timing", "histogram"):
            return None
        try:
            numeric = None if value is None else float(value)
        except (TypeError, ValueError):
            numeric = None
        try:
            moment = float(ts or 0.0)
        except (TypeError, ValueError):
            moment = 0.0
        return cls(
            name=text_name,
            kind=kind,  # type: ignore[arg-type]  # проверено членством строкой выше
            value=numeric,
            aggregate=dict(aggregate) if isinstance(aggregate, dict) else None,
            tags=dict(tags) if isinstance(tags, dict) else {},
            unit="",
            ts=moment,
            writer=str(writer or ""),
        )
