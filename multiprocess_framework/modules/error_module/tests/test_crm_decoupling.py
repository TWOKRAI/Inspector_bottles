# -*- coding: utf-8 -*-
"""
RED-тесты Task 5.14 — CRM-развязка ErrorManager + канонизация имени error-гнезда.

Контекст (behavior-preserving рефакторинг семейства менеджеров):
  1. ErrorManager сейчас наследует LoggerManager (IS-A). Целевое состояние —
     оба являются братьями через композицию, с общим предком
     ChannelRoutingManager (общий лог-слой — миксин, Stats его НЕ наследует).
  2. Имя error-гнезда рассинхронизировано: process_managers.register_all()
     регистрирует менеджер ошибок под слотом "errors", тогда как канон
     ObservableMixin._track_error пробует "error" первым ("errors" — только
     fallback). Канон = "error".

Эти тесты фиксируют ЖЕЛАЕМОЕ поведение и должны падать на текущем коде.
_impl не трогаем — только тесты.
"""

from types import SimpleNamespace


from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.channel_routing_module import ChannelRoutingManager
from multiprocess_framework.modules.process_module.managers.process_managers import ProcessManagers
from multiprocess_framework.modules.process_module.types.types import ManagersBundle


def test_error_manager_is_not_subclass_of_logger_manager():
    """ErrorManager — брат LoggerManager через композицию, а не наследник (IS-A запрещено).

    Целевое состояние: общий лог-слой вынесен в миксин, разделяемый
    LoggerManager и ErrorManager (композиция, не наследование). Оба остаются
    потомками общего предка ChannelRoutingManager — это должно быть true и
    сейчас, и после рефакторинга (sanity-часть теста).
    """
    assert not issubclass(ErrorManager, LoggerManager), (
        "ErrorManager не должен наследовать LoggerManager (Task 5.14: композиция вместо IS-A)"
    )
    # Sanity: общий предок сохраняется в обоих направлениях.
    assert issubclass(ErrorManager, ChannelRoutingManager)
    assert issubclass(LoggerManager, ChannelRoutingManager)


def test_error_slot_registered_under_canonical_name():
    """process_managers.register_all() должен регистрировать error-менеджер под "error".

    Канон задан ObservableMixin._track_error (пробует "error" первым, "errors" —
    только legacy-fallback). register_all() сейчас регистрирует под "errors" —
    расхождение имени гнезда с каноном.
    """
    registered: list[tuple[str, object, bool]] = []

    class FakeProcess:
        def register_manager(self, name, manager, enabled=True):
            registered.append((name, manager, enabled))

    fake_process = FakeProcess()

    bundle = ManagersBundle(
        worker=SimpleNamespace(name="worker"),
        logger=SimpleNamespace(name="logger"),
        router=SimpleNamespace(name="router"),
        command=SimpleNamespace(name="command"),
        stats=SimpleNamespace(name="stats"),
        console=SimpleNamespace(name="console"),
        error=SimpleNamespace(name="error"),  # непустой error-менеджер
        config_manager=None,
        console_enabled=False,
    )

    process_managers = ProcessManagers(process=fake_process)
    process_managers.register_all(bundle, fake_process)

    registered_names = [name for name, _manager, _enabled in registered]

    assert "error" in registered_names, (
        f"ожидали каноничное имя слота 'error', зарегистрированные имена: {registered_names}"
    )
    assert "errors" not in registered_names, (
        f"устаревшее имя слота 'errors' не должно регистрироваться, зарегистрированные имена: {registered_names}"
    )
