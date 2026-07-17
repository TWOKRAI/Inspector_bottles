# -*- coding: utf-8 -*-
"""Тесты P1 (backend-control-mcp): introspect.handlers / registers / status.

Инструмент диагностики «что у меня есть» в процессе. Ключевой кейс — воспроизвести
находку Этапа 2: отсутствие приёмника ``register_update`` в router-handlers.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


# ====================================================================== #
#  Фейки                                                                  #
# ====================================================================== #


class _FakeCommandManager:
    """Минимальный CommandManager: хранит хендлеры, диспатчит по 'command'."""

    def __init__(self) -> None:
        self.handlers: dict = {}
        self.meta: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.meta[name] = {"metadata": metadata or {}, "tags": list(tags or [])}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})

    def get_commands(self) -> list:
        return [{"key": k, **self.meta.get(k, {})} for k in self.handlers]


class _FakeMessageDispatcher:
    def __init__(self, keys) -> None:
        self._keys = list(keys)

    def get_all_handlers(self) -> list:
        return [{"key": k} for k in self._keys]


class _FakeRouter:
    def __init__(self, handler_keys) -> None:
        self.event_dispatcher = _FakeMessageDispatcher(handler_keys)


class _FakeWorkerManager:
    def __init__(self, statuses) -> None:
        self._statuses = statuses

    def get_all_workers_status(self) -> dict:
        return self._statuses


class _FakeRouterWithStats(_FakeRouter):
    def __init__(self, handler_keys=(), stats=None) -> None:
        super().__init__(handler_keys)
        self._stats = stats or {}

    def get_stats(self) -> dict:
        return self._stats


class _FakeQueue:
    def __init__(self, size) -> None:
        self._size = size

    def qsize(self) -> int:
        if self._size is None:
            raise NotImplementedError
        return self._size


class _FakeMemoryManager:
    """MemoryManager-совместимый фейк: get_stats() + опц. shm_registry."""

    def __init__(self, stats, shm_registry=None) -> None:
        self._stats = stats
        self.shm_registry = shm_registry

    def get_stats(self) -> dict:
        return self._stats


class _FakeSharedResources:
    """SharedResourcesManager-совместимый фейк: держит _memory_manager."""

    def __init__(self, memory_manager) -> None:
        self._memory_manager = memory_manager


class _FakeShmRegistry:
    def __init__(self, names) -> None:
        self._names = list(names)

    def all_names(self) -> list:
        return list(self._names)


class _FakeOrchestrator:
    def __init__(self, registers_manager) -> None:
        self.registers_manager = registers_manager


class _FakeRegistersManager:
    def __init__(self, dump) -> None:
        self._dump = dump

    def model_dump_all(self) -> dict:
        return self._dump


class _FakeServices:
    """IProcessServices-совместимый фейк для introspect-команд."""

    def __init__(
        self, *, router=None, worker_manager=None, orchestrator=None, queues=None, shared_resources=None
    ) -> None:
        self.command_manager = _FakeCommandManager()
        self.router_manager = router
        self.worker_manager = worker_manager
        self._orchestrator = orchestrator
        self.queues = queues
        self.shared_resources = shared_resources
        self.name = "preprocessor"
        self._current_process_status = "running"

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...


def _make(**kw) -> tuple:
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_introspect_commands()
    return svc, svc.command_manager


# ====================================================================== #
#  Регистрация                                                            #
# ====================================================================== #


class TestRegistration:
    def test_register_adds_three_introspect_commands(self) -> None:
        _svc, cm = _make()
        for key in (
            "introspect.handlers",
            "introspect.registers",
            "introspect.status",
            "introspect.queues",
            "introspect.memory",
            "introspect.capabilities",
            "introspect.plugins",
        ):
            assert key in cm.handlers

    def test_register_skips_without_command_manager(self) -> None:
        svc = _FakeServices()
        svc.command_manager = None
        bc = BuiltinCommands(svc)
        bc._register_introspect_commands()  # не должно падать


# ====================================================================== #
#  introspect.handlers                                                    #
# ====================================================================== #


class TestIntrospectHandlers:
    def test_returns_router_handlers_and_commands(self) -> None:
        router = _FakeRouter(["register_update", "state.changed", "worker.create"])
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.handlers")

        assert result["success"] is True
        assert result["process"] == "preprocessor"
        assert "register_update" in result["router_handlers"]
        assert "state.changed" in result["router_handlers"]
        # commands включает зарегистрированные introspect.* (через _FakeCommandManager)
        assert "introspect.handlers" in result["commands"]
        # отсортировано и без дублей
        assert result["router_handlers"] == sorted(set(result["router_handlers"]))

    def test_reproduces_stage2_missing_register_update(self) -> None:
        # Этап 2: плагин без register_schema → приёмника register_update нет.
        router = _FakeRouter(["state.changed", "worker.create"])
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.handlers")
        assert "register_update" not in result["router_handlers"]  # ← мгновенный диагноз

    def test_empty_when_no_router(self) -> None:
        _svc, cm = _make(router=None)
        result = cm.dispatch("introspect.handlers")
        assert result["success"] is True
        assert result["router_handlers"] == []


# ====================================================================== #
#  introspect.registers                                                   #
# ====================================================================== #


class TestIntrospectRegisters:
    def test_empty_with_note_when_no_orchestrator(self) -> None:
        _svc, cm = _make()
        result = cm.dispatch("introspect.registers")
        assert result["success"] is True
        assert result["registers"] == {}
        assert "note" in result  # диагностично: нет RegistersManager

    def test_returns_model_dump_when_present(self) -> None:
        rm = _FakeRegistersManager({"resize": {"scale_factor": 0.5}})
        orch = _FakeOrchestrator(rm)
        _svc, cm = _make(orchestrator=orch)
        result = cm.dispatch("introspect.registers")
        assert result["success"] is True
        assert result["registers"] == {"resize": {"scale_factor": 0.5}}

    def test_empty_when_orchestrator_without_registers(self) -> None:
        orch = _FakeOrchestrator(None)
        _svc, cm = _make(orchestrator=orch)
        result = cm.dispatch("introspect.registers")
        assert result["registers"] == {}


# ====================================================================== #
#  introspect.status                                                      #
# ====================================================================== #


class TestIntrospectStatus:
    def test_returns_name_status_workers(self) -> None:
        wm = _FakeWorkerManager({"w1": {"status": "running"}, "w2": {"status": "paused"}})
        _svc, cm = _make(worker_manager=wm)
        result = cm.dispatch("introspect.status")
        assert result["success"] is True
        assert result["process"] == "preprocessor"
        assert result["status"] == "running"
        assert set(result["workers"]) == {"w1", "w2"}

    def test_empty_workers_without_worker_manager(self) -> None:
        _svc, cm = _make(worker_manager=None)
        result = cm.dispatch("introspect.status")
        assert result["workers"] == {}

    def test_reports_own_pid(self) -> None:
        """Ф3.7: introspect.status отдаёт реальный OS-pid (os.getpid) для fault-injection."""
        import os

        _svc, cm = _make(worker_manager=None)
        result = cm.dispatch("introspect.status")
        assert result["pid"] == os.getpid()


# ====================================================================== #
#  introspect.capabilities (Ф1 Task 1.9 — контактная книжка v0)           #
# ====================================================================== #


class TestIntrospectCapabilities:
    def test_card_contains_commands_with_descriptions_and_tags(self) -> None:
        _svc, cm = _make()
        result = cm.dispatch("introspect.capabilities")
        assert result["success"] is True
        assert result["process"] == "preprocessor"
        by_name = {c["name"]: c for c in result["commands"]}
        card = by_name["introspect.capabilities"]
        assert "книжк" in card["description"]  # description из metadata регистрации
        assert card["tags"] == ["system"]
        # отсортировано по имени
        assert [c["name"] for c in result["commands"]] == sorted(by_name)

    def test_registers_reduced_to_field_names(self) -> None:
        # Контракт, не значения: {register: {field: value}} → {register: [field]}.
        rm = _FakeRegistersManager({"resize": {"scale_factor": 0.5, "algo": "area"}})
        _svc, cm = _make(orchestrator=_FakeOrchestrator(rm))
        result = cm.dispatch("introspect.capabilities")
        assert result["registers"] == {"resize": ["algo", "scale_factor"]}

    def test_router_handlers_sorted_unique(self) -> None:
        router = _FakeRouter(["state.changed", "heartbeat", "state.changed"])
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.capabilities")
        assert result["router_handlers"] == ["heartbeat", "state.changed"]

    def test_capabilities_extra_hook_merged(self) -> None:
        # PM-хук: dict из svc.capabilities_extra() вливается в карточку.
        svc, cm = _make()
        svc.capabilities_extra = lambda: {
            "processes": {"preprocessor": {"class": "x.Y"}},
            "channels": [{"name": "backend_ctl", "kind": "SocketChannel"}],
        }
        result = cm.dispatch("introspect.capabilities")
        assert result["processes"] == {"preprocessor": {"class": "x.Y"}}
        assert result["channels"][0]["name"] == "backend_ctl"

    def test_no_extra_keys_without_hook(self) -> None:
        _svc, cm = _make()
        result = cm.dispatch("introspect.capabilities")
        assert "processes" not in result
        assert "channels" not in result

    def test_extra_hook_failure_reported(self) -> None:
        svc, cm = _make()

        def _boom() -> dict:
            raise RuntimeError("boom")

        svc.capabilities_extra = _boom
        result = cm.dispatch("introspect.capabilities")
        assert result["success"] is False
        assert "capabilities_extra" in result["reason"]


# ====================================================================== #
#  introspect.router_stats                                                #
# ====================================================================== #


class TestIntrospectRouterStats:
    def test_returns_router_section(self) -> None:
        router = _FakeRouterWithStats(stats={"router": {"sent_ok": 5, "errors": 0, "received": 3}})
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.router_stats")
        assert result["success"] is True
        assert result["router_stats"]["sent_ok"] == 5
        assert result["router_stats"]["received"] == 3

    def test_note_without_router(self) -> None:
        _svc, cm = _make(router=None)
        result = cm.dispatch("introspect.router_stats")
        assert result["success"] is True
        assert result["router_stats"] == {}
        assert "note" in result


# ====================================================================== #
#  introspect.queues                                                      #
# ====================================================================== #


class TestIntrospectQueues:
    def test_reports_queue_sizes(self) -> None:
        queues = {"system": _FakeQueue(2), "data": _FakeQueue(0)}
        _svc, cm = _make(queues=queues)
        result = cm.dispatch("introspect.queues")
        assert result["success"] is True
        assert result["queue_sizes"] == {"system": 2, "data": 0}

    def test_qsize_unavailable_reported_as_none(self) -> None:
        # macOS: qsize() кидает NotImplementedError → None (диагностично).
        queues = {"system": _FakeQueue(None)}
        _svc, cm = _make(queues=queues)
        result = cm.dispatch("introspect.queues")
        assert result["queue_sizes"] == {"system": None}

    def test_empty_without_queues(self) -> None:
        _svc, cm = _make(queues=None)
        result = cm.dispatch("introspect.queues")
        assert result["queue_sizes"] == {}


# ====================================================================== #
#  introspect.memory (Ф2 Task 2.4 — инвентарь памяти/SHM/очередей)        #
# ====================================================================== #


class TestIntrospectMemory:
    """Best-effort инвентарь памяти: недоступная секция → null, не ошибка."""

    def test_all_sections_null_without_subsystems(self) -> None:
        # Процесс без shared_resources/router/queues → success=True, все секции null.
        _svc, cm = _make()
        result = cm.dispatch("introspect.memory")
        assert result["success"] is True
        assert result["process"] == "preprocessor"
        assert result["memory"] is None
        assert result["pool"] is None
        assert result["queues"] is None
        assert result["shm_registry"] is None

    def test_memory_section_from_memory_manager_get_stats(self) -> None:
        mm = _FakeMemoryManager({"created": 3, "errors": 0, "is_owner": True})
        sr = _FakeSharedResources(mm)
        _svc, cm = _make(shared_resources=sr)
        result = cm.dispatch("introspect.memory")
        assert result["success"] is True
        assert result["memory"] == {"created": 3, "errors": 0, "is_owner": True}

    def test_pool_section_from_public_get_stats(self) -> None:
        # F6: pool берётся из ПУБЛИЧНОГО router.get_stats() (frame_loan_pools/frame_slots_*),
        # НЕ из приватного _frame_middlewares. Router без _frame_middlewares → доказывает,
        # что читаем публичный агрегат (иначе секция была бы null).
        router = _FakeRouterWithStats(
            stats={
                "frame_loan_pools": 2,
                "frame_slots_released": 8,
                "frame_slots_reclaimed": 1,
                "frame_loan_exhausted": 2,
            }
        )
        assert not hasattr(router, "_frame_middlewares"), "фейк не должен иметь приватного атрибута"
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.memory")
        assert result["pool"] == {
            "loan_pools": 2,
            "slots_released": 8,
            "slots_reclaimed": 1,
            "loan_exhausted": 2,
        }

    def test_pool_null_when_no_loan_pools(self) -> None:
        # get_stats есть, но loan-протокол не активен (frame_loan_pools=0) → секция null.
        router = _FakeRouterWithStats(stats={"frame_loan_pools": 0, "frame_slots_released": 0})
        _svc, cm = _make(router=router)
        result = cm.dispatch("introspect.memory")
        assert result["pool"] is None

    def test_queues_section_mirrors_introspect_queues(self) -> None:
        queues = {"system": _FakeQueue(2), "data": _FakeQueue(0)}
        _svc, cm = _make(queues=queues)
        result = cm.dispatch("introspect.memory")
        assert result["queues"] == {"system": 2, "data": 0}

    def test_shm_registry_from_registry_when_present(self) -> None:
        mm = _FakeMemoryManager({"created": 1}, shm_registry=_FakeShmRegistry(["shm_a", "shm_b"]))
        sr = _FakeSharedResources(mm)
        _svc, cm = _make(shared_resources=sr)
        result = cm.dispatch("introspect.memory")
        assert result["shm_registry"] == {"names": ["shm_a", "shm_b"], "count": 2}

    def test_all_sections_filled_together(self) -> None:
        mm = _FakeMemoryManager({"created": 7}, shm_registry=_FakeShmRegistry(["shm_x"]))
        sr = _FakeSharedResources(mm)
        router = _FakeRouterWithStats(stats={"frame_loan_pools": 1, "frame_slots_released": 4})
        queues = {"system": _FakeQueue(1)}
        _svc, cm = _make(shared_resources=sr, router=router, queues=queues)
        result = cm.dispatch("introspect.memory")
        assert result["success"] is True
        assert result["memory"] == {"created": 7}
        assert result["pool"]["slots_released"] == 4
        assert result["queues"] == {"system": 1}
        assert result["shm_registry"]["count"] == 1


# ====================================================================== #
#  introspect.plugins (Ф2.3)                                              #
# ====================================================================== #


class TestIntrospectPlugins:
    """Каталог плагинов + failed_imports — «куда делся мой плагин»."""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )

        PluginRegistry.clear()
        yield
        PluginRegistry.clear()

    def test_reports_registered_and_failed(self) -> None:
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )

        class _DummyPlugin:
            pass

        PluginRegistry.register("dummy", _DummyPlugin, category="testing")
        # Инъекция отказа импорта (как после discover со сломанным модулем)
        PluginRegistry._failed_imports["pkg.broken.plugin"] = "SyntaxError: опечатка"

        _svc, cm = _make()
        result = cm.dispatch("introspect.plugins")
        assert result["success"] is True
        assert result["process"] == "preprocessor"
        assert result["plugins"] == {"dummy": "testing"}
        assert result["count"] == 1
        assert result["failed_imports"] == {"pkg.broken.plugin": "SyntaxError: опечатка"}

    def test_empty_registry_is_valid_answer(self) -> None:
        _svc, cm = _make()
        result = cm.dispatch("introspect.plugins")
        assert result["success"] is True
        assert result["plugins"] == {}
        assert result["count"] == 0
        assert result["failed_imports"] == {}
