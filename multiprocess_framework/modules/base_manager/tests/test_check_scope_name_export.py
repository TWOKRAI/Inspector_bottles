# -*- coding: utf-8 -*-
"""Публичный экспорт ``check_scope_name`` с корня ``base_manager`` (Task 1.9m): правило имени записи Scope."""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.base_manager import check_scope_name


def test_valid_name_returned_unchanged() -> None:
    assert check_scope_name("io") == "io"


@pytest.mark.parametrize("bad", ["", "a/b", "x (self)"])
def test_bad_names_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        check_scope_name(bad)


def test_non_str_refused() -> None:
    with pytest.raises(TypeError):
        check_scope_name(5)
