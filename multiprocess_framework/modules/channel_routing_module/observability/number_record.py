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

**Почему форма живёт в базе, а не в ``statistics_module`` (вердикт CTO,
2026-09-05).** Первая редакция положила файл в ``statistics_module/core/``, по
владельцу СМЫСЛА метрики. Персистентность и транспорт записей принадлежат
``channel_routing_module/observability`` (ADR-CRM-009), и там же — единый
нормализатор ``record_display``, который обязан ходить через эту форму. Пока
форма лежала слоем выше, кольцо импортов было воспроизводимо:
``observability/__init__ → observability_store → record_display →
statistics_module/__init__ → channels/log_stats_channel → store_tap →
observability_store`` (частично загруженный). Форма персистируемого числа
принадлежит владельцу персистентности; ``statistics_module`` остаётся владельцем
АГРЕГАЦИИ (та же граница, что провёл ADR-CRM-009), и ничего из этого файла ему
не нужно. Цена перевода нормализатора на форму замерена и названа в ADR-CRM-017.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, Literal, Optional

from ...data_schema_module import FieldMeta, SchemaBase
from .observability_hub import (
    KIND_OBSERVATION,
    KIND_STATS,
    METRIC_GAUGE,
    STATS_AGGREGATE_KEY,
)

#: Роды числа — те же четыре, что у ``statistics_module.core.metric_record.MetricType``.
#: Продублированы литералами намеренно: ``Literal[...]`` в аннотации Pydantic
#: требует констант времени определения класса, а импорт ``MetricType`` сюда
#: втянул бы весь ``metric_record`` в модуль-схему — и вернул бы зависимость
#: базы от слоя выше, ради снятия которой форма сюда и переехала.
#:
#: Расхождение ловит контракт-тест, а не глаз:
#: ``statistics_module/tests/test_number_kind_contract.py`` (сверяет множества и
#: прогоняет каждое живое значение ``MetricType`` через :meth:`NumberRecord.from_hub_record`).
#: Файл заведён добором 2026-09-05 — до него это обещание было пустым: теста,
#: на который ссылалась строка, не существовало.
NumberKind = Literal["counter", "gauge", "timing", "histogram"]


def number_metric_identity(writer: str, name: str) -> Optional[str]:
    """Идентичность одного числа — то, что ложится в колонку ``metric`` (Task 3.1, К4).

    **Одно правило на всю плоскость, в одном месте.** Строку строят ДВА
    потребителя — колонка ``metric`` стора и ``message`` записи наблюдения, — и
    два независимых написания «writer точка metric» разошлись бы молча: запрос
    ``where metric='capture.drops'`` перестал бы находить строку, чей текст
    по-прежнему читается как ``capture.drops``. Поэтому идентичность считается
    здесь, а обе колонки берут ГОТОВОЕ значение.

    **Живёт рядом с формой, а не в нормализаторе.** Правило отвечает на вопрос
    «как зовут ЭТО ЧИСЛО», то есть принадлежит форме числа; после перевода
    ``hub_record_to_display`` на :class:`NumberRecord` (вердикт CTO, 2026-09-05)
    нормализатор импортирует правило отсюда. Обратный порядок замкнул бы кольцо
    внутри пакета: ``record_display`` → ``number_record`` → ``record_display``.

    **Писатель обязателен там, где он есть.** Голое ``drops`` столкнулось бы
    между процессами: у ``camera_0`` и у ``devices`` метрика с одним именем — это
    ДВА разных ряда, а в общем сторе они слились бы в один. Полная идентичность
    (``capture.drops``) — та же, что несёт лист дерева
    (``state.plugins.<writer>.<metric>``), без префикса ``plugins``: он одинаков
    у каждой записи этого рода и поиску ничего не добавляет.

    **Пусто → ``None``, а не пустая строка.** Колонка ``metric`` различает «это
    одно число, вот его имя» и «имени нет» (агрегат окна, лог, ошибка). Пустая
    строка была бы третьим состоянием, неотличимым в SQL от первого: она
    попадает в ``metric = ''`` и НЕ попадает в ``metric IS NULL``, то есть
    строка без имени тихо оседала бы в ряду по имени ``''``.

    Args:
        writer: писатель числа (плагин/компонент) — пусто, если писателя нет
            (одиночная stats-запись менеджера).
        name: имя метрики.

    Returns:
        ``"<writer>.<name>"`` при непустом писателе, ``name`` без него,
        ``None`` — если имени нет вовсе.
    """
    name = str(name or "").strip()
    if not name:
        return None
    writer = str(writer or "").strip()
    return f"{writer}.{name}" if writer else name


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
        # ``value is not None`` НЕ означает «это скаляр»: у ``gauge``-агрегата
        # заполнены ОБА поля (само значение поднимается в ``value``, а окно
        # остаётся в ``aggregate``). Правило читается в одну сторону: «есть
        # ``aggregate`` → число пришло агрегатом окна», и ровно так его и
        # проверяют — иначе читатель вывел бы обратное правило и потерял окно.
        FieldMeta("Распределение", info="Агрегат окна (count/min/max/avg/p95/…); None, если числа пришли не окном"),
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

        Правило — :func:`number_metric_identity`, одно на всю плоскость: тем же
        правилом пользуется нормализатор display-вида (``record_display``), и
        второе написание «writer точка name» разошлось бы с первым молча — именно
        на пустых значениях, где разница между ``None`` и ``"capture."`` решает,
        найдётся ли ряд.
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
          оно и есть значение, а не статистика. **У этого диалекта сегодня нет
          боевого кормильца** — единственный вызывающий вне тестов,
          ``hub_record_to_display``, приходит сюда только с ``kind`` stats или
          observation. Ветка держится потому, что К3 требует схождения ТРЁХ
          диалектов, а разложение снапшота на записи по метрике — вопрос
          открытый; читать её как «живой путь» не надо.

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
