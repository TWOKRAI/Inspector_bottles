"""Слепые приёмочные тесты Task 1.2b-3 для прототипа: ``FullReplacePlanner`` и 5 классов на ``ProcessModule``.

G-26: класс разрешается на шаблон ``BaseManager.shutdown`` (свой ``shutdown`` снят, свой ``_on_shutdown`` есть).
G-27: запись жизни (Р7 (в)) — ``__dict__`` на экземпляре, ``scope is None``, области независимы. Зелёный и до правки.
G-28: тело останова выполняется один раз через шаблон, область закрывается один раз.

Ожидаемые значения — литералы гарантий. Вызовы ``shutdown()`` идут в daemon-потоке со сроком.
"""

from __future__ import annotations

import importlib
import threading
import time

import pytest

from multiprocess_framework.modules.base_manager import BaseManager

DEADLINE_S = 15.0

# G-26: литеральный список 6 классов прототипа (инвентарь брифа).
PROTOTYPE_6 = [
    "multiprocess_prototype.backend.assembly.planner.FullReplacePlanner",
    "multiprocess_prototype.frontend.process.GuiProcess",
    "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess",
    "multiprocess_prototype.frontend.bridge_process.BridgeGuiProcess",
    "multiprocess_prototype.generic_process_app.GenericProcessApp",
    "multiprocess_prototype.orchestrator.ProcessManagerProcessApp",
]
# Переименован один: планировщик (``shutdown`` -> ``_on_shutdown``); пять других — на ``ProcessModule``.
RENAMED = {"FullReplacePlanner"}
OWN = PROTOTYPE_6


def _short(dotted: str) -> str:
    return dotted.rpartition(".")[2]


def _load(dotted: str) -> type:
    module_name, _, class_name = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), class_name)


def call_bounded(fn, timeout_s: float):
    """Вызвать ``fn`` в daemon-потоке; вернуть (завершился, результат, ошибка, длительность)."""
    box: dict = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            box["error"] = exc
        box["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=run, daemon=True, name="call_bounded")
    th.start()
    th.join(timeout_s)
    return (not th.is_alive()), box.get("result"), box.get("error"), box.get("elapsed")


class FakeScope:
    """Подделка ``IScope``: считает вызовы ``close()``."""

    def __init__(self, path: str = "fake/scope") -> None:
        self.path = path
        self.closed = False
        self.close_calls = 0

    def close(self, budget_s=None, *, deadline=None):
        self.close_calls += 1
        self.closed = True
        return None


# ---------------------------------------------------------------------------
# G-26
# ---------------------------------------------------------------------------


def test_inventory_literal_has_six() -> None:
    """G-26: литеральный список — 6 различных классов прототипа (инвентарь брифа)."""
    assert len(PROTOTYPE_6) == 6
    assert len(set(PROTOTYPE_6)) == 6


@pytest.mark.parametrize("dotted", OWN, ids=_short)
def test_resolves_to_template(dotted: str) -> None:
    """G-26: нет своего ``shutdown``, разрешение на шаблон; у переименованных есть ``_on_shutdown``."""
    cls = _load(dotted)
    assert issubclass(cls, BaseManager)
    assert "shutdown" not in vars(cls), f"{cls.__name__}: свой shutdown остался"
    assert cls.shutdown is BaseManager.shutdown, f"{cls.__name__}.shutdown не шаблон"
    if cls.__name__ in RENAMED:
        assert "_on_shutdown" in vars(cls), f"{cls.__name__}: нет своего _on_shutdown"


# ---------------------------------------------------------------------------
# G-27 (Р7 (в)): запись жизни в __dict__, зелёный и до правки
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dotted", OWN, ids=_short)
def test_record_in_dict_independent(dotted: str) -> None:
    """G-27: ``cls.__new__(cls)`` дважды: ``__dict__`` есть, ``scope is None``, подделки областей независимы."""
    cls = _load(dotted)
    obj = cls.__new__(cls)
    twin = cls.__new__(cls)
    assert isinstance(obj.__dict__, dict)
    assert isinstance(twin.__dict__, dict)
    assert obj.scope is None
    assert twin.scope is None
    fake_a = FakeScope(f"fake/{cls.__name__}/a")
    fake_b = FakeScope(f"fake/{cls.__name__}/b")
    obj.attach_scope(fake_a)
    assert twin.scope is None, "области двух экземпляров не должны совпадать"
    twin.attach_scope(fake_b)
    assert obj.scope is fake_a
    assert twin.scope is fake_b


# ---------------------------------------------------------------------------
# G-28: тело один раз через шаблон
# ---------------------------------------------------------------------------


def test_double_shutdown_runs_body_once_and_closes_scope() -> None:
    """G-28: два ``shutdown()`` -> оба ``True``, ``close()`` области 1, шпион на ``_on_shutdown`` 1."""
    from multiprocess_prototype.backend.assembly.planner import FullReplacePlanner

    obj = FullReplacePlanner(lambda desired: {}, lambda: set(), lambda: set())
    scope = FakeScope("fake/FullReplacePlanner")
    spy_calls: list[int] = []
    assert obj.initialize() is True
    obj.attach_scope(scope)
    original = obj._on_shutdown

    def spy() -> bool:
        spy_calls.append(1)
        return original()

    obj._on_shutdown = spy  # экземплярный шпион, оборачивает исходный метод

    first = call_bounded(obj.shutdown, DEADLINE_S)
    second = call_bounded(obj.shutdown, DEADLINE_S)
    assert first[0] and second[0], "shutdown() завис"
    assert first[2] is None, repr(first[2])
    assert second[2] is None, repr(second[2])
    assert first[1] is True
    assert second[1] is True
    assert scope.close_calls == 1, f"close() области: {scope.close_calls} вместо 1"
    assert spy_calls == [1], f"тело _on_shutdown вызвано {len(spy_calls)} раз вместо 1"
