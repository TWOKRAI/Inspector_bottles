"""Тесты для scripts/sync/adr_obsolete.py.

Проверяют:
- render_obsolete: ADR с is_obsolete=True попадает в вывод с правильным форматом.
- render_obsolete: отсутствие superseded_by → '*(устарело)*'; наличие → '*(Суперсед: **ADR-NNN**)*'.
"""
from __future__ import annotations

import pytest

from scripts.sync.adr_obsolete import render_obsolete
from scripts.sync.adr_toc import GlobalAdr


# ---------------------------------------------------------------------------
# Тест 1: устаревший ADR попадает в вывод
# ---------------------------------------------------------------------------


def test_obsolete_included(tmp_path):
    """ADR с is_obsolete=True попадает в render_obsolete вывод с правильным форматом."""
    adrs = [
        GlobalAdr(num=99, title="X", is_obsolete=True, superseded_by=100),
    ]

    result = render_obsolete(adrs)

    assert "**ADR-099**" in result, (
        f"Ожидался '**ADR-099**' в выводе, получен: '{result}'"
    )
    assert "X" in result, "Заголовок 'X' должен быть в выводе"
    assert "Суперсед: **ADR-100**" in result, (
        f"Ожидалась строка 'Суперсед: **ADR-100**' в выводе, получен: '{result}'"
    )


# ---------------------------------------------------------------------------
# Тест 2: форматы '*(устарело)*' и '*(Суперсед: **ADR-NNN**)*'
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "superseded_by, expected_suffix",
    [
        (None, "*(устарело)*"),
        (200, "*(Суперсед: **ADR-200**)"),
    ],
    ids=["without_superseded", "with_superseded"],
)
def test_superseded_parsed(tmp_path, superseded_by, expected_suffix):
    """Без superseded_by → '*(устарело)*'; с superseded_by → '*(Суперсед: **ADR-NNN**)*'."""
    adrs = [
        GlobalAdr(num=50, title="Тест", is_obsolete=True, superseded_by=superseded_by),
    ]

    result = render_obsolete(adrs)

    assert expected_suffix in result, (
        f"Ожидался суффикс '{expected_suffix}' в выводе, получен: '{result}'"
    )
