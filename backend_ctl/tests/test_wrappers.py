# -*- coding: utf-8 -*-
"""Тесты типизированных обёрток introspect (Ф1 Task 1.2): router_stats/queues/worker_status.

Две группы:
- юнит с инжекцией сырых ответов (форма парсинга, вложенность result, строгий край) —
  быстрые, без запуска системы;
- live против headless-бэкенда (фикстура headless_backend, помечены harness_smoke).

Строгий край проверяется ПАРОЙ на каждую обёртку: ответ с полем → значение и
``missing == []``; тот же ответ с переименованным полем → ``None`` и имя ключа в
``missing``. Одиночное плечо здесь ничего не доказывает: «поле прочиталось» и «поле
подставилось дефолтом» на зелёном тесте выглядят одинаково — различает их только
второе плечо, где поля заведомо нет.
"""

from __future__ import annotations

import pytest

from backend_ctl.driver import MemoryStats, QueueDepths, RouterStats, WorkerStatus
from backend_ctl.protocol import UNWRAP_MISS, unwrap


# Реальная форма ответа команды: внешний конверт success + вложенная payload под result
# (снято с живого бэкенда — см. probe). Парсеры обязаны спускаться по result.
#: Полный набор счётчиков, которые роутер инициализирует при старте и потому
#: обязан отдавать всегда. Фикстура держит их все: обёртка судит форму ответа по
#: ``missing``, поэтому неполная фикстура проверяла бы не тот контракт.
#: Точечные ключи (разбивка по kind) в этот набор НЕ входят — они заводятся на
#: лету и живут в ``by_kind`` (см. _read_breakdown).
def _full_router_stats(**overrides: object) -> dict:
    stats: dict = {
        "sent_ok": 10,
        "received": 21,
        "middleware_dropped": 0,
        "errors": 0,
        "sent_attempted": 10,
        "sent_via_channel": 3,
        "sent_via_targets": 7,
        "queued_async": 0,
        "send_queue_size": 0,
        "queue_data_evicted": 0,
        "queue_system_evict_blocked": 0,
        "frame_loans_released_on_evict": 0,
    }
    stats.update(overrides)
    return stats


#: Имена всех счётчиков строгого края — в порядке чтения из from_response.
_ALL_COUNTERS = [
    "sent_ok",
    "received",
    "middleware_dropped",
    "errors",
    "sent_attempted",
    "sent_via_channel",
    "sent_via_targets",
    "queued_async",
    "send_queue_size",
    "queue_data_evicted",
    "queue_system_evict_blocked",
    "frame_loans_released_on_evict",
]

_ROUTER_RESP = {
    "type": "response",
    "success": True,
    "result": {
        "success": True,
        "process": "preprocessor",
        "router_stats": _full_router_stats(
            **{"sent_via_targets.state": 5, "sent_via_channel.system": 3},
        ),
    },
}

_QUEUES_RESP = {
    "success": True,
    "result": {"success": True, "process": "preprocessor", "queue_sizes": {"system": None, "data": 3}},
}

_STATUS_RESP = {
    "success": True,
    "result": {
        "success": True,
        "process": "preprocessor",
        "status": "running",
        "workers": {"message_processor": {"status": "running", "is_alive": True}},
    },
}


