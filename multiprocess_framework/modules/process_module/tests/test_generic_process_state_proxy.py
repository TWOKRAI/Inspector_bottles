# -*- coding: utf-8 -*-
"""Task 2.0 / ADR-PM-049 — hazard-тесты АВТОРА на StateProxy у GenericProcess.

Дополняют независимую приёмку (``test_generic_process_state_proxy_acceptance.py``),
не заменяют её. Что может сломаться в ЭТОМ механизме:

* порядок: обработчик ``state.changed`` обязан стоять в реестре dispatcher'а ДО
  старта message_processor (шаг 7), иначе ранняя дельта уходит в пустоту;
* двойная регистрация: свой прокси, попавший в ``self.state_proxy``, шаг 10
  (``_init_state_proxy``) регистрирует второй раз — дубликат проигрывает МОЛЧА,
  поэтому считаются вызовы регистрации в dispatcher, а не лог;
* приоритет конструкторного прокси: свой второй не заводится;
* слот логгера: ``logger_manager``, не процесс (Task Т.1 — иначе записи немые);
* порядок останова: ``proxy.shutdown()`` до базового shutdown, пока роутер жив;
* без router_manager — прокси нет и исключения нет;
* store-less режим (приложение вернуло ``state_bootstrap → {}``): прокси есть,
  ``get`` отдаёт default, процесс живёт — ТЕКУЩЕЕ поведение, пиновка ADR-PM-049.

Сборка процесса — как в приёмке: настоящий RouterManager, фейковый только
транспортный сток очередей, без спавна.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess


class _FakeQueueRegistry:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        self.sent.append((target, qtype, msg))
        return True

    def register_process_queues(self, *_a: object, **_kw: object) -> None:
        """No-op."""


class _InjectedProxy:
    """Конструкторный прокси: достаточно того, что читают процесс и оркестратор."""

    def __init__(self) -> None:
        self.shutdown_calls = 0

    def on_state_changed(self, msg: dict) -> None:  # pragma: no cover — не вызывается
        pass

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _make_process(name: str, *, state_proxy: Any = None) -> tuple[GenericProcess, _FakeQueueRegistry]:
    proc = GenericProcess(name=name, config={"config": {"plugins": []}}, state_proxy=state_proxy)
    fake_qr = _FakeQueueRegistry()

    def _init_queues_stub() -> None:
        proc.queues = {}
        proc.queue_registry = fake_qr
        proc.memory_manager = None

    proc._init_queues = _init_queues_stub  # type: ignore[method-assign]
    return proc, fake_qr


def _count_state_changed_registrations(proc: GenericProcess) -> list[bool]:
    """Обернуть ``register_handler`` dispatcher'а роутера, как только роутер появится.

    Возвращает список результатов регистраций ключа ``state.changed`` (True — принята,
    False — дубликат отвергнут). Обёртка ставится после шага 4 (_init_communication),
    т.е. до шага 6, где регистрирует GenericProcess.
    """
    results: list[bool] = []
    original_comm = proc._init_communication

    def _comm_then_wrap() -> Any:
        out = original_comm()
        dispatcher = proc.router_manager.event_dispatcher
        original_register = dispatcher.register_handler

        def _register(*args: Any, **kwargs: Any) -> bool:
            ok = original_register(*args, **kwargs)
            key = kwargs.get("key", args[0] if args else None)
            if key == "state.changed":
                results.append(ok)
            return ok

        dispatcher.register_handler = _register  # type: ignore[method-assign]
        return out

    proc._init_communication = _comm_then_wrap  # type: ignore[method-assign]
    return results


def _registered_handler(proc: GenericProcess) -> Any:
    from multiprocess_framework.modules.dispatch_module import DispatchStrategy

    storage = proc.router_manager.event_dispatcher._handlers_storage[DispatchStrategy.EXACT_MATCH]
    info = storage.get("state.changed")
    return None if info is None else info.handler


class TestOwnProxyRegistration:
    def test_handler_is_in_registry_before_message_processor_starts(self) -> None:
        proc, _ = _make_process("hz_order")
        seen_at_step7: dict[str, Any] = {}
        original_sys = proc._init_system_threads

        def _sys_threads() -> Any:
            seen_at_step7["handler"] = _registered_handler(proc)
            return original_sys()

        proc._init_system_threads = _sys_threads  # type: ignore[method-assign]
        try:
            assert proc.initialize() is True
            assert proc._state_proxy is not None
            assert seen_at_step7["handler"] == proc._state_proxy.on_state_changed, (
                "state.changed не в реестре к старту message_processor (шаг 7)"
            )
        finally:
            proc.shutdown()

    def test_own_proxy_registers_exactly_once_and_is_not_public(self) -> None:
        proc, _ = _make_process("hz_once")
        registrations = _count_state_changed_registrations(proc)
        try:
            assert proc.initialize() is True
            assert registrations == [True], f"ожидалась одна принятая регистрация, было {registrations}"
            assert proc.state_proxy is None, "свой прокси попал в self.state_proxy → шаг 10 регистрирует второй раз"
            assert _registered_handler(proc) == proc._state_proxy.on_state_changed
        finally:
            proc.shutdown()

    def test_logger_slot_is_logger_manager_not_process(self) -> None:
        proc, _ = _make_process("hz_logger")
        try:
            assert proc.initialize() is True
            assert proc.logger_manager is not None
            assert proc._state_proxy.get_manager("logger") is proc.logger_manager
        finally:
            proc.shutdown()

    def test_process_without_plugins_still_gets_proxy(self) -> None:
        proc, _ = _make_process("hz_noplugins")
        try:
            assert proc.initialize() is True
            assert proc._state_proxy is not None, "heartbeat без прокси не пишет здоровье в дерево"
        finally:
            proc.shutdown()


class TestInjectedProxyWins:
    def test_injected_proxy_used_and_registered_once_by_step_10(self) -> None:
        injected = _InjectedProxy()
        proc, _ = _make_process("hz_di", state_proxy=injected)
        registrations = _count_state_changed_registrations(proc)
        try:
            assert proc.initialize() is True
            assert proc._state_proxy is injected, "при конструкторном прокси заведён свой"
            assert registrations == [True], f"ожидалась одна регистрация (шаг 10), было {registrations}"
            assert _registered_handler(proc) == injected.on_state_changed
        finally:
            proc.shutdown()
        assert injected.shutdown_calls == 1


class TestShutdownOrder:
    def test_proxy_shutdown_runs_before_base_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc, _ = _make_process("hz_stop")
        assert proc.initialize() is True
        order: list[str] = []

        proxy = proc._state_proxy
        original_proxy_shutdown = proxy.shutdown

        def _proxy_shutdown() -> None:
            order.append("proxy")
            original_proxy_shutdown()

        proxy.shutdown = _proxy_shutdown  # type: ignore[method-assign]
        original_base = ProcessModule.shutdown

        def _base_shutdown(self: ProcessModule) -> bool:
            order.append("base")
            return original_base(self)

        monkeypatch.setattr(ProcessModule, "shutdown", _base_shutdown)
        proc.shutdown()
        assert order[:2] == ["proxy", "base"], f"порядок останова: {order}"


class TestEdgeCases:
    def test_no_router_manager_means_no_proxy_and_no_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = GenericProcess(name="hz_norouter", config={"config": {"plugins": []}})
        proc.router_manager = None
        monkeypatch.setattr(ProcessModule, "_init_custom_managers", lambda self: None)
        proc._init_custom_managers()
        assert proc._state_proxy is None

    def test_storeless_mode_get_returns_default_and_process_lives(self) -> None:
        """Store нет (state_bootstrap → {}): на state.get никто не ответит.

        Пиновка ТЕКУЩЕГО поведения (ADR-PM-049), не норма: прокси есть, ``get`` вне
        приёмного потока досиживает таймаут и отдаёт default, процесс не падает.
        """
        proc, fake_qr = _make_process("hz_storeless")
        try:
            assert proc.initialize() is True
            proxy = proc._state_proxy
            assert proxy is not None
            proxy._SYNC_REQUEST_TIMEOUT = 0.2  # без сервера ждать 5 с незачем
            assert proxy.get("sim.belt.encoder", "DEFAULT") == "DEFAULT"
            asked = [m for (_t, _q, m) in fake_qr.sent if isinstance(m, dict) and m.get("command") == "state.get"]
            assert len(asked) == 1, "get не дошёл до IPC-фолбэка — тест не про store-less режим"
            assert proc.router_manager is not None
        finally:
            proc.shutdown()
