# -*- coding: utf-8 -*-
"""Авторские тесты опасных мест Ф1 — ДОПОЛНЕНИЕ к приёмочным, не замена.

Приёмочный набор (`test_mapping_acceptance.py`, `test_resources_acceptance.py`)
написан независимым тестером по актам приёмки и проверяет КОНТРАКТ. Здесь —
только то, что видно автору из устройства механизма и чего тестер видеть не мог:

* места, которые тестер назвал непроверенными своими словами (идентичность
  объекта `Resource` при повторе ключа; порядок вытеснения, а не только счёт);
* решения, принятые АВТОРОМ при реализации и потому не описанные ни в одном
  акте: отказ на нулевом `trace_id`, `None`-значение поля контекста как то же
  отсутствие, пустой `service_namespace` без атрибута, отказ пула размера < 1;
* швы между двумя сторожами числовой плоскости — фильтр считает по `kind`,
  маппер отказывает ещё и по `severity`; каждый обязан краснеть от СВОЕЙ
  инъекции, иначе снятие одного маскируется вторым;
* `isinstance` против Protocol'ов — единственная причина, по которой конкретные
  классы зовутся `DisplayRecordMapper`/`PooledResourceResolver` (Р-1/Р-2).
  Верни имя `RecordMapper` конкретному классу — и этот тест умрёт первым.
"""

from __future__ import annotations

import copy
import socket
from typing import Any

import pytest

from Services.otel_export.interfaces import RecordMapper, ResourceResolver
from Services.otel_export.mapping import DisplayRecordMapper, split_exportable
from Services.otel_export.resources import PooledResourceResolver
from Services.otel_export.tests._snapshot_fixtures import load_snapshot_records

LOG_RECORDS = load_snapshot_records("log")
STATS_RECORDS = load_snapshot_records("stats")
OBSERVATION_RECORDS = load_snapshot_records("observation")


@pytest.fixture()
def log_record() -> dict[str, Any]:
    assert LOG_RECORDS, "в снимке не нашлось ни одной записи kind=log"
    return copy.deepcopy(LOG_RECORDS[0])


@pytest.fixture()
def context(log_record: dict[str, Any]) -> dict[str, Any]:
    return dict(log_record["extra"]["context"])


class TestSplitExportable:
    """Task 1.3: разбивку отдаёт ПРЕДМЕТ, а не тест (Р-5)."""

    def test_snapshot_batch_split_and_no_record_vanishes(self, log_record: dict[str, Any]) -> None:
        """Батч снимка -> `to_send` = log + error, пропуск `{stats: 1, observation: 1}`.

        Второе утверждение важнее первого: тождество
        `len(to_send) + sum(skipped) == len(batch)` ловит класс дефекта, который
        первое пропускает, — запись, потерянную обеими половинами. «Ушло 2,
        пропущено 1» при батче из 4 выглядит правдоподобно и означает потерю.
        """
        error_record = copy.deepcopy(log_record)
        error_record["kind"] = "error"
        batch = [log_record, error_record, STATS_RECORDS[0], OBSERVATION_RECORDS[0]]

        to_send, skipped_by_kind = split_exportable(batch)

        assert [r["kind"] for r in to_send] == ["log", "error"]
        assert dict(skipped_by_kind) == {"stats": 1, "observation": 1}
        assert len(to_send) + sum(skipped_by_kind.values()) == len(batch)

    def test_filter_counts_by_kind_while_mapper_also_refuses_by_severity(self, log_record: dict[str, Any]) -> None:
        """Шов двух сторожей: `kind=log` при `severity="number"`.

        Фильтр 1.3 считает по РОДУ — запись проходит (род не числовой). Маппер
        отказывает по `severity` — он последний рубеж. Тест пришивает обе
        половины сразу: сведи их к одному признаку, и одна из двух инъекций
        («снять род из фильтра», «снять проверку severity у маппера») перестанет
        краснеть, а вторая замаскирует её.
        """
        drifted = copy.deepcopy(log_record)
        drifted["severity"] = "number"

        to_send, skipped_by_kind = split_exportable([drifted])

        assert to_send == [drifted], "фильтр обязан считать по kind, а не по severity"
        assert dict(skipped_by_kind) == {}
        assert DisplayRecordMapper().to_otlp(drifted) is None, "маппер обязан отказать по severity"


