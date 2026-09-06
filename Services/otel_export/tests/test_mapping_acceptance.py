# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.1 + Task 1.3 плана otel-export — НЕЗАВИСИМЫЙ тестер, ДО кода.

Источник критериев: акты приёмки, переданные тестеру буквально (Task 1.1 "record_to_otlp",
Task 1.3 "числа не экспортируются"). Реализации `Services/otel_export/mapping.py` на диске
НЕТ — проверено (см. `find Services/otel_export -type f`, ни `mapping.py`, ни `resources.py`
не перечислены). Импорт предмета — ВНУТРИ каждого теста, чтобы `pytest --collect-only`
собирал полный список тестов и без пакета.

**Открытая посылка, названная громко (не спрятана).** `interfaces.py:4-6` говорит:
«маппер (Ф1.1) ... приходит позже и пишется под уже названные здесь имена» — то есть под
имя Protocol'а `RecordMapper`. Тестер вывел из этого имя конкретного класса —
и ошибся: Protocol с этим именем уже занят, конкретный класс зовётся ``DisplayRecordMapper``
(решение автора 2026-09-06, довод в плане). Метод —
``to_otlp(self, display_record)`` — тем же именем метода, что в Protocol'е. Это ЕДИНСТВЕННЫЙ
угаданный крючок для этого файла (по правилу «один угаданный крючок на файл»); если имя
класса или сигнатура конструктора other — тесты упадут `ImportError`/`TypeError`, а не по
существу критерия, и это названо в отчёте тестера отдельным пунктом.

