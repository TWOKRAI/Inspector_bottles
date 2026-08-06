# -*- coding: utf-8 -*-
"""Точки DEBUG роутера обязаны быть ОТЛОЖЕННЫМИ (Ф7.1, долг baseline §2.5).

Почему страж читает ИСХОДНИК, а не поведение. Свойство здесь — дисциплина
call-site: ``f``-строка собирается ДО входа в логгер, и никакой гейт внутри её
не снимает. Наблюдаемого следствия у неё нет — при выключенном DEBUG обе формы
дают ноль записей, — поэтому единственный честный способ её сторожить это
смотреть на то, что написано. Иначе первая же правка вернёт ``f""`` и ничего
не покраснеет.

Сэмплинг Ф7.1 снимает объём ПОСЛЕ гейта; эта дисциплина — цену ДО него. Обе
половины нужны, и ни одна не заменяет другую.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

import pytest

ROUTER_MANAGER = Path(__file__).resolve().parents[1] / "core" / "router_manager.py"

#: Сколько точек DEBUG в роутере на момент фиксации. Литерал, а не подсчёт из
#: кода: выражение согласилось бы и с нулём. Число менялось (план говорил 13 —
#: столько было до Ф6.7, переведшей одну точку в WARNING).
EXPECTED_DEBUG_CALLSITES = 12


def _debug_calls() -> List[Tuple[int, ast.AST]]:
    tree = ast.parse(ROUTER_MANAGER.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "_log_debug":
            found.append((node.lineno, node.args[0]))
    return found


def test_every_hot_debug_point_is_deferred_or_constant() -> None:
    """Аргумент — либо лямбда, либо постоянная строка. Третьего быть не должно.

    Постоянная строка законна: собирать в ней нечего, и замыкание было бы
    чистой ценой. Всё остальное (``f``-строка, конкатенация, ``.format``)
    означает сборку на горячем пути при выключенном уровне.
    """
    offenders = [
        lineno
        for lineno, arg in _debug_calls()
        if not isinstance(arg, ast.Lambda) and not isinstance(arg, ast.Constant)
    ]
    assert offenders == [], (
        "точки _log_debug собирают сообщение на call-site (строки: "
        f"{offenders}) — при выключенном DEBUG эта цена платится всё равно"
    )


def test_the_number_of_debug_points_is_the_one_that_was_measured() -> None:
    """Число точек — характеризация: новая точка обязана быть замечена ревью."""
    calls = _debug_calls()
    assert len(calls) == EXPECTED_DEBUG_CALLSITES, (
        f"точек _log_debug стало {len(calls)}, зафиксировано {EXPECTED_DEBUG_CALLSITES} — "
        "число несущее (приёмка Ф7.1 названа поимённо), правится вместе с причиной"
    )


def test_the_guard_can_see_a_violation() -> None:
    """Молчащий детектор ничего не доказывает — показываем его красным.

    Тот же разбор на заведомо нарушающем исходнике обязан найти нарушение.
    Без этого «нарушителей нет» неотличимо от «разбор ничего не находит».
    """
    tree = ast.parse('self._log_debug(f"собрано на месте {x}")\n')
    calls = [
        node.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_log_debug"
    ]
    assert calls and not isinstance(calls[0], (ast.Lambda, ast.Constant))


def test_a_lambda_reading_exc_binds_it_as_a_default_argument() -> None:
    """``exc`` из ``except ... as exc`` обязан связываться дефолт-аргументом.

    Python **удаляет** это имя на выходе из блока ``except``. Замыкание, дожившее
    до вызова за пределами блока, поднимет ``NameError`` — то есть отложенная
    запись убьёт диагностику ровно там, где её и включают: на пути отказа.
    Сегодня спасает синхронность вызова внутри ``log()`` — то есть это мина, а
    не дефект, и сторожим мы именно мину.
    """
    offenders = []
    for lineno, arg in _debug_calls():
        if not isinstance(arg, ast.Lambda):
            continue
        reads_exc = any(isinstance(n, ast.Name) and n.id == "exc" for n in ast.walk(arg.body))
        binds_exc = any(a.arg == "exc" for a in arg.args.args)
        if reads_exc and not binds_exc:
            offenders.append(lineno)
    assert offenders == [], (
        f"лямбды читают `exc` замыканием (строки: {offenders}) — за пределами except-блока "
        "имя уже удалено, нужен `lambda exc=exc:`"
    )


def test_the_trap_is_real_and_the_binding_removes_it() -> None:
    """Механизм показан обеими сторонами: без связывания — падает, со связыванием — нет."""

    def naive():
        try:
            raise ValueError("сбой транспорта")
        except ValueError as exc:  # noqa: F841 — ровно это и демонстрируем
            return lambda: f"{exc!r}"  # noqa: F821 — имя УЖЕ удалено к вызову: в этом и мина

    with pytest.raises(NameError):
        naive()()

    def bound():
        try:
            raise ValueError("сбой транспорта")
        except ValueError as exc:
            return lambda exc=exc: f"{exc!r}"

    assert "ValueError" in bound()()
