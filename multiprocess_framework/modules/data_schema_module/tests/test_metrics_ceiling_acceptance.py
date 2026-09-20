# -*- coding: utf-8 -*-
"""
Независимая приёмка Task 5.4 (Ф5, план ``plans/observation-port/plan.md``) — S-27.

Пишет ЭТОТ файл тестер БЕЗ доступа к реализации, от критериев, выданных в постановке
задачи (не от текста Acceptance criteria в самом плане — та строка ýже: «в репозитории
не осталось места, где record_metric значит перезаписать»; хозяин расширил решение до
«заморозить с голосом и потолком», зафиксировав числа воспроизведения 2026-08-26:
14 боевых вызывающих, 22 счётчика уже на импорте, ``_timings`` растёт на 35 байт/вызов
без потолка, читателей ``get_metrics()`` — ноль).

Критерии (К1-К5) и их якоря:
    К1 — рост ``_timings`` ограничен ЛИТЕРАЛОМ (не «меньше, чем было»).
    К2 — потеря при упоре в потолок НАЗВАНА (поле/счётчик/голос), не молчалива.
    К3 — голос «меня никто не читает» звучит РОВНО один раз, не на каждый вызов.
    К4 — ``record_metric`` не значит «перезаписать»: 3×record_metric(name, 1) == 3.
    К5 — 14 боевых вызывающих (``model_factory.py``, ``schema_registry.py``) не падают.

ЛОВУШКА, которую этот файл обходит: глобальный ``_metrics_collector`` — один на
процесс и наполнен ещё на импорте (те самые 22 счётчика). К1-К4 поэтому НЕ трогают
глобальный singleton — каждый тест строит свежий ``MetricsCollector()`` напрямую
(публичный конструктор, ноль аргументов, ничего не меняет в старом коде). Только
К5 сознательно идёт через боевые точки входа (в т.ч. process-wide ``SchemaManager``
singleton), потому что именно ЭТО поведение он обязан проверить, — и подчищает за
собой ``registry.clear()``, как уже делает ``test_factory.py`` в этом же каталоге.

ЛИТЕРАЛЫ ЭТОГО ФАЙЛА — решение тестера, а не найденная в коде/плане константа.
Ни в ``plans/observation-port/plan.md``, ни в ``DECISIONS.md`` (ни модульном, ни
framework-уровня) конкретное число потолка не зафиксировано — раздел «где моя
модель может быть неверна» в отчёте называет это прямо. Эти тесты и есть предложенное
ТЗ для разработчика; расхождение в выборе числа — законный повод для правки числа
здесь, а не для отказа от потолка.
"""

import logging
import re

import pytest
from pydantic import BaseModel

from ..core.metrics import MetricsCollector
from ..core.exceptions import SchemaValidationError
from ..registry.schema_registry import SchemaManager, SchemaRegistry
from ..factory.model_factory import ModelFactory
from ..models.base import BaseManagerModel


# ============================================================================
# К1 — потолок _timings, литерал
# ============================================================================

# Потолок выбран тестером (нигде в репозитории не зафиксирован — см. докстринг
# модуля). 1000 записей * ~35 байт/вызов (число воспроизведения хозяина) ~= 35 КБ
# на ключ — разумная граница для «не должно расти неограниченно».
TIMINGS_CEILING = 1000
CALLS_BEYOND_CEILING = 2500
# Литерал считается из ДВУХ литералов тестера, не из кода под тестом.
EXPECTED_DROPPED = CALLS_BEYOND_CEILING - TIMINGS_CEILING  # 1500


def test_k1_timings_length_is_capped_at_a_literal_ceiling():
    """К1: после заведомо большего числа вызовов, чем потолок, размер не растёт дальше потолка."""
    collector = MetricsCollector()
    name = "k1.growth.metric"

    # Якорь существования (ниже потолка): обычный счёт идёт как обычно — ЛИТЕРАЛ 5, не «> 0».
    for _ in range(5):
        collector.record_timing(name, 0.001)
    below_cap = collector.get_metrics()["timings"][name]["count"]
    assert below_cap == 5, (
        f"ниже потолка запись обязана идти как обычно (без потолка это тоже верно) — "
        f"после 5 вызовов ожидали count == 5, получено {below_cap!r}"
    )

    # Основное утверждение: после потолка рост останавливается РОВНО на потолке.
    for _ in range(CALLS_BEYOND_CEILING - 5):
        collector.record_timing(name, 0.001)
    at_cap = collector.get_metrics()["timings"][name]["count"]
    assert at_cap == TIMINGS_CEILING, (
        f"после {CALLS_BEYOND_CEILING} вызовов ({CALLS_BEYOND_CEILING} >> потолка) размер "
        f"хранилища обязан застыть на литерале {TIMINGS_CEILING}, получено {at_cap!r} — рост "
        f"оказался неограниченным (или потолок реализован другим числом — поправьте "
        f"TIMINGS_CEILING в этом файле под фактическое проектное решение)"
    )


