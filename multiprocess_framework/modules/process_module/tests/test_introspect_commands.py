# -*- coding: utf-8 -*-
"""Тесты P1 (backend-control-mcp): introspect.handlers / registers / status.

Инструмент диагностики «что у меня есть» в процессе. Ключевой кейс — воспроизвести
находку Этапа 2: отсутствие приёмника ``register_update`` в router-handlers.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


# ====================================================================== #
#  Фейки                                                                  #
# ====================================================================== #


class _FakeCommandManager:
    """Минимальный CommandManager: хранит хендлеры, диспатчит по 'command'."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})

    def get_commands(self) -> list:
        return [{"key": k} for k in self.handlers]


class _FakeMessageDispatcher:
    def __init__(self, keys) -> None:
        self._keys = list(keys)

    def get_all_handlers(self) -> list:
        return [{"key": k} for k in self._keys]


class _FakeRouter:
    def __init__(self, handler_keys) -> None:
        self.message_dispatcher = _FakeMessageDispatcher(handler_keys)


class _FakeWorkerManager:
    def __init__(self, statuses) -> None:
        self._statuses = statuses

    def get_all_workers_status(self) -> dict:
        return self._statuses


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

    def __init__(self, *, router=None, worker_manager=None, orchestrator=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.router_manager = router
        self.worker_manager = worker_manager
        self._orchestrator = orchestrator
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
        for key in ("introspect.handlers", "introspect.registers", "introspect.status"):
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
