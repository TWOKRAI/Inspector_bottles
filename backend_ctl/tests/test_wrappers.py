# -*- coding: utf-8 -*-
"""Тесты типизированных обёрток introspect (Ф1 Task 1.2): router_stats/queues/worker_status.

Две группы:
- юнит с инжекцией сырых ответов (форма парсинга, вложенность result, дефолты) — быстрые,
  без запуска системы;
- live против headless-бэкенда (фикстура headless_backend, помечены harness_smoke).
"""

from __future__ import annotations

import pytest

from backend_ctl.driver import MemoryStats, QueueDepths, RouterStats, WorkerStatus

# Реальная форма ответа команды: внешний конверт success + вложенная payload под result
# (снято с живого бэкенда — см. probe). Парсеры обязаны спускаться по result.
_ROUTER_RESP = {
    "type": "response",
    "success": True,
    "result": {
        "success": True,
        "process": "preprocessor",
        "router_stats": {
            "sent_ok": 10,
            "received": 21,
            "middleware_dropped": 0,
            "errors": 0,
            "sent_attempted": 10,
        },
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
        assert rs.raw is _ROUTER_RESP  # сырой ответ сохранён целиком

    def test_parses_flat_payload(self) -> None:
        # На случай «плоского» ответа (без внешнего конверта result).
        flat = {"success": True, "router_stats": {"sent_ok": 1, "received": 2}}
        rs = RouterStats.from_response(flat)
        assert rs.ok is True and rs.sent_ok == 1 and rs.received == 2

    def test_defaults_on_empty(self) -> None:
        rs = RouterStats.from_response({"success": False, "error": "timeout"})
        assert rs.ok is False
        assert (rs.sent_ok, rs.received, rs.middleware_dropped, rs.errors) == (0, 0, 0, 0)

    def test_robust_to_garbage(self) -> None:
        rs = RouterStats.from_response(None)  # type: ignore[arg-type]
        assert rs.ok is False and rs.raw == {}


class TestQueueDepthsParsing:
    def test_parses_sizes_with_none(self) -> None:
        q = QueueDepths.from_response(_QUEUES_RESP)
        assert q.ok is True
        assert q.sizes == {"system": None, "data": 3}

    def test_defaults_on_empty(self) -> None:
        q = QueueDepths.from_response({"success": True, "result": {"success": True}})
        assert q.sizes == {}


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
        assert m.raw is _MEMORY_RESP  # сырой ответ сохранён целиком

    def test_null_sections_on_bare_process(self) -> None:
        # Процесс без shared_resources: все секции null, но success=True.
        bare = {"success": True, "result": {"success": True, "memory": None, "pool": None, "queues": None}}
        m = MemoryStats.from_response(bare)
        assert m.ok is True
        assert (m.memory, m.pool, m.queues, m.shm_registry) == (None, None, None, None)

    def test_defaults_on_error(self) -> None:
        m = MemoryStats.from_response({"success": False, "error": "timeout"})
        assert m.ok is False
        assert (m.memory, m.pool, m.queues, m.shm_registry) == (None, None, None, None)

    def test_robust_to_garbage(self) -> None:
        m = MemoryStats.from_response(None)  # type: ignore[arg-type]
        assert m.ok is False and m.raw == {}


class TestWorkerStatusParsing:
    def test_parses_process_and_workers(self) -> None:
        ws = WorkerStatus.from_response(_STATUS_RESP)
        assert ws.ok is True
        assert ws.process == "preprocessor"
        assert ws.status == "running"
        assert "message_processor" in ws.workers

    def test_defaults_on_empty(self) -> None:
        ws = WorkerStatus.from_response({"success": False})
        assert ws.ok is False and ws.process is None and ws.workers == {}


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

    def test_queues_live(self, headless_backend) -> None:
        q = headless_backend.queues(self._PROC, timeout=8.0)
        assert isinstance(q, QueueDepths)
        assert q.ok is True
        # ключи очередей есть (значения могут быть None на macOS — qsize недоступен)
        assert set(q.sizes.keys()) >= {"system", "data"}

    def test_worker_status_live(self, headless_backend) -> None:
        ws = headless_backend.worker_status(self._PROC, timeout=8.0)
        assert isinstance(ws, WorkerStatus)
        assert ws.ok is True
        assert ws.process == self._PROC
        assert ws.status == "running"
        # у процесса есть защищённый message_processor
        assert "message_processor" in ws.workers
