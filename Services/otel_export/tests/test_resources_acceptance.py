# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.2 плана otel-export — НЕЗАВИСИМЫЙ тестер, ДО кода.

Источник критериев — акт приёмки Task 1.2, переданный тестеру буквально. Файл
`Services/otel_export/resources.py` на диске НЕ существует — проверено. Импорт предмета
ВНУТРИ каждого теста, чтобы `pytest --collect-only` видел полный список тестов и без пакета.

**Два угаданных крючка, оба названы вслух (не спрятаны).**

1. Имя класса — тестер угадал ``ResourceResolver``, но оно занято Protocol'ом; автор назвал
   конкретный класс ``PooledResourceResolver``. Основание то же, что и
   в `test_mapping_acceptance.py`: `interfaces.py:4-6` говорит, что реализация «пишется под
   уже названные здесь имена» (имя Protocol'а).
2. Атрибут счётчика вытеснения — угадан как ``resolver.evicted`` (локальная часть
   точечного имени метрики ``otel_export.resource_evicted`` из README «Counters»). Protocol
   `ResourceResolver.resolve` в `interfaces.py` НЕ объявляет способ достать этот счётчик —
   README называет только точку в плоскости чисел (`ctx.record_metric`), а кто её зовёт
   (сам резолвер или хост, читающий что-то с резолвера) — не сказано. Это ВТОРОЙ угаданный
   крючок, слабее первого; если тест `TestEviction` падает не на этом атрибуте, а на форме
   Resource — это всё равно значимый результат, но сам факт вытеснения тестом не доказан.
   Назван отдельным пунктом отчёта.

Вход — реальный `extra.context` записи снимка (`tail_debug.json`, kind=log, camera_0).
Второй источник (другой `proc_name`/`pid`) в снимке физически отсутствует (карточка Task 1.0
§6: «все 144 записи страницы — от одного процесса camera_0») — везде, где нужен второй
источник, он ВЫВЕДЕН тем же составом полей context, с другими значениями.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from Services.otel_export.tests._snapshot_fixtures import load_snapshot_records

LOG_RECORDS = load_snapshot_records("log")


def _resolver(resource_pool_size: int = 64, service_namespace: str = "region_pipeline_ns"):
    """Первый угаданный крючок файла — см. докстринг модуля."""
    from Services.otel_export.resources import PooledResourceResolver

    return PooledResourceResolver(resource_pool_size=resource_pool_size, service_namespace=service_namespace)


@pytest.fixture(scope="module")
def real_context() -> dict[str, Any]:
    assert LOG_RECORDS, "в снимке не нашлось ни одной записи kind=log"
    context = LOG_RECORDS[0]["extra"]["context"]
    # Сторож входа: состав context стабилен (карточка §3) — иначе тест ниже проверяет не то.
    assert context == {
        "proc_name": "camera_0",
        "pid": 2692,
        "fw_version": "2.0.0+1f40ce0d.dirty",
        "incarnation": 0,
        "recipe": "region_pipeline",
        "origin": "stats_snapshot",
    }
    return dict(context)


class TestFieldMapping:
    def test_five_fields_map_literally(self, real_context: dict[str, Any]) -> None:
        """`proc_name/fw_version/incarnation/pid/recipe` -> semconv, значения литералами."""
        resolver = _resolver()
        resource = resolver.resolve(real_context)

        assert resource.attributes["service.name"] == "camera_0"
        assert resource.attributes["service.version"] == "2.0.0+1f40ce0d.dirty"
        # `service.instance.id` больше не копия `incarnation` — вердикт CTO по О-6
        # (2026-09-06), правка акта Task 1.2. Проверяется отдельно, литералом формы,
        # в TestInstanceIdIsAStringAndIdentifiesTheRun ниже.
        assert resource.attributes["process.pid"] == 2692
        assert resource.attributes["inspector.recipe"] == "region_pipeline"

    def test_origin_and_trace_id_do_not_leak_into_resource(self, real_context: dict[str, Any]) -> None:
        """`origin` (шестое поле context) и `trace_id` — НЕ поля Resource.

        `origin` уезжает в `Attributes` записи (Task 1.1), а не в `Resource` — это разные
        назначения одного и того же context, и путать их — конкретный класс дефекта.
        """
        resolver = _resolver()
        resource = resolver.resolve(real_context)

        assert "origin" not in resource.attributes
        assert not any("stats_snapshot" == v for v in resource.attributes.values())

    def test_incarnation_zero_still_produces_the_attribute(self, real_context: dict[str, Any]) -> None:
        """`incarnation=0` (ложное значение в Python) — поле ПРИСУТСТВУЕТ в context, значит
        и в Resource оно обязано остаться, а не выпасть по проверке `if incarnation:`.

        Это конкретный класс дефекта: наивная проверка истинности неотличима от «поля нет»
        ровно на нуле — самом частом значении incarnation при первом старте процесса.
        """
        assert real_context["incarnation"] == 0
        resolver = _resolver()
        resource = resolver.resolve(real_context)
        assert "service.instance.id" in resource.attributes
        # Свойство прежнее — ноль не выпадает по проверке истинности; изменилась
        # только форма значения (вердикт CTO по О-6): составная строка вместо int.
        assert resource.attributes["service.instance.id"].endswith(":2692:0")

    def test_missing_fw_version_omits_service_version_not_unknown(self, real_context: dict[str, Any]) -> None:
        """Запись без `fw_version` -> ключа `service.version` НЕТ (инвариант из interfaces.py:53-56)."""
        context = dict(real_context)
        del context["fw_version"]

        resolver = _resolver()
        resource = resolver.resolve(context)

        assert "service.version" not in resource.attributes
        assert "unknown" not in resource.attributes.values()
        # Остальные поля context всё ещё маппятся — отсутствие ОДНОГО не роняет остальные.
        assert resource.attributes["service.name"] == "camera_0"


class TestHostAndNamespaceAreExporterLevel:
    """`host.name` (из `socket.gethostname()`) и `service.namespace` — одни у ВСЕХ записей."""

    def test_two_different_sources_get_two_different_resources(self, real_context: dict[str, Any]) -> None:
        """ВЫВЕДЕНО: снимок несёт только один источник (camera_0) — второй context
        построен той же формой (шесть ключей), с другими значениями proc_name/pid.
        """
        context_a = real_context
        context_b = dict(real_context, proc_name="camera_1", pid=3001, incarnation=2)

        resolver = _resolver()
        resource_a = resolver.resolve(context_a)
        resource_b = resolver.resolve(context_b)

        assert resource_a.attributes["service.name"] == "camera_0"
        assert resource_b.attributes["service.name"] == "camera_1"
        assert resource_a.attributes["process.pid"] != resource_b.attributes["process.pid"]
        assert resource_a.attributes != resource_b.attributes

    def test_host_name_and_namespace_identical_across_sources(self, real_context: dict[str, Any]) -> None:
        context_a = real_context
        context_b = dict(real_context, proc_name="camera_1", pid=3001, incarnation=2)

        resolver = _resolver(service_namespace="region_pipeline_ns")
        resource_a = resolver.resolve(context_a)
        resource_b = resolver.resolve(context_b)

        assert resource_a.attributes.get("host.name") == socket.gethostname()
        assert resource_b.attributes.get("host.name") == socket.gethostname()
        assert resource_a.attributes.get("service.namespace") == "region_pipeline_ns"
        assert resource_b.attributes.get("service.namespace") == "region_pipeline_ns"


class TestEviction:
    """Пул ограничен `resource_pool_size`; вытеснение LRU -> `resource_evicted` растёт.

    Второй угаданный крючок файла (см. докстринг модуля) — атрибут `resolver.evicted`.
    """

    def _context(self, real_context: dict[str, Any], *, proc_name: str, pid: int, incarnation: int) -> dict[str, Any]:
        return dict(real_context, proc_name=proc_name, pid=pid, incarnation=incarnation)

    def test_no_eviction_within_capacity(self, real_context: dict[str, Any]) -> None:
        """ОБЯЗАТЕЛЬНАЯ пара: N источников при пуле размера N -> счётчик 0."""
        resolver = _resolver(resource_pool_size=2)
        resolver.resolve(self._context(real_context, proc_name="camera_0", pid=100, incarnation=0))
        resolver.resolve(self._context(real_context, proc_name="camera_1", pid=101, incarnation=0))

        assert resolver.evicted == 0

    def test_n_plus_one_source_evicts_the_oldest(self, real_context: dict[str, Any]) -> None:
        """Пул размера 2, третий РАЗЛИЧНЫЙ источник -> вытеснение, счётчик = 1."""
        resolver = _resolver(resource_pool_size=2)
        resolver.resolve(self._context(real_context, proc_name="camera_0", pid=100, incarnation=0))
        resolver.resolve(self._context(real_context, proc_name="camera_1", pid=101, incarnation=0))
        resolver.resolve(self._context(real_context, proc_name="camera_2", pid=102, incarnation=0))

        assert resolver.evicted == 1

    def test_repeated_same_key_does_not_count_as_a_new_source(self, real_context: dict[str, Any]) -> None:
        """Ключ пула — `(proc_name, pid, incarnation)`: повтор ТОГО ЖЕ ключа — не новый
        источник и не должен вытеснять при пуле размера 1.
        """
        resolver = _resolver(resource_pool_size=1)
        ctx = self._context(real_context, proc_name="camera_0", pid=100, incarnation=0)
        resolver.resolve(ctx)
        resolver.resolve(dict(ctx))  # тот же ключ, новый dict-объект
        resolver.resolve(dict(ctx))

        assert resolver.evicted == 0


class TestInstanceIdIsAStringAndIdentifiesTheRun:
    """О-6, вердикт CTO 2026-09-06: `service.instance.id` — СТРОКА и составная.

    Два отдельных свойства, и они разделены намеренно (предсказание CTO для
    инъекционной матрицы): откат на голый `incarnation`-int обязан красить
    **только** тест типа; тесты формы на `str()` остались бы зелёными, потому
    что `"3" != "4"` истинно и для чисел, приведённых к строке.
    """

    def test_encoded_attribute_is_string_value_not_int(self, real_context: dict[str, Any]) -> None:
        """У ЗАКОДИРОВАННОГО ресурса атрибут — `string_value`, литералом.

        Проверяется у кодировщика OTLP, а не у Python-объекта: `Resource` хранит
        что дали, а расходится с semconv именно провод. Доступ **по ключу, а не
        по индексу** — `Resource.create` подмешивает `telemetry.sdk.*`, и
        `attributes[0]` читает чужой атрибут. На этом уже ошиблась первая
        проверка CTO, поймал он сам.
        """
        from opentelemetry.exporter.otlp.proto.common._internal import _encode_resource

        resolver = _resolver()
        encoded = _encode_resource(resolver.resolve(real_context))
        found = [kv for kv in encoded.attributes if kv.key == "service.instance.id"]
        assert len(found) == 1, f"ожидался ровно один service.instance.id, получено {len(found)}"
        assert found[0].value.WhichOneof("value") == "string_value"

    def test_restart_of_the_source_yields_a_different_id(self, real_context: dict[str, Any]) -> None:
        """Рестарт источника -> другой id. Критерий Task 4.1."""
        resolver = _resolver()
        before = resolver.resolve({**real_context, "incarnation": 0})
        after = resolver.resolve({**real_context, "incarnation": 1})
        assert before.attributes["service.instance.id"] != after.attributes["service.instance.id"]

    def test_two_hosts_yield_different_ids(self, real_context: dict[str, Any]) -> None:
        """Два хоста -> разные id. Без этого флот устройств на одном коллекторе сливается."""
        from Services.otel_export.resources import PooledResourceResolver

        a = PooledResourceResolver(resource_pool_size=8, service_namespace="inspector", host_name="node-a").resolve(
            real_context
        )
        b = PooledResourceResolver(resource_pool_size=8, service_namespace="inspector", host_name="node-b").resolve(
            real_context
        )
        assert a.attributes["service.instance.id"] != b.attributes["service.instance.id"]

    def test_two_launches_at_incarnation_zero_yield_different_ids(self, real_context: dict[str, Any]) -> None:
        """ДВА ЗАПУСКА системы при `incarnation=0` -> разные id.

        Это тот сторож, ради которого форма и составная. `incarnation` живёт в
        памяти ProcessManager (`process_manager_process.py:93`) и пуст при каждом
        старте лаунчера, поэтому форма `host:proc:incarnation` дала бы
        `host:camera_0:0` на КАЖДОМ запуске, и два разных экземпляра склеились бы
        в один временной ряд. Компонент запуска — `pid`.

        Честный остаток, названный и здесь: если ОС переиспользует тот же `pid`
        для того же имени с той же инкарнацией на том же хосте — id совпадёт.
        Сужение, не устранение.
        """
        resolver = _resolver()
        run_one = resolver.resolve({**real_context, "pid": 2692, "incarnation": 0})
        run_two = resolver.resolve({**real_context, "pid": 3001, "incarnation": 0})
        assert run_one.attributes["service.instance.id"] != run_two.attributes["service.instance.id"]

    def test_a_missing_part_drops_the_attribute_entirely(self, real_context: dict[str, Any]) -> None:
        """Нет хотя бы одной части -> атрибута НЕТ вовсе.

        Полуидентификатор хуже отсутствующего: он выглядит рабочим и склеивает
        чужие ряды молча, а отсутствие атрибута видно сразу.
        """
        resolver = _resolver()
        without_pid = {k: v for k, v in real_context.items() if k != "pid"}
        assert "service.instance.id" not in resolver.resolve(without_pid).attributes