# ============================================================================
# К2 — потеря при упоре в потолок ДОЛЖНА БЫТЬ НАЗВАНА (поле / счётчик / голос)
# ============================================================================

_LOSS_VOICE_RE = re.compile(r"вытесн|потер|dropped|evict|overflow|перепол", re.IGNORECASE)


def _loss_signal_count(collector: MetricsCollector, name: str, caplog=None):
    """Достать литерал числа потерянных записей, если сборщик его уже называет.

    Критерий К2 в постановке прямо перечисляет ТРИ равноправные формы («счётчик/поле/
    голос») — поэтому проверяем все три правдоподобные точки, а не одну угаданную.
    Возвращает None, если ни одна форма не нашлась (это и есть «молчаливая потеря»).
    """
    agg = collector.get_metrics()["timings"].get(name, {})
    if isinstance(agg, dict) and "dropped" in agg:
        return agg["dropped"]

    counters = collector.get_metrics()["counters"]
    for candidate in (f"{name}.timings_dropped", f"{name}_dropped", f"{name}.dropped"):
        if candidate in counters:
            return counters[candidate]

    if caplog is not None:
        hits = [r for r in caplog.records if _LOSS_VOICE_RE.search(r.getMessage())]
        numbers = []
        for r in hits:
            numbers.extend(int(n) for n in re.findall(r"\d+", r.getMessage()))
        if numbers:
            return numbers[-1]

    return None


def test_k2_overflow_loss_is_named_with_a_literal_not_silent(caplog):
    """К2: потеря отброшенных записей видна числом, а не тонет молча."""
    caplog.set_level(logging.WARNING)
    collector = MetricsCollector()
    name = "k2.overflow.metric"

    # Якорь существования (Y — ниже потолка): сигнала потери либо нет, либо он явный 0.
    for _ in range(5):
        collector.record_timing(name, 0.001)
    below_cap_loss = _loss_signal_count(collector, name, caplog)
    assert below_cap_loss in (0, None), (
        f"ниже потолка потери не было — сигнал потери обязан быть 0 или отсутствовать, получено {below_cap_loss!r}"
    )

    # X — выше потолка: потеря обязана получить ЧИСЛО.
    caplog.clear()
    for _ in range(CALLS_BEYOND_CEILING - 5):
        collector.record_timing(name, 0.001)
    after_overflow_loss = _loss_signal_count(collector, name, caplog)
    assert after_overflow_loss == EXPECTED_DROPPED, (
        f"после {CALLS_BEYOND_CEILING} вызовов (потолок {TIMINGS_CEILING}) потеря обязана быть "
        f"названа литералом {EXPECTED_DROPPED}, получено {after_overflow_loss!r}. Искали поле "
        f"'dropped' в get_metrics()['timings'][name], счётчики '*_dropped'/'*.dropped' и голос "
        f"в WARNING-логах, матчащий /{_LOSS_VOICE_RE.pattern}/i с числом внутри сообщения."
    )


# ============================================================================
# К3 — голос «меня никто не читает» звучит РОВНО один раз, не на каждый вызов
# ============================================================================

_NO_READER_VOICE_RE = re.compile(r"читател|читает|no reader|not read|никто.*чита", re.IGNORECASE)


