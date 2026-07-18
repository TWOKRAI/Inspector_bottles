# -*- coding: utf-8 -*-
"""Контракт-тесты Protocol-интерфейсов backend_ctl (C.2).

Гарантируют, что реальные реализации удовлетворяют объявленным контрактам —
forcing-функция против дрейфа при распиле driver.py (Phase C): если из
BackendDriver/реестра уедет метод контракта, тест покраснеет.
"""

from __future__ import annotations

from backend_ctl.driver import BackendDriver
from backend_ctl.interfaces import IBackendClient, IEventSource, ISubscriptionRegistry
from backend_ctl.subscriptions import _SubscriptionRegistry


def test_backend_driver_satisfies_client_and_event_source() -> None:
    d = BackendDriver()
    assert isinstance(d, IBackendClient)
    assert isinstance(d, IEventSource)


def test_subscription_registry_satisfies_contract() -> None:
    assert isinstance(_SubscriptionRegistry(), ISubscriptionRegistry)
