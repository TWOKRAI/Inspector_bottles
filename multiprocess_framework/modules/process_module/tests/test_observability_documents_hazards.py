# -*- coding: utf-8 -*-
"""Ф8.5 — опасности САМОГО механизма плоскости документов (тесты автора).

Приёмку («ключ есть → документ в БД») закрывает независимый набор. Здесь то, что видно
только изнутри устройства и в диффе не читается:

* отметка, которую механизм дописывает в запись УЖЕ ПОСЛЕ публикации, отключает
  схлопывание — ровно на отказе, когда поток повторов максимален (M-1 ревью Ф8);
* форма доставки конфига у оркестратора и у ребёнка РАЗНАЯ (плоский корень против
  ``config.``) — механизм обязан читать обе, иначе плоскость есть у одного процесса
  из восьми;
* порядок отцепления на teardown: сток обязан уйти от аудита ДО закрытия БД;
* срок следующей уборки обязан ставиться ДО самой уборки — иначе отказ БД
  превращается в попытку каждый такт, то есть в нагрузку на неё же.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from multiprocess_framework.modules.process_module.configs.observability_audit import (
    _AUDIT_OWNED_FIELDS,
    ObservabilityAudit,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    DEFAULT_PURGE_INTERVAL_SEC,
    DOCUMENT_SINK_ATTR,
    DOCUMENTS_CONFIG_ADDRESS,
    resolve_factory,
    sweep_process_documents,
    unwire_document_sink,
    wire_document_sink,
)


class _Svc:
    """Минимальный процесс: конфиг, имя, журнал. Логгер УМЕЕТ различать уровни.

    Отдельные списки ``warnings``/``infos``: фальшивка, сваливающая всё в один список,
    не отличила бы «сказали вслух» от «сказали шёпотом», а вся задача 8.5c именно про
    громкость отказа.
    """

    def __init__(self, config: Dict[str, Any], name: str = "proc") -> None:
        self._config = config
        self.name = name
        self.warnings: List[str] = []
        self.infos: List[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        node: Any = self._config
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _log_warning(self, message: str, module: str = "") -> None:
        self.warnings.append(message)

    def _log_info(self, message: str, module: str = "") -> None:
        self.infos.append(message)


class _FailingStore:
    """Сток, который отказывает и на записи, и на уборке. Считает попытки."""

    def __init__(self) -> None:
        self.append_calls = 0
        self.purge_calls = 0
        self.closed = False
        #: Что видит сток в момент своего закрытия. Через него проверяется ПОРЯДОК
        #: teardown'а: сам факт «закрыт и отцеплен» одинаков при любом порядке строк.
        self.on_close: Optional[Any] = None

    def append(self, document: Dict[str, Any]) -> bool:
        self.append_calls += 1
        if self.closed:
            raise RuntimeError("соединение закрыто")
        return False

    def purge_expired(self, now: Optional[float] = None) -> int:
        self.purge_calls += 1
        raise RuntimeError("БД недоступна")

    def close(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.closed = True


_FAILING_STORES: List[_FailingStore] = []


def _failing_factory(config: Dict[str, Any]) -> _FailingStore:
    """Фабрика для конфига: модульная функция, потому что резолв идёт import-path'ом."""
    store = _FailingStore()
    _FAILING_STORES.append(store)
    return store


def _not_a_sink(config: Dict[str, Any]) -> object:
    """Вернуть объект БЕЗ ``append`` — структурная проверка обязана его отвергнуть."""
    return object()


_FACTORY = f"{__name__}:_failing_factory"


def _section(factory: str, **config: Any) -> Dict[str, Any]:
    return {"documents": {"factory": factory, "config": config}}


# ---------------------------------------------------------------------------
# M-1: отметка после публикации против схлопывания
# ---------------------------------------------------------------------------


class TestCollapseSurvivesAFailingSink:
    def test_ten_failures_are_one_ring_entry_with_repeats(self) -> None:
        """Репро ревью Ф8 переворачивается: было ``ring=10``, стало ``ring=1, repeats=10``.

        Механика дефекта: ``document_failed`` дописывается в запись, УЖЕ лежащую в
        кольце, а следующая приходит без неё — сравнение условий видит разные наборы
        ключей и схлопывание выключается. Выключается оно ровно на отказе, то есть
        тогда, когда подметальщик повторяет попытку каждый такт и место в кольце
        дороже всего: сотня отказов выедала историю за ~8 минут вместе с причиной.
        """
        audit = ObservabilityAudit(sink=lambda doc: False, clock=lambda: 1.0)

        for _ in range(10):
            audit.record("expire", origin="ttl-sweeper", key="scopes.SYSTEM", ok=False, error="занято")

        assert len(audit.ring) == 1
        assert audit.ring[0]["repeats"] == 10
        assert audit.ring[0]["document_failed"] is True

    def test_raising_sink_collapses_too(self) -> None:
        """Второй сорт отказа — исключение: оно дописывает ДВА поля, а не одно.

        Забудь мы в перечне ``document_error`` — этот тест остался бы красным, а
        соседний зелёным, то есть половина дефекта уехала бы незамеченной.
        """
        audit = ObservabilityAudit(sink=_raise, clock=lambda: 1.0)

        for _ in range(5):
            audit.record("set", origin="watcher:app", key="log_level", value="DEBUG")

        assert len(audit.ring) == 1
        assert audit.ring[0]["repeats"] == 5
        assert "document_error" in audit.ring[0]

    def test_seq_and_dropped_stay_consistent_under_failures(self) -> None:
        """Повтор не двигает ``seq`` — иначе ``dropped`` отрапортует вытеснение, которого не было."""
        audit = ObservabilityAudit(sink=lambda doc: False, clock=lambda: 1.0)

        for _ in range(10):
            audit.record("set", origin="switch", key="k")

        assert audit.seq == 1
        assert audit.dropped() == 0

    def test_every_post_publication_mark_is_declared_owned(self) -> None:
        """Страж класса, а не одного случая.

        Оба известных сорта отметок — журнальная и документная — дописываются после
        публикации, и оба обязаны быть в перечне «поля самого аудита». Появится
        третий писатель со своей отметкой — этот список придётся расширить осознанно.
        """
        assert {"log_failed", "document_failed", "document_error"} <= _AUDIT_OWNED_FIELDS