class TestRouterStatsParsing:
    def test_parses_nested_payload(self) -> None:
        rs = RouterStats.from_response(_ROUTER_RESP)
        assert rs.ok is True
        assert (rs.sent_ok, rs.received, rs.middleware_dropped, rs.errors) == (10, 21, 0, 0)
        assert rs.missing == [], "форма полная — пропусков быть не должно"
        assert rs.raw is _ROUTER_RESP  # сырой ответ сохранён целиком

    def test_parses_flat_payload(self) -> None:
        # На случай «плоского» ответа (без внешнего конверта result).
        flat = {"success": True, "router_stats": {"sent_ok": 1, "received": 2}}
        rs = RouterStats.from_response(flat)
        assert rs.ok is True and rs.sent_ok == 1 and rs.received == 2

    def test_renamed_counter_is_missing_not_zero(self) -> None:
        """Второе плечо пары: сервер переименовал счётчик → None + имя в missing.

        Именно этот случай раньше был неотличим от «трафика не было»: ``int(
        stats.get("sent_ok", 0) or 0)`` отдавал ноль, и агент читал его как факт.
        """
        stats = _full_router_stats()
        stats["sent_okay"] = stats.pop("sent_ok")  # сервер переименовал ровно один счётчик
        renamed = {"success": True, "result": {"success": True, "router_stats": stats}}
        rs = RouterStats.from_response(renamed)
        assert rs.ok is True, "ручка ответила успешно — расхождение только в форме"
        assert rs.sent_ok is None, "нет показания ≠ ноль"
        assert rs.missing == ["sent_ok"]
        assert (rs.received, rs.middleware_dropped, rs.errors) == (21, 0, 0), "соседи читаются как раньше"

    def test_zero_stays_zero_and_is_not_missing(self) -> None:
        """Ноль ОТ СЕРВЕРА — валидное показание, а не пропуск (обратная сторона пары)."""
        zeros = {name: 0 for name in _ALL_COUNTERS}
        rs = RouterStats.from_response({"success": True, "router_stats": zeros})
        assert (rs.sent_ok, rs.received, rs.middleware_dropped, rs.errors) == (0, 0, 0, 0)
        assert (rs.sent_attempted, rs.sent_via_channel, rs.sent_via_targets) == (0, 0, 0)
        assert rs.missing == []

    def test_whole_section_absent_marks_every_counter(self) -> None:
        rs = RouterStats.from_response({"success": False, "error": "timeout"})
        assert rs.ok is False
        assert (rs.sent_ok, rs.received, rs.middleware_dropped, rs.errors) == (None, None, None, None)
        assert rs.missing == _ALL_COUNTERS

    def test_non_numeric_value_is_not_a_reading(self) -> None:
        """Значение пришло, но числом не является — показания нет, не ноль."""
        rs = RouterStats.from_response({"success": True, "router_stats": {"sent_ok": "н/д"}})
        assert rs.sent_ok is None and "sent_ok" in rs.missing

    def test_robust_to_garbage(self) -> None:
        rs = RouterStats.from_response(None)  # type: ignore[arg-type]
        assert rs.ok is False and rs.raw == {}
        assert rs.missing == _ALL_COUNTERS

    def test_delivery_doors_are_readable(self) -> None:
        """Новые счётчики читаются — тождество «куда делись отправки» сводится обёрткой.

        Раньше слагаемых в дataclass не было и тождество приходилось сводить
        руками через ``.raw`` — ровно тот признак дырявой обёртки, ради которого
        счётчики и открыты.
        """
        rs = RouterStats.from_response(_ROUTER_RESP)
        assert rs.sent_attempted == 10
        assert (rs.sent_via_channel, rs.sent_via_targets) == (3, 7)
        assert (rs.queued_async, rs.send_queue_size) == (0, 0)
        assert (rs.queue_data_evicted, rs.queue_system_evict_blocked) == (0, 0)
        assert rs.frame_loans_released_on_evict == 0
        assert rs.missing == []
        assert rs.sent_attempted == rs.sent_via_channel + rs.sent_via_targets

    def test_kind_breakdown_goes_to_by_kind_not_missing(self) -> None:
        """Точечные ключи — в by_kind; их отсутствие НЕ считается расхождением формы.

        Разбивка по kind заводится на лету (состав зависит от топологии), поэтому
        рецепт без state-трафика не должен давать ложную пропажу в ``missing``.
        """
        rs = RouterStats.from_response(_ROUTER_RESP)
        assert rs.by_kind == {"sent_via_targets.state": 5, "sent_via_channel.system": 3}
        assert all("." not in name for name in rs.missing)

        without_breakdown = {"success": True, "router_stats": _full_router_stats()}
        rs2 = RouterStats.from_response(without_breakdown)
        assert rs2.by_kind == {}
        assert rs2.missing == [], "нет разбивки — это не пропажа, а отсутствие такого трафика"


