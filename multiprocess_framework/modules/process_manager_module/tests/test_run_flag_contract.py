# -*- coding: utf-8 -*-
"""Task 1.10 (system-run-state) — контрактные тесты ``RunFlag`` (критерий 6).

Контракт: ``RunFlag(initial: bool = False)``; ``set()``/``clear()`` идемпотентны и возвращают ``None``;
``is_set()`` возвращает настоящий ``bool``; конструктор принимает ``bool`` позиционно и по имени ``initial``.
Ожидания — литералы.
"""

from __future__ import annotations

import pytest

from ..core.run_flag import RunFlag


@pytest.mark.parametrize("initial", [True, False])
def test_constructor_accepts_bool_positionally(initial: bool) -> None:
    assert RunFlag(initial).is_set() is initial


@pytest.mark.parametrize("initial", [True, False])
def test_constructor_accepts_bool_by_keyword_initial(initial: bool) -> None:
    assert RunFlag(initial=initial).is_set() is initial


def test_set_is_idempotent_from_clear_state() -> None:
    flag = RunFlag(False)
    flag.set()
    first = flag.is_set()
    flag.set()
    flag.set()
    assert (first, flag.is_set()) == (True, True)


def test_set_is_idempotent_from_set_state() -> None:
    flag = RunFlag(True)
    flag.set()
    assert flag.is_set() is True


def test_clear_is_idempotent_from_set_state() -> None:
    flag = RunFlag(True)
    flag.clear()
    first = flag.is_set()
    flag.clear()
    flag.clear()
    assert (first, flag.is_set()) == (False, False)


def test_clear_is_idempotent_from_clear_state() -> None:
    flag = RunFlag(False)
    flag.clear()
    assert flag.is_set() is False


@pytest.mark.parametrize("initial", [True, False])
def test_set_returns_none(initial: bool) -> None:
    assert RunFlag(initial).set() is None


@pytest.mark.parametrize("initial", [True, False])
def test_clear_returns_none(initial: bool) -> None:
    assert RunFlag(initial).clear() is None


@pytest.mark.parametrize("initial", [True, False])
def test_is_set_returns_exact_bool_type(initial: bool) -> None:
    flag = RunFlag(initial)
    assert type(flag.is_set()) is bool
    flag.set()
    assert type(flag.is_set()) is bool
    flag.clear()
    assert type(flag.is_set()) is bool


def test_default_constructor_equals_explicit_false() -> None:
    assert RunFlag().is_set() is RunFlag(False).is_set()
