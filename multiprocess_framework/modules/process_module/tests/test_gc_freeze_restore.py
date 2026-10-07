# -*- coding: utf-8 -*-
"""Помощник ``freeze_restored`` (conftest пакета): тест возвращает заморозку gc, а не размораживает кучу.

Всё на настоящих ``gc.freeze``/``gc.unfreeze``, без дублёров. Каждый тест обёрнут внешним
``freeze_restore_block()``: свою заморозку тест возвращает тем же помощником, что проверяет, и
сессионную кучу pytest не размораживает. Проверка — по счётчику ``gc.get_freeze_count()`` и по
присутствию объекта в поколениях 0..2 (``gc.get_objects()`` permanent-поколение не перечисляет),
не по времени.
"""

from __future__ import annotations

import gc

import pytest

from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import collection_owner


def _tracked(obj) -> bool:
    """``obj`` в поколениях 0..2 (то есть НЕ заморожен)."""
    return any(o is obj for o in gc.get_objects())


def _make_cyclic_garbage(n: int) -> None:
    """``n`` недостижимых циклов: собрать их может только gc."""
    for _ in range(n):
        a: list = []
        a.append(a)


def _assert_freeze_count_near(n0: int) -> None:
    """Счётчик заморозки вернулся к базе ``n0``: допуск 100 объектов в ОБЕ стороны.

    Вниз счётчик тянет смерть по refcount: замороженный объект, умерший в блоке, вычитается из
    ``gc.get_freeze_count()`` без всякого ``gc.unfreeze()`` (Linux CI, CPython 3.12: дельта -6;
    50 вложенных списков и внешний — ровно -51). Вверх — объекты, рождённые в блоке и живые к
    повторной заморозке. Свойство «мусор блока не заморожен» допуск не прячет: 10 000
    замороженных циклов дали бы дельту около +10 000.
    """
    delta = gc.get_freeze_count() - n0
    assert abs(delta) < 100, f"дельта счётчика заморозки {delta}"


def test_restore_returns_freeze_count_to_baseline(freeze_restore_block):
    with freeze_restore_block():
        gc.freeze()  # «сессионная заморозка» — база помощника
        n0 = gc.get_freeze_count()
        assert n0 > 0
        with freeze_restore_block():
            _make_cyclic_garbage(10_000)  # мусор теста: в permanent попасть не должен
            gc.unfreeze()  # то, что делал teardown тестов gc до правки
            assert gc.get_freeze_count() == 0
        # база вернулась; мусор блока собран collect(1), а не заморожен
        _assert_freeze_count_near(n0)


def test_restore_tolerates_frozen_objects_dying_by_refcount(freeze_restore_block):
    """Замороженные объекты, умершие по refcount в блоке, уводят счётчик ниже базы — это не провал.

    Падение CI на Linux: 669835 - 669841 = -6 при нижней границе 0. Здесь тот же дрейф задан явно.
    """
    with freeze_restore_block():
        doomed = [[] for _ in range(50)]  # 51 объект: внешний список и 50 вложенных
        gc.freeze()
        n0 = gc.get_freeze_count()
        with freeze_restore_block():
            del doomed  # умирают по refcount, будучи замороженными
            # предпосылка: CPython вычел умерших из счётчика (между del и проверкой нет freeze)
            assert gc.get_freeze_count() - n0 <= -51
            _make_cyclic_garbage(10_000)
            gc.unfreeze()
        # дельта около -51: граница «0 <=» дала бы здесь ложный провал
        _assert_freeze_count_near(n0)


def test_restore_does_not_unfreeze_session_heap(freeze_restore_block):
    with freeze_restore_block():
        session_obj = [[]]  # объект «сессионной кучи»
        gc.freeze()
        assert _tracked(session_obj) is False
        with freeze_restore_block():
            gc.unfreeze()
            assert _tracked(session_obj) is True  # unfreeze глобален: объект в старшем поколении
            gc.freeze()  # тест сам морозит — как freeze_after_startup
        assert _tracked(session_obj) is False  # после блока снова permanent


def test_restore_without_baseline_freeze_only_unfreezes(freeze_restore_block):
    with freeze_restore_block():
        # Искусственное состояние: на практике счётчик не ноль (старт интерпретатора уже даёт
        # permanent-объекты, в сессии морозит граница). Ветку n0 == 0 проверяет только этот тест.
        gc.unfreeze()
        assert gc.get_freeze_count() == 0
        with freeze_restore_block():
            gc.freeze()
            assert gc.get_freeze_count() > 0
        assert gc.get_freeze_count() == 0  # прежнее поведение: unfreeze без refreeze


def test_restore_runs_when_block_raises(freeze_restore_block):
    with freeze_restore_block():
        session_obj = [[]]
        gc.freeze()
        with pytest.raises(RuntimeError, match="тело упало"):
            with freeze_restore_block():
                gc.unfreeze()
                raise RuntimeError("тело упало")
        assert _tracked(session_obj) is False


def test_restore_collects_only_young_generations(freeze_restore_block):
    """Выход помощника — без полной сборки: полная и есть та пауза 170–280 мс, которую он убирает."""
    gens: list[int] = []

    def on_gc(phase: str, info: dict) -> None:
        if phase == "start":
            gens.append(info["generation"])

    with freeze_restore_block():
        gc.freeze()
        try:
            with freeze_restore_block():
                gc.unfreeze()  # счётчик изменился → путь восстановления
                gc.callbacks.append(on_gc)
        finally:
            if on_gc in gc.callbacks:
                gc.callbacks.remove(on_gc)
    assert gens == [1]


def test_slot_block_restores_freeze_after_live_owner_suspend_exit(slot_suspended_block):
    """Живой сессионный владелец морозил → выход suspend сам зовёт gc.unfreeze(); связка возвращает заморозку.

    Обратная вложенность (возврат заморозки ВНУТРИ suspend) оставляет кучу размороженной.
    """
    owner = collection_owner()
    assert owner is not None  # владелец сессии из корневого conftest
    sentinel = [[]]
    owner.collect(full=True, refreeze=True)  # как граница теста: полная сборка + gc.freeze()
    assert _tracked(sentinel) is False
    with slot_suspended_block():
        pass
    assert _tracked(sentinel) is False
    assert gc.get_freeze_count() > 0