Вход — настоящие записи снимка (`tools/otel_stand/samples/1f40ce0d/tail_debug.json`) через
`_snapshot_fixtures.load_snapshot_records`. Форма ``error`` и одиночная ``stats``
(``aggregate=false``) в снимке НЕ встречаются (карточка Task 1.0, §6) — там, где критерий
требует именно их, запись строится ВЫВОДОМ ИЗ КОДА нормализатора
(`record_display.py:log_record_to_display` / `hub_record_to_display`, ветка `elif kind in
(KIND_STATS, KIND_OBSERVATION)`), и это помечено в докстринге теста явно словом "ВЫВЕДЕНО".
"""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

import pytest

from Services.otel_export.tests._snapshot_fixtures import load_snapshot_records

LOG_RECORDS = load_snapshot_records("log")
STATS_RECORDS = load_snapshot_records("stats")
OBSERVATION_RECORDS = load_snapshot_records("observation")

# Число процессов страницы (§6 карточки Task 1.0): один источник, camera_0. Ни один
# реальный log-record снимка не содержит другого proc_name — сверено ниже фикстурой.


def _mapper():
    """Единственный угаданный крючок файла — см. докстринг модуля."""
    from Services.otel_export.mapping import DisplayRecordMapper

    return DisplayRecordMapper()


@pytest.fixture(scope="module")
def one_log_record() -> dict[str, Any]:
    assert LOG_RECORDS, "в снимке не нашлось ни одной записи kind=log — сверка входа сломана"
    return LOG_RECORDS[0]


class TestFieldMapping:
    """Task 1.1: по одному тесту на строку отображения, значения литералами, вход из снимка."""

    def test_context_shape_assumption_holds_on_all_18_log_records(self) -> None:
        """Сторож входа: 18/18 log-записей несут РОВНО шесть ключей context (карточка §3).

        Не приёмочный критерий сам по себе — страховка, что остальные тесты класса не
        молча проверяют случайную запись с другой формой ``extra.context``.
        """
        expected_keys = {"proc_name", "pid", "fw_version", "incarnation", "recipe", "origin"}
        keysets = {frozenset(r["extra"]["context"].keys()) for r in LOG_RECORDS}
        assert keysets == {frozenset(expected_keys)}, f"состав extra.context разошёлся: {keysets}"

    def test_ts_maps_to_timestamp_ns(self, one_log_record: dict[str, Any]) -> None:
        """``ts`` (unix-секунды, float) -> ``Timestamp`` в наносекундах.

        Литерал получен формулой ``round(ts * 1e9)`` на РЕАЛЬНОМ значении записи снимка.
        Открытая посылка (названа в отчёте): контракт не фиксирует конвенцию округления;
        ``int(ts * 1e9)`` на этом конкретном числе даёт тот же результат (проверено), но
        реализация через ``Decimal(str(ts))`` разошлась бы на ~108 нс — ниже точности
        float64 на числах такого порядка, но формально другое число.
        """
        mapper = _mapper()
        ts = one_log_record["ts"]
        assert ts == 1788631974.7541459, "запись снимка изменилась — литерал теста устарел"

        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.timestamp_ns == 1788631974754145792

    def test_severity_copied_not_recomputed(self, one_log_record: dict[str, Any]) -> None:
        """``severity``/``severity_number`` — КОПИЯ, шкала уже OTel (5/9/13/17/21).

        Литерал 9 отличает копию от пересчёта по рангу 0..4 (там INFO дал бы 1) —
        сам факт совпадения с 9 уже отвергает дефект «пересчитано по рангу».
        """
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.severity_text == "info"
        assert mapped.severity_number == 9

    def test_message_maps_to_body(self, one_log_record: dict[str, Any]) -> None:
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.body == one_log_record["message"]
        assert mapped.body.startswith("metrics snapshot (ts=1788631975, count=8):")

    def test_module_maps_to_scope_name(self, one_log_record: dict[str, Any]) -> None:
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.scope_name == "multiprocess_framework.modules.statistics_module"

    def test_observed_ts_maps_to_observed_timestamp_ns(self, one_log_record: dict[str, Any]) -> None:
        """``observed_ts`` -> ``ObservedTimestamp``.

        Ни одна запись снимка не несёт ``observed_ts`` (карточка §4: «0/144 — в сырье его
        нет, ставит его приёмник»). Запись строится на РЕАЛЬНОЙ базе + добавленное поле —
        не выведено с нуля, но и не снято как есть; пометка честная, а не подмена.
        """
        record = copy.deepcopy(one_log_record)
        record["observed_ts"] = 1788631980.123456

        mapper = _mapper()
        mapped = mapper.to_otlp(record)
        assert mapped is not None
        assert mapped.observed_timestamp_ns == 1788631980123456000

    def test_observed_ts_absent_when_not_stamped(self, one_log_record: dict[str, Any]) -> None:
        """Парная: запись БЕЗ ``observed_ts`` (как в снимке) не получает выдуманного значения."""
        assert "observed_ts" not in one_log_record
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.observed_timestamp_ns is None


class TestTraceId:
    """`extra.context.trace_id` -> `TraceId`. 0 вхождений в снимке (карточка §4) — ВЫВЕДЕНО."""

    def test_trace_id_maps_when_present_and_well_formed(self, one_log_record: dict[str, Any]) -> None:
        """ВЫВЕДЕНО: снимок не содержит ни одного `trace_id` — база настоящая, поле добавлено."""
        record = copy.deepcopy(one_log_record)
        record["extra"]["context"]["trace_id"] = "0af7651916cd43dd8448eb211c80319c"

        mapper = _mapper()
        mapped = mapper.to_otlp(record)
        assert mapped is not None
        assert mapped.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_trace_id_absent_field_when_missing_from_context(self, one_log_record: dict[str, Any]) -> None:
        """Настоящая запись снимка: ``trace_id`` в ``context`` нет вовсе -> поля нет, не нули."""
        assert "trace_id" not in one_log_record["extra"]["context"]
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.trace_id is None

    @pytest.mark.parametrize(
        "bad_trace_id",
        [
            "",  # пусто
            "0af765",  # короче 32 hex
            "0af7651916cd43dd8448eb211c80319cXX",  # длиннее 32 hex
            "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",  # 32 символа, не hex
        ],
        ids=["empty", "too-short", "too-long", "not-hex"],
    )
    def test_trace_id_none_on_malformed_never_zero_filled(
        self, one_log_record: dict[str, Any], bad_trace_id: str
    ) -> None:
        """Битый ``trace_id`` -> поля нет. НЕ ``"00000000000000000000000000000000"``."""
        record = copy.deepcopy(one_log_record)
        record["extra"]["context"]["trace_id"] = bad_trace_id

        mapper = _mapper()
        mapped = mapper.to_otlp(record)
        assert mapped is not None
        assert mapped.trace_id is None
        assert mapped.trace_id != "0" * 32, "нулевой trace_id — тоже заполнение, а не отсутствие"


class TestAttributesResidue:
    """`Attributes` записи `kind=log` реального снимка — литералом, и парная проверка утечки."""

    def test_real_log_record_attributes_are_exactly_record_kind(self, one_log_record: dict[str, Any]) -> None:
        """18/18 log-записей: после изъятия пятёрки Resource + origin + trace_id остаток
        ``extra.context`` пуст — `Attributes` содержит РОВНО ``{"record.kind": "log"}``.

        Критерий прямо предупреждает: реализация `attributes = {}` (без ``record.kind``)
        тоже прошла бы этот тест наравне с правильной — пара ниже
        (`test_unmodeled_context_key_survives_into_attributes`) обязательна.
        """
        mapper = _mapper()
        mapped = mapper.to_otlp(one_log_record)
        assert mapped is not None
        assert mapped.attributes == {"record.kind": "log"}

    def test_unmodeled_context_key_survives_into_attributes(self, one_log_record: dict[str, Any]) -> None:
        """ОБЯЗАТЕЛЬНАЯ пара: лишний ключ в ``extra.context`` обязан ДОЕХАТЬ до ``Attributes``.

        Без этого теста «`attributes = {}` всегда» (см. докстрин выше) неотличима от
        правильного изъятия шести конкретных ключей.
        """
        record = copy.deepcopy(one_log_record)
        record["extra"]["context"]["request_id"] = "req-42"

        mapper = _mapper()
        mapped = mapper.to_otlp(record)
        assert mapped is not None
        assert mapped.attributes == {"record.kind": "log", "request_id": "req-42"}

    def test_kind_attribute_distinguishes_log_from_error(self, one_log_record: dict[str, Any]) -> None:
        """ВЫВЕДЕНО: снимок не содержит ни одной записи ``kind=error`` (карточка §6).

        `record_display.py` подтверждает: лог и ошибка — ОДИН нормализатор
        (`log_record_to_display`), различаются только значениями `severity`/
        `severity_number`/`kind` (докстринг §5 карточки: «error и log — одна форма»).
        Запись строится копией реальной log-записи с гонкой этих трёх полей на
        error/critical — форма (ключи `context`) остаётся настоящей.
        """
        error_record = copy.deepcopy(one_log_record)
        error_record["kind"] = "error"
        error_record["severity"] = "critical"
        error_record["severity_number"] = 21

        mapper = _mapper()
        mapped_error = mapper.to_otlp(error_record)
        mapped_log = mapper.to_otlp(one_log_record)

        assert mapped_error is not None
        assert mapped_log is not None
        assert mapped_error.attributes == {"record.kind": "error"}
        assert mapped_log.attributes == {"record.kind": "log"}
        assert mapped_error.attributes != mapped_log.attributes


class TestNumericPlaneRefusal:
    """Task 1.1 (отказ) + Task 1.3 (видно числом): `severity=="number"` / `kind` числовой."""

    def test_refuses_on_severity_number_for_real_stats_record(self) -> None:
        assert STATS_RECORDS, "в снимке нет ни одной stats-записи"
        record = STATS_RECORDS[0]
        assert record["severity"] == "number"

        mapper = _mapper()
        assert mapper.to_otlp(record) is None

    def test_refuses_on_severity_number_for_real_observation_record(self) -> None:
        assert OBSERVATION_RECORDS, "в снимке нет ни одной observation-записи"
        record = OBSERVATION_RECORDS[0]
        assert record["severity"] == "number"

        mapper = _mapper()
        assert mapper.to_otlp(record) is None

    def test_snapshot_batch_only_log_and_error_survive_skip_broken_down_by_kind(
        self, one_log_record: dict[str, Any]
    ) -> None:
        """Task 1.3, буквально: батч (log + error + stats-агрегат + stats-одиночная +
        observation) -> ушли ровно log и error; пропуск = 3, разбивка {stats: 2, observation: 1}.

        `error` в батче — ВЫВЕДЕНО (см. `test_kind_attribute_distinguishes_log_from_error`).
        Одиночная `stats` (``aggregate=false``) тоже ВЫВЕДЕНА — в снимке все 18/18 записей
        `stats` страницы несут ``aggregate=true`` (сверено фикстурой ниже), форма построена
        по ветке `record_display.hub_record_to_display` (``elif kind in (KIND_STATS,
        KIND_OBSERVATION)``, ``else`` для НЕ-stats: ``extra = {"value", "tags", "metric_type"}``).

        Разбивку по `kind` считает ТЕСТ (группируя батч по `record["kind"]` для None-результатов),
        а не выделенная функция подсчёта — интерфейс `RecordMapper.to_otlp` не декларирует
        отдельного счётчика (см. `interfaces.py`: «каждый None обязан быть посчитан
        ВЫЗЫВАЮЩИМ» — учёт вне контракта маппера самого по себе). Открытый пункт отчёта:
        если Task 1.3 ожидает отдельную публичную функцию учёта в `mapping.py`, этот тест её
        не находит и не проверяет её название.
        """
        assert all(r["extra"].get("aggregate") for r in STATS_RECORDS), (
            "предпосылка сломана: в снимке появилась stats-запись с aggregate=false — "
            "нужно использовать РЕАЛЬНУЮ, а не выведенную"
        )

        error_record = copy.deepcopy(one_log_record)
        error_record["kind"] = "error"
        error_record["severity"] = "error"
        error_record["severity_number"] = 17

        stats_aggregate = STATS_RECORDS[0]

        # ВЫВЕДЕНО: одиночная stats-метрика, форма по ветке hub_record_to_display
        # (elif kind in (KIND_STATS, KIND_OBSERVATION), branch != KIND_OBSERVATION).
        stats_single = {
            "kind": "stats",
            "process": "camera_0",
            "module": "camera_0",
            "ts": 1788631972.1140497,
            "severity": "number",
            "severity_number": 0,
            "metric": "capture.capture_fps",
            "message": "capture.capture_fps",
            "extra": {"value": 21.3, "tags": {"plugin": "capture", "camera": "0"}, "metric_type": "gauge"},
        }

        observation = OBSERVATION_RECORDS[0]

        batch = [one_log_record, error_record, stats_aggregate, stats_single, observation]

        mapper = _mapper()
        results = [(record["kind"], mapper.to_otlp(record)) for record in batch]

        survived_kinds = [kind for kind, mapped in results if mapped is not None]
        assert survived_kinds == ["log", "error"]

        skipped_by_kind = Counter(kind for kind, mapped in results if mapped is None)
        assert skipped_by_kind == Counter({"stats": 2, "observation": 1})
        assert sum(skipped_by_kind.values()) == 3
