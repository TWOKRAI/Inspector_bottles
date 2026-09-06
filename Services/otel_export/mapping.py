# -*- coding: utf-8 -*-
"""Display-запись -> модель OTel Logs (Task 1.1) и фильтр числовой плоскости (Task 1.3).

**Что здесь может сломаться, учитывая, как оно устроено.**

1. *`extra` НЕ однороден — и одна ветка разбора неверна ровно наполовину.*
   Замер снимка 1f40ce0d (`docs/audits/2026-09-06_otel-input-shape.md`, §3):
   у `kind ∈ {log, error}` `extra` вложенный (`{"context": {...}}`), у
   `kind ∈ {stats, observation}` — плоский (`value`/`metrics`/`tags`). Маппер
   разбирает только первую форму, и это законно ровно потому, что вторую он
   ОТКАЗЫВАЕТСЯ обрабатывать раньше, чем прикоснётся к `extra`. Поменяй порядок
   — и первая же числовая запись даст `KeyError` в потоке приёма.
2. *`Attributes = {}` проходит критерий изъятия наравне с правильной сборкой.*
   У 18 из 18 log-записей снимка остаток `extra.context` после изъятий ПУСТ:
   шесть полей, пять забирает Resource, шестое (`origin`) изымается здесь. То
   есть «атрибутов не бывает» и «изъяли ровно шесть ключей» на живом входе дают
   один результат. Единственное, что их различает, — незнакомый ключ контекста,
   который обязан ДОЕХАТЬ до `Attributes`. Поэтому изымается ЧЁРНЫЙ список
   (:data:`NON_ATTRIBUTE_CONTEXT_KEYS`), а не собирается белый.
3. *`severity_number` — копия, а не пересчёт.* Шкала записи
   (`channel_routing_module/levels.py`: 5/9/13/17/21) уже словарь OTel. Ранг
   0…4 выглядит правдоподобно и даёт INFO=1 вместо 9 — тихое искажение
   важности у приёмника.
4. *Нули вместо отсутствия.* Битый или пустой `trace_id` даёт ОТСУТСТВИЕ поля.
   `"0" * 32` — не «пусто», а валидный по длине и невалидный по W3C
   идентификатор, который приёмник примет и склеит по нему несвязанные записи.
5. *Разряды, которых в данных нет.* `ts` -> нс считается `round(ts * 1e9)`
   (решение Р-4). `Decimal(str(ts))` даёт другое число и выглядит точнее, но
   источник этой точности не имел: шаг float64 на эпохе ~1.79e9 с равен
   2**-22 с ≈ 238 нс.
6. *Молчащий `None`.* Каждый отказ маппера обязан быть посчитан вызывающим:
   `None` без счётчика неотличим от «записей не было». Разбивку по родам
   отдаёт :func:`split_exportable` — предмет проверки, а не сам тест
   (решение Р-5).

**Два сторожа числовой плоскости, и они независимы намеренно.**
:func:`split_exportable` (Task 1.3) считает по `kind` — так считает ИСТОЧНИК.
:meth:`DisplayRecordMapper.to_otlp` отказывает по `kind` **или** по
`severity == "number"` — он последний рубеж, и расхождение двух полей (о нём
прямо говорит докстринг `kind_for_severity`: порог `ERROR_SEVERITY`
переопределяет род) не должно протечь наружу. Снять род из фильтра — красный в
тестах :func:`split_exportable`; снять проверку `severity` — красный у маппера.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from multiprocess_framework.modules.channel_routing_module.observability.observability_hub import (
    KIND_OBSERVATION,
    KIND_STATS,
)
from multiprocess_framework.modules.channel_routing_module.observability.record_display import (
    NUMBER_SEVERITY,
    OBSERVED_TS_KEY,
)
from multiprocess_framework.modules.logger_module.core.trace_id_guard import TRACE_ID_RE

from .interfaces import MappedRecord
from .resources import RESOURCE_CONTEXT_KEYS

__all__ = [
    "KIND_ATTRIBUTE",
    "NON_ATTRIBUTE_CONTEXT_KEYS",
    "NUMERIC_KINDS",
    "ORIGIN_KEY",
    "TRACE_ID_KEY",
    "DisplayRecordMapper",
    "split_exportable",
]


#: Роды числовой плоскости. Имена берутся у владельца словаря
#: (`observability_hub`), а не переписываются литералами: переименование рода во
#: фреймворке обязано ломать импорт здесь, а не тихо выключать фильтр.
NUMERIC_KINDS = frozenset({KIND_STATS, KIND_OBSERVATION})

#: Ключ следа кадра в `extra.context`. Именно `extra.context.trace_id`, а не
#: `extra.trace_id`: ошибка ред. 1 плана, на неё есть инъекция.
TRACE_ID_KEY = "trace_id"

#: Внутренний маркер маршрутизации того же класса, что `scope`: наружу не едет
#: ни атрибутом, ни полем Resource. Константа локальная, а не импорт
#: `store_tap.ORIGIN_FIELD`: тот описывает колонку стора, а замер 1.0 доказал,
#: что колонки `origin` у стора нет вовсе — владелец там не тот.
ORIGIN_KEY = "origin"

#: Атрибут, без которого `log` и `error` на выходе неразличимы: `SeverityText`
#: у них может совпасть, а род — нет.
KIND_ATTRIBUTE = "record.kind"

#: Что изымается из `extra.context` перед сборкой `Attributes`. Чёрный список,
#: а не белый: незнакомый ключ обязан доехать (см. пункт 2 докстринга модуля).
NON_ATTRIBUTE_CONTEXT_KEYS = RESOURCE_CONTEXT_KEYS | {TRACE_ID_KEY, ORIGIN_KEY}

#: Невалидный по W3C идентификатор: длина верная, значение — заполнение.
_ZERO_TRACE_ID = "0" * 32


class DisplayRecordMapper:
    """Display-запись -> :class:`MappedRecord`. Удовлетворяет `RecordMapper`.

    Имя не `RecordMapper`: так зовут Protocol в `interfaces.py`, и одноимённый
    конкретный класс в том же пакете сломал бы `isinstance()`, ради которого
    Protocol объявлен `@runtime_checkable` (решение Р-1 плана).

    Состояния нет: чистая функция в обёртке класса — форма продиктована
    Protocol'ом, а не потребностью что-то помнить.
    """

    def to_otlp(self, display_record: Mapping[str, Any]) -> MappedRecord | None:
        """Отобразить одну display-запись. `None` — запись не экспортируется.

        `resource` остаётся `None`: его ставит хост после
        :meth:`ResourceResolver.resolve` — маппер о пуле не знает и знать не
        должен, иначе чистая функция обзаводится состоянием.
        """
        kind = display_record.get("kind") or ""
        if kind in NUMERIC_KINDS or display_record.get("severity") == NUMBER_SEVERITY:
            # Отказ ДО касания `extra`: у числовых родов он плоский, и
            # `extra["context"]` там не существует.
            return None

        extra = display_record.get("extra")
        context: Mapping[str, Any] = extra.get("context") or {} if isinstance(extra, Mapping) else {}
        if not isinstance(context, Mapping):
            # Форма разъехалась: атрибуты не выдумываем, но и запись не теряем.
            context = {}

        attributes: dict[str, Any] = {KIND_ATTRIBUTE: kind}
        for key, value in context.items():
            if key not in NON_ATTRIBUTE_CONTEXT_KEYS:
                attributes[key] = value

        return MappedRecord(
            timestamp_ns=_to_nanoseconds(display_record.get("ts")),
            observed_timestamp_ns=_to_nanoseconds(display_record.get(OBSERVED_TS_KEY)),
            severity_text=_as_text(display_record.get("severity")),
            severity_number=_as_severity_number(display_record.get("severity_number")),
            body=_as_text(display_record.get("message")),
            scope_name=_as_text(display_record.get("module")),
            attributes=attributes,
            trace_id=_normalize_trace_id(context.get(TRACE_ID_KEY)),
        )


def split_exportable(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], Counter[str]]:
    """Отделить экспортируемые записи от числовой плоскости (Task 1.3).

    Считает по `kind`, а не по `severity`: род называет ИСТОЧНИК записи, а
    `severity` выводится (`severity_number_for`) и с родом расходится — на
    снимке оба поля дают один ответ, но совпадение здесь не гарантия.

    Числа приходят при ЛЮБОМ уровне подписки — батч-форвардер уровнем не
    фильтрует (`push_batch`), поэтому отсечь их можно только здесь, а не
    настройкой подписки.

    Returns:
        `(to_send, skipped_by_kind)`. Тождество `len(to_send) +
        sum(skipped_by_kind.values()) == len(records)` держится по построению:
        каждая запись попадает ровно в одну половину. Пустой `Counter` — это
        «числовых не было», и он отличим от «функцию не звали» только по
        `len(to_send)`; поэтому обе половины возвращаются вместе, а не по
        отдельности.
    """
    to_send: list[Mapping[str, Any]] = []
    skipped_by_kind: Counter[str] = Counter()
    for record in records:
        kind = record.get("kind") or ""
        if kind in NUMERIC_KINDS:
            skipped_by_kind[kind] += 1
        else:
            to_send.append(record)
    return to_send, skipped_by_kind


# --------------------------------------------------------------------- #
# Приведение отдельных полей
# --------------------------------------------------------------------- #


def _to_nanoseconds(value: Any) -> int | None:
    """Секунды unix-эпохи (float) -> наносекунды. Не-число -> `None`.

    `bool` отсекается отдельно: он подкласс `int`, и `True` дал бы метку
    времени 1 нс. `inf`/`nan` отсекаются тоже — `round(float("nan"))` не
    возвращает мусор, а поднимает `ValueError` прямо в потоке приёма.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return round(value * 1e9)


def _as_text(value: Any) -> str:
    """Текстовое поле модели OTel. Отсутствие -> пустая строка, не `"None"`."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _as_severity_number(value: Any) -> int:
    """`SeverityNumber` — КОПИЯ числа записи, без пересчёта по рангу.

    Не-число -> `0` (`UNSPECIFIED` шкалы фреймворка): то же значение, которым
    `severity_number_for` помечает «оси важности у этой записи нет». Выдумывать
    здесь `INFO` значило бы поднять неизвестность до уровня.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _normalize_trace_id(value: Any) -> str | None:
    """32 hex W3C -> строка в нижнем регистре. Всё остальное -> `None`.

    Форма проверяется регуляркой ВЛАДЕЛЬЦА (`trace_id_guard.TRACE_ID_RE`),
    а не своей копией — иначе страж «сырой trace_id в тексте» и экспортёр
    разойдутся в том, что считать идентификатором.

    Нулевой идентификатор отвергается: по W3C он невалиден, а по длине
    проходит — приёмник склеил бы по нему несвязанные записи.
    """
    if not isinstance(value, str) or not TRACE_ID_RE.fullmatch(value):
        return None
    normalized = value.lower()
    if normalized == _ZERO_TRACE_ID:
        return None
    return normalized