class TestMapperHazards:
    def test_satisfies_the_runtime_checkable_protocol(self) -> None:
        """Р-1: конкретный класс зовётся иначе, чем Protocol, — иначе `isinstance` ломается."""
        assert isinstance(DisplayRecordMapper(), RecordMapper)

    def test_uppercase_trace_id_normalized_to_lowercase(self, log_record: dict[str, Any]) -> None:
        """W3C требует нижний регистр; регулярка владельца принимает оба.

        Без нормализации один и тот же след кадра, записанный разным регистром,
        разъезжается у приёмника на две трассы — и это видно только там.
        """
        log_record["extra"]["context"]["trace_id"] = "0AF7651916CD43DD8448EB211C80319C"
        mapped = DisplayRecordMapper().to_otlp(log_record)
        assert mapped is not None
        assert mapped.trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_all_zero_trace_id_is_refused_not_forwarded(self, log_record: dict[str, Any]) -> None:
        """Решение автора: `"0"*32` — заполнение, а не идентификатор.

        По длине и алфавиту он валиден, по W3C — нет. Пропусти его наружу, и
        приёмник склеит по нему все записи всех источников, у которых источник
        следа не проставил.
        """
        log_record["extra"]["context"]["trace_id"] = "0" * 32
        mapped = DisplayRecordMapper().to_otlp(log_record)
        assert mapped is not None
        assert mapped.trace_id is None

    @pytest.mark.parametrize(
        "bad_ts",
        [None, "1788631974.75", float("nan"), float("inf"), True],
        ids=["none", "string", "nan", "inf", "bool"],
    )
    def test_broken_ts_gives_none_and_never_raises(self, log_record: dict[str, Any], bad_ts: Any) -> None:
        """Битая метка времени -> поля нет; исключения в потоке приёма НЕТ.

        `round(float("nan"))` поднимает `ValueError`, а `True` — подкласс `int`
        и без отдельной проверки дал бы метку «1 нс от эпохи», то есть 1970 год
        у половины записей вместо честного пропуска.
        """
        log_record["ts"] = bad_ts
        mapped = DisplayRecordMapper().to_otlp(log_record)
        assert mapped is not None
        assert mapped.timestamp_ns is None

    def test_log_record_with_flat_extra_still_maps(self, log_record: dict[str, Any]) -> None:
        """Форма `extra` разъехалась (плоская у рода `log`) — запись не теряется.

        Атрибуты при этом НЕ выдумываются из плоского `extra`: числовая форма
        несёт `value`/`metrics`/`tags`, и свалить их в `Attributes` значило бы
        протащить числовую плоскость в логи обходным путём.
        """
        log_record["extra"] = {"value": 21.3, "tags": {"plugin": "capture"}}
        mapped = DisplayRecordMapper().to_otlp(log_record)
        assert mapped is not None
        assert mapped.attributes == {"record.kind": "log"}


class TestResolverHazards:
    def test_satisfies_the_runtime_checkable_protocol(self) -> None:
        """Р-2: `PooledResourceResolver`, а не `ResourceResolver` — иначе `isinstance` ломается."""
        assert isinstance(PooledResourceResolver(), ResourceResolver)

    def test_same_key_returns_the_very_same_object(self, context: dict[str, Any]) -> None:
        """Тестер оставил это непроверенным своими словами: счётчик проверен, КЭШ — нет.

        Счётчик вытеснения равен нулю и у настоящего пула, и у резолвера,
        который собирает Resource заново на каждую запись и кладёт его в пул
        поверх прежнего. Отличает их только тождество объекта.
        """
        resolver = PooledResourceResolver(resource_pool_size=4)
        first = resolver.resolve(context)
        second = resolver.resolve(dict(context))

        assert first is second
        assert resolver.pooled == 1

    def test_eviction_follows_use_not_insertion_order(self, context: dict[str, Any]) -> None:
        """LRU, а не FIFO: повторное обращение к A обязано его СПАСТИ.

        Пул размера 2: A, B, снова A, затем C. Вытесниться обязан B — самый
        давно не используемый. FIFO выкинул бы A, то есть самый активный
        источник, и пул стал бы кэшем, промахивающимся ровно там, где нужен.
        """
        resolver = PooledResourceResolver(resource_pool_size=2)
        a = resolver.resolve(dict(context, proc_name="camera_0", pid=100))
        resolver.resolve(dict(context, proc_name="camera_1", pid=101))
        assert resolver.resolve(dict(context, proc_name="camera_0", pid=100)) is a
        resolver.resolve(dict(context, proc_name="camera_2", pid=102))

        assert resolver.evicted == 1
        assert resolver.resolve(dict(context, proc_name="camera_0", pid=100)) is a, "вытеснили активный источник"
        assert resolver.resolve(dict(context, proc_name="camera_1", pid=101)) is not None

    def test_none_valued_context_field_is_omitted_not_written_as_none(self, context: dict[str, Any]) -> None:
        """Решение автора: `None` — то же отсутствие, что и нет ключа.

        Значением атрибута OTel `None` быть не может; попав в `attributes`, он
        доехал бы до приёмника строкой `"None"` или отказом сериализации —
        и то и другое хуже честного пропуска поля.
        """
        context["fw_version"] = None
        resource = PooledResourceResolver().resolve(context)

        assert "service.version" not in resource.attributes
        assert None not in resource.attributes.values()
        assert resource.attributes["service.name"] == "camera_0"

    def test_empty_namespace_and_host_omit_their_attributes(self, context: dict[str, Any]) -> None:
        """Пусто -> атрибута НЕТ, а не пустая строка.

        Пара к дефолту: `host_name=""` — это и есть инъекция «снять host.name»,
        и она обязана давать отсутствие ключа, а не `host.name == ""`, иначе
        приёмник получит источник с пустым именем хоста и посчитает его хостом.
        """
        resolver = PooledResourceResolver(service_namespace="", host_name="")
        resource = resolver.resolve(context)

        assert "service.namespace" not in resource.attributes
        assert "host.name" not in resource.attributes
        # Контроль: с дефолтами оба атрибута на месте — тест выше не вакуумен.
        default_resource = PooledResourceResolver(service_namespace="ns").resolve(context)
        assert default_resource.attributes["host.name"] == socket.gethostname()
        assert default_resource.attributes["service.namespace"] == "ns"

    def test_pool_smaller_than_one_is_refused_at_construction(self) -> None:
        """Пул размера 0 вытесняет каждую запись: счётчик вытеснения стал бы счётчиком вызовов."""
        with pytest.raises(ValueError, match="resource_pool_size"):
            PooledResourceResolver(resource_pool_size=0)
