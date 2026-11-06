# -*- coding: utf-8 -*-
"""Task 1.13, ревью (minor 1): нехешируемый id дисплея в файле даёт RecipeValidationError, а не TypeError.

Файл фикстуры A с ``- id: [main]`` (список вместо строки) в top-level ``displays``; Save редактора
с корректной топологией обязан отказать типизированным ``RecipeValidationError``.
Обвязка — из ``test_save_display_refs_blind.py`` (blind-файл не правится).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_prototype.recipes.tests.test_save_display_refs_blind import _SLUG, _chain, _fixture_topology, _save
from multiprocess_prototype.recipes.tests.test_save_noise_store import fixture_a_lf


def test_unhashable_display_id_in_file_raises_validation_error(tmp_path: Path) -> None:
    """``- id: [main]`` в файле: RecipeValidationError (не TypeError), байты файла прежние."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    src = fixture_a_lf()
    assert src.count(b"\n  - id: main\n") == 1
    broken = src.replace(b"\n  - id: main\n", b"\n  - id: [main]\n")
    store, path, session = _chain(tmp_path, broken)

    with pytest.raises(RecipeValidationError):
        _save(store, _fixture_topology(), session.base_rev_for(_SLUG))

    assert path.read_bytes() == broken
