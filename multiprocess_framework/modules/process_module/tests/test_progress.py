# -*- coding: utf-8 -*-
"""Task 1.3b (system-run-state) — слепой набор: ``ProgressTracker`` и путь листа прогресса.

Контракт (из брифа): ``process_module/progress.py`` — ``PROGRESS_ROOT = "system.progress"``,
``progress_path(id) -> "system.progress.<id>"``, ``ProgressTracker(steps: list[tuple[str, int]])`` (имя шага,
вес в процентах, сумма 100), ``advance(step, fraction=1.0, *, label="") -> dict``, ``finish(label="") -> dict``.
Лист — dict с литеральными ключами ``percent`` (int 0..100), ``label`` (str), ``done`` (bool), ``updated_at``
(float), pickle-safe. Процент монотонный, ``fraction`` вне 0..1 обрезается, неизвестный шаг — ``ValueError``
без значения шага в тексте, ``finish`` даёт 100 и ``done=True``.

Красные на ImportError (модуля ещё нет) — ожидаемо. Ожидаемые значения — литералы.

Решения тестера (ASSUMPTION — см. отчёт 1.3b.tester.md):
  * «значение шага» в тексте ошибки = переданная строка шага (и переданная доля); тест ищет их подстроками;
  * после ``ValueError`` трекер остаётся рабочим (состояние не испорчено);
  * ``advance`` не ставит ``done=True`` даже на 100 — это делает только ``finish``.
"""

from __future__ import annotations

import pickle

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ..progress import PROGRESS_ROOT, ProgressTracker, progress_path

STEPS = [("a", 30), ("b", 70)]


@pytest.mark.timeout(60)
def test_percent_is_monotonic() -> None:
    """Процент не убывает; ``fraction`` вне 0..1 обрезается; литералы и свойство на случайных последовательностях."""
    t = ProgressTracker(STEPS)
    assert t.advance("a", -3.0)["percent"] == 0  # доля < 0 обрезана до 0
    assert t.advance("a")["percent"] == 30  # доля по умолчанию 1.0: шаг a целиком
    assert t.advance("b", 0.5)["percent"] == 65  # 30 + 70 * 0.5
    assert t.advance("b", 0.1)["percent"] == 65  # доля шага отступила — процент не откатился
    assert t.advance("a", 0.2)["percent"] == 65  # возврат к уже пройденному шагу — тоже
    assert t.advance("b", 7.5)["percent"] == 100  # доля > 1 обрезана до 1

    @settings(max_examples=200, deadline=None)
    @given(st.lists(st.tuples(st.sampled_from(["a", "b"]), st.floats(min_value=-5, max_value=5, allow_nan=False))))
    def prop(moves: list[tuple[str, float]]) -> None:
        tracker = ProgressTracker(STEPS)
        seen = [tracker.advance(step, fraction)["percent"] for step, fraction in moves]
        assert all(0 <= p <= 100 for p in seen), seen
        assert seen == sorted(seen), seen

    prop()


@pytest.mark.timeout(60)
def test_finish_gives_hundred_and_done() -> None:
    """``finish`` даёт 100 и ``done=True`` с переданным label; до него ``done`` ложь, даже на неполном проценте."""
    t = ProgressTracker(STEPS)
    mid = t.advance("a", 0.5, label="идёт")
    assert (mid["percent"], mid["done"], mid["label"]) == (15, False, "идёт")  # 30 * 0.5
    end = t.finish("готово")
    assert (end["percent"], end["done"], end["label"]) == (100, True, "готово")
    # finish на свежем трекере (ни одного шага) — то же
    fresh = ProgressTracker(STEPS).finish()
    assert (fresh["percent"], fresh["done"], fresh["label"]) == (100, True, "")


@pytest.mark.timeout(60)
def test_unknown_step_raises_without_value() -> None:
    """Неизвестный шаг -> ``ValueError``; переданные значения (имя шага, доля) в тексте не светятся; трекер цел."""
    t = ProgressTracker(STEPS)
    with pytest.raises(ValueError) as info:
        t.advance("секрет-шаг-zz9", 0.4242, label="метка")
    text = str(info.value)
    assert "секрет-шаг-zz9" not in text, text
    assert "0.4242" not in text, text
    assert t.advance("a")["percent"] == 30  # провал не испортил состояние


@pytest.mark.timeout(60)
def test_leaf_is_pickle_safe_dict_with_literal_keys() -> None:
    """Лист — обычный dict с ровно четырьмя литеральными ключами и их типами; pickle-круг без потерь; путь листа."""
    assert PROGRESS_ROOT == "system.progress"
    assert progress_path("boot") == "system.progress.boot"
    t = ProgressTracker(STEPS)
    for leaf in (t.advance("a", 0.5, label="x"), t.finish("y")):
        assert type(leaf) is dict
        assert set(leaf) == {"percent", "label", "done", "updated_at"}, leaf
        assert type(leaf["percent"]) is int and 0 <= leaf["percent"] <= 100
        assert type(leaf["label"]) is str
        assert type(leaf["done"]) is bool
        assert type(leaf["updated_at"]) is float
        assert pickle.loads(pickle.dumps(leaf)) == leaf
