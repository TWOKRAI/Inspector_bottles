# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.1 плана ``observability-closure`` — К3 (``NumberRecord``).

**RED-набор, написан ДО реализации.** Тестер работал в отдельном git worktree
(``.claude/worktrees/f3-t31``) на коммите ``610698c0`` — ДО правки Task 3.1,
не видел diff/реализацию, не читал ``_impl/`` (в этом дереве такой директории
нет вовсе). Источник критериев — раздел «### Task 3.1» в
``plans/observability-closure/phase-3-store-and-signal.md`` (контракт К1–К8 +
«пять исправлений спеки»), а НЕ сегодняшнее поведение кода.

======================================================================
Что здесь проверяется
======================================================================

К3 (дословно): «``statistics_module/core/number_record.py``, ``SchemaBase``:
``name, kind(counter|gauge|timing|histogram), value | aggregate, tags, unit,
ts, writer``. Три диалекта (агрегат ``MetricRecord.aggregate()``, hub-запись
``metric/value/metric_type``, запись порта ``writer/metric/value``) сходятся
к ней, и адаптеры удаляются, а не оборачиваются.»

Путь модуля, имя класса и имена ВСЕХ полей — литералы из контракта, ничего не
угадано. Единственная не-литеральная деталь — имя метода ``to_dict()``: план
явно его не называет, но того же требует правило проекта №1 («Dict at
Boundary») и тот же приём уже применён РЯДОМ, в этом же модуле, у
``ObservationRecord.to_dict()`` (``statistics_module/observation/
observation_manager.py``, задача 3.2, готовый прецедент той же формы записи
для того же хаба). Это ОДИН допущенный (не подтверждённый планом) символ —
назван здесь и в отчёте тестера.

======================================================================
Что здесь НЕ проверяется (сознательно, не забыто)
======================================================================

