# -*- coding: utf-8 -*-
"""Контракт «``NumberKind`` ↔ ``MetricType``» — словарь родов числа один на два модуля.

**Почему тест вообще нужен.** ``NumberRecord.kind`` объявлен литералами
(``Literal["counter", "gauge", "timing", "histogram"]``), а живое перечисление
родов метрики — ``MetricType`` в ``statistics_module``. Литералы продублированы
намеренно: ``Literal[...]`` требует констант времени определения класса, а импорт
``MetricType`` в модуль-схему втянул бы туда весь ``metric_record`` — и вернул бы
зависимость базы от слоя выше, ради снятия которой форма и переехала в
``channel_routing_module/observability`` (вердикт CTO, 2026-09-05).

Дубль без сверки расходится молча: добавь кто-нибудь пятый род в ``MetricType``,
и ``from_hub_record`` начнёт возвращать ``None`` на законной записи — то есть
метрика тихо перестанет попадать в колонку ``metric`` и в ряд по имени. Ровно это
обещал докстринг ``NumberKind`` («расхождение ловит контракт-тест, а не глаз») —
до этого файла обещание было пустым: тест, на который он ссылается, не
существовал (проверено ``grep -rn "NumberKind"`` — единственные совпадения были в
самом ``number_record.py``).

**Где живёт.** В тестах ``statistics_module``, а не ``channel_routing_module``:
сверка требует ``MetricType``, и импортировать его из тестов базы значило бы
завести обратную зависимость слоя даже в тестах.
"""

from __future__ import annotations

from typing import get_args

from multiprocess_framework.modules.channel_routing_module.observability.number_record import NumberKind
from multiprocess_framework.modules.statistics_module.core.metric_record import MetricType


def test_number_kind_literals_match_metric_type_members_exactly() -> None:
    """Множества равны — не «включено», а ДОСЛОВНО совпадают.

    Проверяется равенство, а не вложенность, потому что расхождение опасно в обе
    стороны: лишний род в ``NumberKind`` пустил бы в форму значение, которого
    агрегация не знает, а недостающий — молча отверг бы законную запись.

    Сломается: при добавлении/переименовании/удалении рода в любом из двух мест
    без правки второго.
    """
    literal_kinds = set(get_args(NumberKind))
    metric_kinds = {member.value for member in MetricType}
    assert literal_kinds == metric_kinds, (
        "словарь родов числа разошёлся: в NumberKind "
        f"{sorted(literal_kinds)}, в MetricType {sorted(metric_kinds)}; "
        f"только в NumberKind — {sorted(literal_kinds - metric_kinds)}, "
        f"только в MetricType — {sorted(metric_kinds - literal_kinds)}"
    )


def test_every_metric_type_value_is_actually_accepted_by_the_form() -> None:
    """Совпадение имён — половина контракта; вторая половина — что форма их ПРИНИМАЕТ.

    Равенство множеств выше сверяет две строки текста и осталось бы зелёным,
    если бы ``_build`` проверял членство по СВОЕМУ, третьему списку (он и правда
    написан там кортежем литералов). Здесь каждое живое значение
    ``MetricType`` прогоняется через ``from_hub_record`` — сверяется поведение,
    а не объявление.
    """
    from multiprocess_framework.modules.channel_routing_module.observability.number_record import NumberRecord

    for member in MetricType:
        record = {
            "kind": "stats",
            "module": "seg",
            "ts": 1.0,
            "metric": "probe",
            "value": 1,
            "metric_type": member.value,
        }
        num = NumberRecord.from_hub_record(record)
        assert num is not None, f"род {member.value!r} объявлен в MetricType, но форма его не приняла"
        assert num.kind == member.value