class TestQueueDepthsParsing:
    def test_parses_sizes_with_none(self) -> None:
        q = QueueDepths.from_response(_QUEUES_RESP)
        assert q.ok is True
        assert q.sizes == {"system": None, "data": 3}
        assert q.missing == []

    def test_renamed_section_is_missing_not_empty(self) -> None:
        """Второе плечо: секция названа иначе → sizes=None + missing, а не «очередей нет»."""
        renamed = {"success": True, "result": {"success": True, "queue_depths": {"data": 3}}}
        q = QueueDepths.from_response(renamed)
        assert q.sizes is None, "пустой словарь здесь солгал бы про отсутствие очередей"
        assert q.missing == ["queue_sizes"]

    def test_empty_sizes_is_an_answer_not_a_gap(self) -> None:
        """Пустой словарь ОТ СЕРВЕРА — валидный ответ «очередей нет»."""
        q = QueueDepths.from_response({"success": True, "result": {"success": True, "queue_sizes": {}}})
        assert q.sizes == {} and q.missing == []

    def test_absent_section_on_empty_response(self) -> None:
        q = QueueDepths.from_response({"success": True, "result": {"success": True}})
        assert q.sizes is None and q.missing == ["queue_sizes"]


_MEMORY_RESP = {
    "success": True,
    "result": {
        "success": True,
        "process": "preprocessor",
        "memory": {"created": 3, "errors": 0, "is_owner": True},
        "pool": {"loan_pools": 1, "slots_released": 5, "slots_reclaimed": 0, "loan_exhausted": 2},
        "queues": {"system": 0, "data": 2},
        "shm_registry": None,
    },
}


class TestMemoryStatsParsing:
    def test_parses_nested_sections(self) -> None:
        m = MemoryStats.from_response(_MEMORY_RESP)
        assert m.ok is True
        assert m.memory == {"created": 3, "errors": 0, "is_owner": True}
        assert m.pool["slots_released"] == 5
        assert m.queues == {"system": 0, "data": 2}
        assert m.shm_registry is None  # null-секция сохраняется как None
        assert m.missing == [], "все четыре секции присутствуют — пропусков нет"
        assert m.raw is _MEMORY_RESP  # сырой ответ сохранён целиком

    def test_explicit_null_section_is_an_answer(self) -> None:
        """Первое плечо: явный ``null`` — это ОТВЕТ «подсистема недоступна».

        Контракт introspect.memory best-effort, поэтому null-секция штатна и в
        ``missing`` попадать не должна — иначе аномалией станет норма.
        """
        bare = {"success": True, "result": {"success": True, "memory": None, "pool": None, "queues": None}}
        m = MemoryStats.from_response(bare)
        assert m.ok is True
        assert (m.memory, m.pool, m.queues) == (None, None, None)
        assert m.missing == ["shm_registry"], "отсутствующая секция — да, явный null — нет"

    def test_renamed_section_lands_in_missing(self) -> None:
        """Второе плечо: секцию переименовали → None и имя в missing."""
        renamed = {
            "success": True,
            "result": {"success": True, "mem": {}, "pool": {}, "queues": {}, "shm_registry": {}},
        }
        m = MemoryStats.from_response(renamed)
        assert m.memory is None and m.missing == ["memory"]
        assert m.pool == {} and m.queues == {}

    def test_defaults_on_error(self) -> None:
        m = MemoryStats.from_response({"success": False, "error": "timeout"})
        assert m.ok is False
        assert (m.memory, m.pool, m.queues, m.shm_registry) == (None, None, None, None)
        assert m.missing == ["memory", "pool", "queues", "shm_registry"]

    def test_robust_to_garbage(self) -> None:
        m = MemoryStats.from_response(None)  # type: ignore[arg-type]
        assert m.ok is False and m.raw == {}
        assert m.missing == ["memory", "pool", "queues", "shm_registry"]


