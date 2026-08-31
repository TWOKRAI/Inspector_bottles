# -*- coding: utf-8 -*-
"""Task Т.1 — проводка логгера в StateStoreManager, поднятый оркестратором.

Тест АВТОРА на опасность конкретной сшивки (не замена независимому набору).

Опасность: ``_setup_state_store`` отдаёт объект в СЛОТ ``logger``
``ObservableMixin``, а слот вызывается КАНОНИЧНЫМ протоколом
``debug/info/warning/error/critical``. Сам оркестратор такого протокола не
несёт — у него только ``log_*``-алиасы. Пока в слот подавался ``self``, каждая
запись ``StateStoreManager`` исчезала; до Т.1 — ещё и молча.

Тест поставлен так, чтобы краснеть от ОБОИХ возвратов:
  * вернуть ``logger=self`` — запись не доедет до кольца, и счётчик
    ``manager_call_failures`` вырастет (проверяется обоими утверждениями);
  * убрать сшивку вовсе (``logger=None``) — записи в кольце тоже нет.

Проверка «доехало» — чтением РЕАЛЬНОГО кольца ``LoggerManager``, а не фактом
вызова метода на подставном объекте: подставной согласился бы с чем угодно.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp
from multiprocess_framework.modules.state_store_module.testing.in_memory_router import (
    InMemoryRouter,
)


@pytest.fixture()
def logger_manager(tmp_path):
    """Настоящий LoggerManager с кольцом в памяти — читаемый приёмник."""
    from multiprocess_framework.modules.logger_module.configs import (
        LoggerChannelSchema,
        LoggerManagerConfig,
        LoggerScopeSchema,
    )
    from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

    scopes = ("SYSTEM", "BUSINESS", "PERFORMANCE", "DEBUG")
    manager = LoggerManager(
        config=LoggerManagerConfig(
            app_name="t1_state_store",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={"ring": LoggerChannelSchema(type="memory", enabled=True, capacity=200)},
            default_level="DEBUG",
            scopes={name: LoggerScopeSchema(channels=["ring"]) for name in scopes},
        )
    )
    yield manager
    manager.shutdown()


@pytest.fixture()
def orchestrator(logger_manager):
    """Оркестратор без multiprocessing-init — только поля для _setup_state_store.

    ``logger_manager`` выставляется явно: у настоящего объекта его ставит
    ``ProcessModule.__init__`` (``None``) и переприсваивает ``_init_managers``
    (шаг 3 initialize), а ``__new__`` оба шага обходит.

    Teardown гасит StateStoreManager: его DeltaDispatcher поднимает поток
    коалесцирования, и сторож потоков в ``modules/conftest.py`` справедливо
    краснеет на утечке.
    """
    orch = GenericProcessManagerApp.__new__(GenericProcessManagerApp)
    orch.name = "ProcessManager"
    orch.config = {"initial_state": {"cameras": {}}}
    orch.config_handler = None
    orch.router_manager = InMemoryRouter()
    orch.command_manager = None
    orch.logger_manager = logger_manager
    orch._state_store_manager = None
    try:
        yield orch
    finally:
        if orch._state_store_manager is not None:
            orch._state_store_manager.shutdown()


class TestStateStoreGetsACanonicalLogger:
    def test_logger_slot_holds_an_object_with_the_canonical_protocol(self, orchestrator) -> None:
        """Самая дешёвая половина: в слоте объект НУЖНОГО протокола.

        Именно это ломается при возврате ``logger=self`` — оркестратор
        каноничных имён не несёт.
        """
        orch = orchestrator

        orch._setup_state_store()

        slot = orch._state_store_manager.get_manager("logger")
        missing = [n for n in ("debug", "info", "warning", "error", "critical") if not callable(getattr(slot, n, None))]
        assert not missing, f"в слоте logger объект без каноничного протокола, нет: {missing}"

    def test_state_store_warning_actually_reaches_the_ring(self, orchestrator, logger_manager) -> None:
        """Вторая половина: запись ДОЕЗЖАЕТ до приёмника, а не «менеджер есть»."""
        orch = orchestrator
        orch._setup_state_store()

        orch._state_store_manager._log_warning("проводка Т.1 жива")

        records = logger_manager.read_sink_tail("ring")["records"]
        assert any("проводка Т.1 жива" in r.get("message", "") for r in records), (
            f"запись StateStoreManager не доехала до кольца: {records!r}"
        )

    def test_no_swallowed_calls_are_counted(self, orchestrator) -> None:
        """Контроль-сторож (Т.1): счётчик проглоченных отказов пуст.

        Без него тест выше прошёл бы и на «частично правильной» проводке, где
        часть уровней доезжает, а часть теряется.
        """
        orch = orchestrator
        orch._setup_state_store()

        for emit in ("_log_debug", "_log_info", "_log_warning", "_log_error", "_log_critical"):
            getattr(orch._state_store_manager, emit)("проверка уровня")

        assert orch._state_store_manager.manager_call_failures == {}, (
            f"часть уровней потерялась: {orch._state_store_manager.manager_call_failures!r}"
        )