def test_k3_no_reader_voice_sounds_exactly_once_not_per_call(caplog):
    """К3: голос «меня никто не читает» — одноразовый, не на каждый вызов (кванторное: 2 вызова).

    **Уровень изменён на DEBUG решением владельца по ревью Ф5 (S7), 2026-08-26.**
    Тест написан независимым тестером ДО реализации и требовал WARNING — это
    была разумная догадка о контракте, но ревью измерило её цену: голос звучит
    на импорте пакета, то есть восемь WARNING на каждый подъём системы,
    бессрочно, при том что сообщение описывает статический факт кода, а не
    происшествие. Свойство, которое сторожит тест, не изменилось ни на букву:
    голос обязан прозвучать РОВНО один раз на два вызова. Изменился только
    уровень, на котором его ловят.
    """
    caplog.set_level(logging.DEBUG)
    collector = MetricsCollector()

    collector.record_metric("k3.voice.metric.a", 1)
    collector.record_metric("k3.voice.metric.b", 1)

    voice_hits = [r for r in caplog.records if _NO_READER_VOICE_RE.search(r.getMessage())]
    assert len(voice_hits) == 1, (
        f"голос «никто не читает эти метрики» обязан прозвучать РОВНО один раз (на первую "
        f"запись в жизни сборщика), а не на каждый вызов и не ни разу; после 2 вызовов на "
        f"свежем MetricsCollector() найдено {len(voice_hits)} совпадений с "
        f"/{_NO_READER_VOICE_RE.pattern}/i среди DEBUG+-записей: "
        f"{[r.getMessage() for r in voice_hits]!r} (все DEBUG+: "
        f"{[r.getMessage() for r in caplog.records]!r})"
    )


# ============================================================================
# К4 — record_metric не значит «перезаписать»: одно имя = counter-семантика
# ============================================================================


def test_k4_record_metric_is_additive_not_last_write_wins():
    """К4: три record_metric(name, 1) дают 3 (прибавление), а не 1 (перезапись)."""
    collector = MetricsCollector()
    name = "k4.additive.metric"

    collector.record_metric(name, 1)
    collector.record_metric(name, 1)
    collector.record_metric(name, 1)

    stored = collector.get_metric(name)
    assert stored is not None, "после трёх record_metric запись обязана существовать"
    assert stored["value"] == 3, (
        f"record_metric в этом проекте — имя со значением 'counter, прибавить' "
        f"(как уже ведёт себя increment); три вызова record_metric(name, 1) обязаны "
        f"дать value == 3, получено {stored['value']!r} (перезапись — третье, закрываемое "
        f"значение того же имени, см. постановку Task 5.4)"
    )


# ============================================================================
# К5 — 14 боевых вызывающих продолжают работать после заморозки
# ============================================================================


class _K5RegistrySchema(BaseModel):
    """Минимальная схема для сквозного вызова SchemaRegistry.create_instance (реальная дорога)."""

    value: int = 0


class _K5ManagerSchema(BaseManagerModel):
    """Минимальная схема менеджера для сквозного вызова ModelFactory.create_manager (реальная дорога)."""

    test_field: str = "default_value"


def test_k5_schema_registry_call_sites_survive_the_freeze():
    """К5: registry.py:96,151-152,156,161 — успешная и ошибочная ветки, много вызовов, без падений."""
    registry = SchemaRegistry()  # изолированный экземпляр — НЕ process-wide default, ничего не пачкает
    assert registry.register("K5RegistrySchema", _K5RegistrySchema) is True  # строка 96

    # Успешная ветка (151-152) — заведомо больше потолка К1, чтобы дорога тоже пережила заморозку.
    for i in range(CALLS_BEYOND_CEILING):
        instance = registry.create_instance("K5RegistrySchema", {"value": i})
        assert instance.value == i

    # Ошибочная ветка (156, 161) — хотя бы раз, дорога отличается от успешной.
    with pytest.raises(SchemaValidationError):
        registry.create_instance("K5RegistrySchema", {"value": "not-an-int-###"})


def test_k5_model_factory_call_sites_survive_the_freeze():
    """К5: model_factory.py:80-87,222-229 — успешная и ошибочная ветки через process-wide singleton.

    Недостижимо здесь: строка 160 (``managers_registered``, ветка ``auto_register=True``) требует
    поднятого ``StorageManager``/``shared_resources`` — вне периметра юнит-теста метрик, и
    ``test_factory.py`` в этом же каталоге по той же причине зовёт ``auto_register=False``.
    """
    registry = SchemaManager.get_instance()
    registry.clear()  # тот же приём, что и test_factory.py::reset_registry — детерминированный старт
    registry.register("K5ManagerSchema", _K5ManagerSchema)
    try:
        # Успешная ветка (80-81) — заведомо больше потолка К1, чтобы дорога тоже пережила заморозку.
        for i in range(60):
            model = ModelFactory.create_manager("K5ManagerSchema", f"k5_instance_{i}", auto_register=False)
            assert model.component_class == "K5ManagerSchema"

        # Ошибочная ветка (86-87) — схема не зарегистрирована.
        with pytest.raises(Exception):
            ModelFactory.create_manager("K5UnknownSchema", "k5_missing", auto_register=False)
    finally:
        registry.clear()  # не оставляем мусор в process-wide singleton для соседних тестов