def _raise(document: Dict[str, Any]) -> Any:
    raise RuntimeError("БД недоступна")


# ---------------------------------------------------------------------------
# m-4: конверт документа
# ---------------------------------------------------------------------------


class TestDocumentEnvelopeIsNotHijackable:
    def test_extra_kind_does_not_steal_the_document_kind(self) -> None:
        """``kind`` — идентичность записи в плоскости, а не поле смены.

        Уедь запись аудита в чужой род — её не найдёт ни ретеншен (срок берётся
        per-kind), ни чтение вкладки, и потеря будет молчаливой: ``append`` вернёт
        True, документ ляжет, спросить его будет некому.
        """
        seen: List[Dict[str, Any]] = []
        audit = ObservabilityAudit(sink=lambda doc: seen.append(doc) or True, clock=lambda: 7.0)

        audit.record("set", origin="switch", key="log_level", kind="verdict")

        assert seen[0]["kind"] == "audit"
        assert seen[0]["ts"] == 7.0

    def test_source_names_the_process(self) -> None:
        """Плоскость одна на систему: без имени процесса восемь писателей неразличимы."""
        seen: List[Dict[str, Any]] = []
        audit = ObservabilityAudit(sink=lambda doc: seen.append(doc) or True, clock=lambda: 1.0, source="gui")

        audit.record("set", origin="switch", key="log_level")

        assert seen[0]["source"] == "gui"


# ---------------------------------------------------------------------------
# Резолв import-path
# ---------------------------------------------------------------------------


class TestResolveFactory:
    def test_colon_and_dot_forms_give_the_same_object(self) -> None:
        assert resolve_factory(_FACTORY) is _failing_factory
        assert resolve_factory(f"{__name__}.{_failing_factory.__name__}") is _failing_factory

    @pytest.mark.parametrize(
        "path",
        ["", "нет_двоеточия_и_точки", "no.such.module:nope", f"{__name__}:НетТакогоАтрибута"],
    )
    def test_bad_paths_raise_rather_than_return_none(self, path: str) -> None:
        """Отказ громкий. ``None`` здесь неотличим от «плоскость не настроена»."""
        with pytest.raises((ValueError, ImportError, AttributeError, TypeError)):
            resolve_factory(path)

    def test_non_callable_target_is_refused(self) -> None:
        with pytest.raises(TypeError):
            resolve_factory(f"{__name__}:_FACTORY")


# ---------------------------------------------------------------------------
# Сшивка: обе формы доставки конфига, громкость отказа, порядок teardown
# ---------------------------------------------------------------------------