* «Три диалекта сходятся к ней» в части СТАРЫХ вызывающих (``StatsManager``,
  ``ObservationManager``, ``HubStatsChannel``) — это интеграционное
  утверждение про ДРУГИЕ файлы (что они начнут строить ``NumberRecord``
  вместо сырых dict'ов и что адаптеры физически удалятся). На уровне ОДНОГО
  нового файла-схемы это не проверяемо без чтения будущей реализации —
  оставлено на инъекцию лида/ревью.
* Дефолтные значения полей при их ОПУСКАНИИ (``writer=""``? ``tags={}``?) —
  план не называет дефолты явно, поэтому конструирую тесты, ВСЕГДА передавая
  все семь полей, а не угадываю, что происходит при их отсутствии.

Импорт модуля — ЛОКАЛЬНЫЙ, внутри каждого теста (а не единым импортом на
верху файла): ``number_record.py`` в дереве не существует вовсе (проверено
``grep -rn "NumberRecord"`` по всему репозиторию — единственное совпадение —
упоминание в докстринге СОСЕДНЕГО теста Task 2.1, не код). Импорт на верху
файла дал бы ОДНУ ошибку сборки на весь файл (``ERROR``, не ``FAILED``) и
скрыл бы, какой тест что именно проверяет; локальный импорт даёт каждому
тесту свой честный ``ModuleNotFoundError`` — тот же класс ошибки, что
``AttributeError``/``NotImplementedError`` для символа, которого ещё нет.
"""

from __future__ import annotations

import pickle

import pytest


def _import_number_record():
    """Единая точка локального импорта — чтобы имя модуля не дублировалось семь раз."""
    from multiprocess_framework.modules.statistics_module.core.number_record import NumberRecord

    return NumberRecord


class TestConstructionAndFieldNames:
    """Все семь полей — литералы К3, читаются обратно ровно тем же значением."""

    def test_all_seven_named_fields_round_trip_through_the_instance(self) -> None:
        """Свойство: конструктор принимает семь полей К3 и хранит их дословно.

        Сломается: если поле переименовано/отсутствует (``AttributeError``/
        ``TypeError`` от Pydantic) или если значение при чтении не совпадает
        с тем, что было передано (тихое приведение типа/потеря данных).
        """
        NumberRecord = _import_number_record()
        rec = NumberRecord(
            name="capture.drops",
            kind="counter",
            value=5.0,
            aggregate=None,
            tags={"process": "camera_0"},
            unit="count",
            ts=1000.0,
            writer="capture",
        )
        assert rec.name == "capture.drops"
        assert rec.kind == "counter"
        assert rec.value == 5.0
        assert rec.aggregate is None
        assert rec.tags == {"process": "camera_0"}
        assert rec.unit == "count"
        assert rec.ts == 1000.0
        assert rec.writer == "capture"

    def test_class_is_a_schema_base_subclass(self) -> None:
        """К3: «``SchemaBase``» — не просто dataclass, а именно базовый класс проекта.

        Сломается: если ``NumberRecord`` унаследован от ``dataclass``/голого
        ``BaseModel``/чего угодно ещё — тогда учёт ``FieldMeta``,
        ``model_dump``, ограничения min/max и т.п. (весь механизм ``SchemaBase``,
        см. ``data_schema_module/core/schema_base.py``) у записи отсутствовал бы.
        """
        from multiprocess_framework.modules.data_schema_module import SchemaBase

        NumberRecord = _import_number_record()
        assert issubclass(NumberRecord, SchemaBase)


class TestKindIsConstrainedToFourLiterals:
    """К3: «``kind(counter|gauge|timing|histogram)``» — перечисление, не свободная строка."""

    @pytest.mark.parametrize("kind", ["counter", "gauge", "timing", "histogram"])
    def test_each_of_the_four_named_kinds_constructs(self, kind: str) -> None:
        NumberRecord = _import_number_record()
        rec = NumberRecord(name="x", kind=kind, value=1.0, aggregate=None, tags={}, unit="", ts=0.0, writer="w")
        assert rec.kind == kind

    def test_a_fifth_value_outside_the_four_literals_is_rejected(self) -> None:
        """Pre-condition: ``kind`` — НЕ произвольная строка.

        ``pytest.raises`` здесь легитимен (не инверсия полярности, см. память
        tester'а ``feedback_pytest_raises_inverts_red_polarity``): это негативный
        контракт «плохой вход обязан быть отклонён навсегда», а не «функция ещё
        не существует». Сегодня тест красный на САМОМ ИМПОРТЕ (модуля нет), а
        не потому что блок ``pytest.raises`` не сработал бы, — это проверено:
        локальный импорт вызывается ДО ``pytest.raises``, поэтому
        ``ModuleNotFoundError`` пробивает тест наружу, не будучи проглоченным.
        """
        from pydantic import ValidationError

        NumberRecord = _import_number_record()
        with pytest.raises(ValidationError):
            NumberRecord(
                name="x", kind="not_a_real_kind", value=1.0, aggregate=None, tags={}, unit="", ts=0.0, writer="w"
            )


class TestValueOrAggregateAreTwoIndependentDialects:
    """К3: «``value | aggregate``» — ДВА поля, любое из них может нести дилект."""

    def test_raw_single_value_dialect_leaves_aggregate_none(self) -> None:
        """Диалект «hub-запись ``metric/value/metric_type``» — несёт голое число."""
        NumberRecord = _import_number_record()
        rec = NumberRecord(
            name="capture.capture_fps",
            kind="gauge",
            value=29.7,
            aggregate=None,
            tags={},
            unit="Hz",
            ts=1.0,
            writer="capture",
        )
        assert rec.value == 29.7
        assert rec.aggregate is None

    def test_aggregate_dialect_carries_a_real_metric_record_aggregate_leaves_value_none(self) -> None:
        """Диалект «агрегат ``MetricRecord.aggregate()``» — несёт РЕАЛЬНЫЙ агрегат.

        Не выдуманная форма словаря: строю ``aggregate`` НАСТОЯЩИМ
        ``MetricRecord`` (существующий класс, не предмет этой задачи) —
        связь «агрегат = то, что уже отдаёт ``MetricRecord.aggregate()``»
        проверена на реальном объекте, а не на форме, которую я придумал сам.
        """
        from multiprocess_framework.modules.statistics_module.core.metric_record import MetricRecord, MetricType

        metric = MetricRecord(name="dispatch.duration", metric_type=MetricType.TIMING)
        metric.observe(0.001)
        metric.observe(0.002)
        metric.observe(0.003)
        aggregate_payload = metric.aggregate()
        assert aggregate_payload["count"] == 3  # контроль: фикстура сама не собралась бы иначе

        NumberRecord = _import_number_record()
        rec = NumberRecord(
            name="dispatch.duration",
            kind="timing",
            value=None,
            aggregate=aggregate_payload,
            tags={},
            unit="s",
            ts=2.0,
            writer="dispatcher",
        )
        assert rec.aggregate == aggregate_payload
        assert rec.value is None


class TestToDictIsPlainPickleSafe:
    """Правило проекта №1 (Dict at Boundary) + прецедент ``ObservationRecord.to_dict()``.

    Имя метода ``to_dict`` НЕ подтверждено буквой К3 — явно помечено как
    допущение тестера (см. докстринг модуля). Если реализация выберет другое
    имя, этот класс останется красным по неверной причине (AttributeError на
    ``to_dict``, а не по существу) — это будет видно в отчёте.
    """

    def test_to_dict_returns_a_plain_dict_with_literal_field_values(self) -> None:
        NumberRecord = _import_number_record()
        rec = NumberRecord(
            name="capture.drops",
            kind="counter",
            value=3.0,
            aggregate=None,
            tags={"a": "b"},
            unit="count",
            ts=5.0,
            writer="capture",
        )
        d = rec.to_dict()
        assert type(d) is dict, f"to_dict() обязан вернуть ГОЛЫЙ dict (Dict at Boundary), получено {type(d)}"
        assert d["name"] == "capture.drops"
        assert d["kind"] == "counter"
        assert d["value"] == 3.0
        assert d["tags"] == {"a": "b"}
        assert d["unit"] == "count"
        assert d["ts"] == 5.0
        assert d["writer"] == "capture"

    def test_to_dict_result_survives_a_pickle_round_trip(self) -> None:
        """Pickle-safe — буквальное требование границы процесса (Dict at Boundary).

        Записи наблюдаемости пересекают границу процесса (hub → drain →
        стор/форвардер); dict, не переживающий pickle (например, из-за
        вложенного не-pickle-safe объекта в ``aggregate``), молча уронил бы
        именно ту доставку, ради которой К3 и существует.

        ``pickle.loads`` здесь безопасен: он читает байты, которые СТРОКОЙ ВЫШЕ
        в этом же процессе произвёл ``pickle.dumps`` над локальными данными —
        не десериализация недоверенного входа (см. security-guidance).
        """
        NumberRecord = _import_number_record()
        rec = NumberRecord(
            name="capture.drops", kind="gauge", value=1.0, aggregate=None, tags={}, unit="", ts=0.0, writer="capture"
        )
        d = rec.to_dict()
        assert pickle.loads(pickle.dumps(d)) == d
