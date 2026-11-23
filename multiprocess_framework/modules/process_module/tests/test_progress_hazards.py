# -*- coding: utf-8 -*-
"""Task 1.3b (system-run-state) — hazard-тесты автора: ``ProgressTracker``.

Слепой набор (``test_progress.py``) задаёт контракт; здесь — края: доля каждого шага не убывает (отступивший шаг
не занижает последующий рост), ``nan``, сумма весов выше 100, ``advance`` не ставит ``done`` на 100 %, повторный
``finish``, ``label`` приводится к ``str``. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import pytest

from ..progress import ProgressTracker, progress_path


@pytest.mark.timeout(60)
def test_step_fraction_never_shrinks_so_later_growth_is_counted_from_best() -> None:
    """a: 0.8 -> 40, отступ 0.2 -> 40, затем 0.9 -> 45 (доля шага a держится на лучшем 0.8, а не на 0.2)."""
    t = ProgressTracker([("a", 50), ("b", 50)])
    assert t.advance("a", 0.8)["percent"] == 40
    assert t.advance("a", 0.2)["percent"] == 40
    assert t.advance("a", 0.9)["percent"] == 45


@pytest.mark.timeout(60)
def test_nan_fraction_counts_as_zero_and_sum_over_hundred_is_clamped() -> None:
    """``nan`` -> 0 (процент не меняется); веса в сумме 120 при полных долях дают 100, не 120."""
    t = ProgressTracker([("a", 60), ("b", 60)])
    assert t.advance("a", float("nan"))["percent"] == 0
    assert t.advance("a")["percent"] == 60
    assert t.advance("b")["percent"] == 100


@pytest.mark.timeout(60)
def test_advance_to_hundred_is_not_done_and_finish_twice_is_stable() -> None:
    """100 % через ``advance`` — ещё не ``done``; ``finish`` дважды: оба раза 100/done, метка — переданная."""
    t = ProgressTracker([("a", 100)])
    leaf = t.advance("a")
    assert (leaf["percent"], leaf["done"]) == (100, False)
    first = t.finish("итог")
    second = t.finish("итог 2")
    assert (first["percent"], first["done"], first["label"]) == (100, True, "итог")
    assert (second["percent"], second["done"], second["label"]) == (100, True, "итог 2")


@pytest.mark.timeout(60)
def test_progress_path_joins_root_and_id() -> None:
    """Путь листа — корень и идентификатор через точку."""
    assert progress_path("recipe_load") == "system.progress.recipe_load"