class TestWiringHazards:
    def setup_method(self) -> None:
        _FAILING_STORES.clear()

    def test_child_process_shape_is_read_too(self) -> None:
        """Форма доставки конфига РАЗНАЯ у оркестратора и у ребёнка.

        Оркестратор получает конфиг плоским (spawner мержит в корень), ребёнок — весь
        ``proc_dict``, поэтому его ключи лежат под ``config.``. Живой прогон 5.12 уже
        ловил на этом ``observability.persist``: тесты подавали плоский словарь и
        доказывали фейк. Здесь проверяются ОБЕ формы, потому что процессов второй
        формы в системе большинство.
        """
        flat = _Svc({"observability_app": _section(_FACTORY)})
        nested = _Svc({"config": {"observability_app": _section(_FACTORY)}})

        assert wire_document_sink(flat) is not None
        assert wire_document_sink(nested) is not None, "у ребёнка ключ лежит под config."

    def test_absent_section_is_silent_and_harmless(self) -> None:
        svc = _Svc({})

        assert wire_document_sink(svc) is None
        assert svc.warnings == [], "«не настроено» — не повод шуметь"

    def test_empty_factory_is_silent(self) -> None:
        svc = _Svc({"observability_app": _section("")})

        assert wire_document_sink(svc) is None
        assert svc.warnings == []

    def test_broken_factory_warns_with_the_config_address(self) -> None:
        """Отказ фабрики — громкий, но не фатальный, и адрес ключа в тексте обязателен.

        Без адреса оператор получает «что-то не поднялось» и не знает, где править;
        адрес — это то, чем сообщение отличается от шума.
        """
        svc = _Svc({"observability_app": _section("no.such.module:nope")})

        assert wire_document_sink(svc) is None
        assert len(svc.warnings) == 1
        assert DOCUMENTS_CONFIG_ADDRESS in svc.warnings[0]
        assert "no.such.module:nope" in svc.warnings[0]

    def test_object_without_append_is_refused_loudly(self) -> None:
        svc = _Svc({"observability_app": _section(f"{__name__}:_not_a_sink")})

        assert wire_document_sink(svc) is None
        assert len(svc.warnings) == 1
        assert "append" in svc.warnings[0]
        # Адрес ключа обязателен в ОБЕИХ точках отказа, а не в одной. Пробел нашёл
        # независимый tester: правило было применено к ветке «фабрика не резолвится»
        # и забыто в ветке «резолвится, но не сток».
        assert DOCUMENTS_CONFIG_ADDRESS in svc.warnings[0]
        assert process_observability_layers(svc).audit.sink is None

    def test_teardown_detaches_the_sink_before_closing_the_db(self) -> None:
        """Порядок, а не факт.

        Закрой мы БД первой — запись аудита, случившаяся между двумя строками (её
        может породить сам teardown), ушла бы в закрытое соединение и дала бы отказ
        ровно на остановке, где его труднее всего объяснить.

        Проверять «закрыт и отцеплен» бессмысленно: в конце обе строки выполнены при
        любом их порядке. Поэтому спрашиваем сам сток в момент его закрытия — что он
        видит на месте аудита. Правильный порядок означает, что видит он уже ``None``.
        """
        svc = _Svc({"observability_app": _section(_FACTORY)})
        wire_document_sink(svc)
        audit = process_observability_layers(svc).audit
        store = _FAILING_STORES[-1]
        seen_at_close: List[Any] = []
        store.on_close = lambda: seen_at_close.append(audit.sink)

        unwire_document_sink(svc)

        assert seen_at_close == [None], "сток обязан быть отцеплен ДО закрытия БД"
        assert store.closed is True
        assert audit.sink is None
        assert getattr(svc, DOCUMENT_SINK_ATTR) is None
        before = store.append_calls
        entry = audit.record("set", origin="switch", key="после-остановки")
        assert store.append_calls == before, "отцепленный сток не имеет права получить запись"
        assert "document_failed" not in entry

    def test_unwire_without_wiring_is_a_no_op(self) -> None:
        unwire_document_sink(_Svc({}))


# ---------------------------------------------------------------------------
# Уборка по такту
# ---------------------------------------------------------------------------


class TestSweepHazards:
    def setup_method(self) -> None:
        _FAILING_STORES.clear()

    def test_failing_purge_does_not_escape_and_does_not_hammer_the_db(self) -> None:
        """Р-8.5-Г + гигиена срока: отказ БД не роняет такт И не превращается в шторм.

        Срок следующей уборки ставится ДО самой уборки. Ставь мы его после — упавшая
        уборка не обновляла бы дедлайн, и каждый heartbeat ходил бы в отказавшую БД:
        сбой стал бы источником нагрузки на то, что уже сломано.
        """
        svc = _Svc({"observability_app": _section(_FACTORY, purge_interval_sec=60.0)})
        wire_document_sink(svc)
        store = _FAILING_STORES[-1]

        assert sweep_process_documents(svc, now=10_000.0) is None
        assert store.purge_calls == 1
        assert svc.warnings and "уборка" in svc.warnings[-1]

        assert sweep_process_documents(svc, now=10_030.0) is None
        assert store.purge_calls == 1, "внутри окна к БД не ходим даже после отказа"

        assert sweep_process_documents(svc, now=10_061.0) is None
        assert store.purge_calls == 2

    def test_process_without_the_plane_is_skipped_cheaply(self) -> None:
        assert sweep_process_documents(_Svc({})) is None

    def test_zero_and_garbage_interval_fall_back_to_the_default(self) -> None:
        """Ноль означает «дефолт», а не «убирать каждый такт».

        Ноль как «каждый такт» превратил бы опечатку в конфиге в постоянный DELETE по
        таблице документов на каждом heartbeat всех восьми процессов.
        """
        for bad in (0, -5, "часто", None):
            _FAILING_STORES.clear()
            svc = _Svc({"observability_app": _section(_FACTORY, purge_interval_sec=bad)})
            wire_document_sink(svc)
            store = _FAILING_STORES[-1]

            sweep_process_documents(svc, now=1000.0)
            sweep_process_documents(svc, now=1000.0 + DEFAULT_PURGE_INTERVAL_SEC - 1)

            assert store.purge_calls == 1, f"purge_interval_sec={bad!r} обязан дать дефолт"