class TestWorkerStatusParsing:
    def test_parses_process_and_workers(self) -> None:
        ws = WorkerStatus.from_response(_STATUS_RESP)
        assert ws.ok is True
        assert ws.process == "preprocessor"
        assert ws.status == "running"
        assert "message_processor" in ws.workers
        assert ws.missing == []

    def test_renamed_workers_section_is_missing(self) -> None:
        """Второе плечо: секцию воркеров переименовали → None, а не «воркеров нет»."""
        renamed = {
            "success": True,
            "result": {"success": True, "process": "preprocessor", "status": "running", "threads": {}},
        }
        ws = WorkerStatus.from_response(renamed)
        assert ws.workers is None and ws.missing == ["workers"]
        assert ws.process == "preprocessor" and ws.status == "running"

    def test_empty_workers_is_an_answer(self) -> None:
        ws = WorkerStatus.from_response({"success": True, "process": "p", "status": "running", "workers": {}})
        assert ws.workers == {} and ws.missing == []

    def test_defaults_on_empty(self) -> None:
        ws = WorkerStatus.from_response({"success": False})
        assert ws.ok is False and ws.process is None and ws.workers is None
        assert ws.missing == ["process", "status", "workers"]


class TestUnwrapMiss:
    """``unwrap`` в keys-режиме: ключей нет → служебный признак, а не молчание."""

    def test_marks_miss_without_mutating_caller_dict(self) -> None:
        res = {"success": True, "result": {"success": True, "queue_depths": {}}}
        payload = unwrap(res, "queue_sizes")
        assert payload[UNWRAP_MISS] == ["queue_sizes"]
        assert UNWRAP_MISS not in res, "входной dict вызывающего мутировать нельзя"
        assert UNWRAP_MISS not in res["result"]

    def test_found_payload_has_no_marker(self) -> None:
        res = {"success": True, "result": {"success": True, "queue_sizes": {"data": 1}}}
        payload = unwrap(res, "queue_sizes")
        assert payload["queue_sizes"] == {"data": 1}
        assert UNWRAP_MISS not in payload

    def test_non_dict_response_reports_miss(self) -> None:
        assert unwrap(None, "router_stats") == {UNWRAP_MISS: ["router_stats"]}

    def test_leaf_mode_untouched(self) -> None:
        """leaf-режим признака не несёт: там «спуск до листа», а не поиск ключей."""
        assert unwrap({"success": True, "result": {"applied": 2}}, leaf=True) == {"applied": 2}


# ---------------------------------------------------------------------------
# Live против headless-бэкенда (acceptance 1.2: каждый метод — тест против бэкенда)
# ---------------------------------------------------------------------------


@pytest.mark.harness_smoke
class TestWrappersLive:
    _PROC = "preprocessor"

    def test_router_stats_live(self, headless_backend) -> None:
        rs = headless_backend.router_stats(self._PROC, timeout=8.0)
        assert isinstance(rs, RouterStats)
        assert rs.ok is True
        # счётчики неотрицательны, форма заполнена реальными числами
        assert rs.sent_ok >= 0 and rs.received >= 0
        assert "router_stats" in str(rs.raw)

    def test_router_stats_shape_matches_live_server(self, headless_backend) -> None:
        """Форма ответа сверена ДЕЛОМ, а не додумана по исходникам.

        ``missing == []`` на живом ProcessManager — единственное доказательство,
        что имена счётчиков в обёртке совпадают с тем, что публикует роутер. Без
        него строгий край гарантировал бы честность разбора выдуманной формы.
        """
        rs = headless_backend.router_stats("ProcessManager", timeout=8.0)
        assert rs.ok is True
        assert rs.missing == [], f"имена счётчиков разошлись с сервером: {rs.missing}"
        assert None not in (rs.sent_ok, rs.received, rs.middleware_dropped, rs.errors)

    def test_queues_live(self, headless_backend) -> None:
        q = headless_backend.queues(self._PROC, timeout=8.0)
        assert isinstance(q, QueueDepths)
        assert q.ok is True
        assert q.missing == []
        # ключи очередей есть (значения могут быть None на macOS — qsize недоступен)
        assert set(q.sizes.keys()) >= {"system", "data"}

    def test_worker_status_live(self, headless_backend) -> None:
        ws = headless_backend.worker_status(self._PROC, timeout=8.0)
        assert isinstance(ws, WorkerStatus)
        assert ws.ok is True
        assert ws.missing == []
        assert ws.process == self._PROC
        assert ws.status == "running"
        # у процесса есть защищённый message_processor
        assert "message_processor" in ws.workers
