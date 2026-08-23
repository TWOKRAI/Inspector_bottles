# -*- coding: utf-8 -*-
"""Task Т.1 — порядок шагов initialize(), на который опирается проводка логгера.

Тест АВТОРА на опасность ПОРЯДКА (не замена независимому набору).

Три места отдают ``self.logger_manager`` в слот ``logger`` создаваемого
компонента вместо ``self``:
  * ``GenericProcessApp._init_custom_managers`` → ``StateProxy``;
  * ``GuiProcess._init_application_threads``   → ``GuiStateProxy``;
  * ``PluginOrchestrator._build_registers_manager`` (зовётся из
    ``_init_custom_managers``) → ``RegistersManager``.

Все три читают атрибут, который присваивает ``_init_managers`` — шаг 3
``ProcessModule.initialize()``. Если шаг 3 когда-нибудь уедет ПОСЛЕ шага 6,
в слот поедет ``None``: записи снова исчезнут, и на этот раз даже не будут
посчитаны (``None`` в слоте — законный допуск ``_call_manager``, тишина по
построению). Именно эту ловушку и стережёт файл.

Оракул — не чтение исходника: ``initialize()`` реально выполняется с
подменёнными шагами-регистраторами, порядок берётся из фактических вызовов.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.plugins.interfaces import IProcessServices
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

#: Шаги initialize(), которые подменяются регистраторами.
_STEPS = (
    "_init_configuration",
    "_init_queues",
    "_init_managers",
    "_init_communication",
    "_register_process_state",
    "_init_custom_managers",
    "_init_application_threads",
    "_init_system_threads",
    "_init_state_proxy",
)

#: Шаги, которым нужен уже присвоенный ``logger_manager``.
_CONSUMERS = ("_init_custom_managers", "_init_application_threads", "_init_state_proxy")


def _run_initialize_recording_order() -> tuple[list[str], list[str]]:
    """Прогнать ``ProcessModule.initialize()`` с шагами-регистраторами.

    Returns:
        (порядок вызванных шагов, тексты ошибок из _log_error)
    """
    proc = ProcessModule.__new__(ProcessModule)
    proc.name = "ordering_probe"
    order: list[str] = []
    errors: list[str] = []

    for step in _STEPS:
        setattr(proc, step, lambda _s=step: order.append(_s))
    proc.update_process_state = lambda **_kw: None
    proc.get_manager = lambda _name: None
    proc._log_info = lambda *_a, **_kw: None
    proc._log_error = lambda msg, *_a, **_kw: errors.append(str(msg))

    assert proc.initialize() is True, f"initialize() не дошёл до конца: {errors}"
    return order, errors


class TestManagersAreReadyBeforeComponentsAreWired:
    def test_init_managers_runs_before_every_consumer_step(self) -> None:
        order, errors = _run_initialize_recording_order()

        assert "_init_managers" in order, f"шаг создания менеджеров не выполнился: {order} / {errors}"
        managers_at = order.index("_init_managers")
        for consumer in _CONSUMERS:
            assert consumer in order, f"шаг '{consumer}' не выполнился: {order}"
            assert managers_at < order.index(consumer), (
                f"'{consumer}' выполняется ДО '_init_managers' — logger_manager там ещё None, "
                f"и слот logger получил бы тишину без счётчика. Порядок: {order}"
            )

    def test_the_oracle_is_not_vacuous(self) -> None:
        """Сторож против «ноль наблюдений выглядит как результат»: если бы
        ни один шаг не записался, тест выше прошёл бы на пустом множестве."""
        order, _errors = _run_initialize_recording_order()
        assert set(_STEPS) <= set(order), f"часть шагов вообще не вызвана: {sorted(set(_STEPS) - set(order))}"


class TestLoggerManagerIsADeclaredPort:
    """``PluginOrchestrator`` читает ``services.logger_manager`` — значит порт
    обязан быть в контракте, иначе дорога есть в коде и отсутствует в протоколе
    (тот же довод, что у ``document_sink`` и ``stats_manager``)."""

    def test_the_protocol_declares_logger_manager(self) -> None:
        members = {name for name in dir(IProcessServices) if not name.startswith("_")}
        assert "logger_manager" in members

    def test_the_mock_carries_the_attribute_so_it_still_satisfies_the_protocol(self) -> None:
        services: Any = MockProcessServices()
        assert hasattr(services, "logger_manager")
        assert isinstance(services, IProcessServices)

    def test_a_bare_process_always_has_the_attribute(self) -> None:
        """``ProcessModule.__init__`` ставит ``logger_manager`` всегда (None до
        initialize) — объявление порта без атрибута ломало бы dev-проверку."""
        proc = ProcessModule(name="port_probe", config={})
        assert proc.logger_manager is None
        assert isinstance(proc, IProcessServices)
