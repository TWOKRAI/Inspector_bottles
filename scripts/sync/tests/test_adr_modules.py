"""Тесты для scripts/sync/adr_modules.py.

Проверяют:
- Парсинг заголовка с суффиксом '(was ADR-NNN)'.
- Обнаружение дублирующегося ADR-кода в двух модулях.
- Ошибку при модуле, не зарегистрированном в MODULE_LAYERS.
- Детерминированность render_index.
- Форматирование статуса для 1/2/3 ADR (_format_status).
"""
from __future__ import annotations

import pytest

from scripts.sync.adr_modules import (
    AdrEntry,
    ModuleAdrs,
    _format_status,
    render_index,
    scan_module,
    validate_all,
)


# ---------------------------------------------------------------------------
# Тест 1: парсинг с суффиксом (was ADR-...)
# ---------------------------------------------------------------------------


def test_scan_with_was_suffix(tmp_path):
    """Заголовок '## ADR-CHN-001 (was ADR-114): Title' парсится корректно."""
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Решения\n\n"
        "## ADR-CHN-001 (was ADR-114): Some Title\n\n"
        "- Статус: принято\n",
        encoding="utf-8",
    )

    result = scan_module(decisions)

    assert result.code == "CHN", f"Ожидался код CHN, получен '{result.code}'"
    assert len(result.adrs) == 1, f"Ожидался 1 ADR, получено {len(result.adrs)}"
    assert result.adrs[0].num == 1, f"Ожидался номер 1, получен {result.adrs[0].num}"
    assert result.adrs[0].title == "Some Title", (
        f"Ожидался заголовок 'Some Title', получен '{result.adrs[0].title}'"
    )


# ---------------------------------------------------------------------------
# Тест 2: два модуля с одинаковым кодом → ValueError
# ---------------------------------------------------------------------------


def test_detect_duplicate_code(tmp_path):
    """Два модуля с одинаковым кодом → ValueError с понятным сообщением."""
    mod_a = ModuleAdrs(
        module_name="module_a",
        code="CM",
        adrs=[AdrEntry(num=1, title="First")],
    )
    mod_b = ModuleAdrs(
        module_name="module_b",
        code="CM",
        adrs=[AdrEntry(num=1, title="Second")],
    )

    with pytest.raises(ValueError) as exc_info:
        validate_all(
            [mod_a, mod_b],
            module_layers=[("module_a", "Layer"), ("module_b", "Layer")],
            modules_without_local_adr=set(),
        )

    msg = str(exc_info.value)
    assert "CM" in msg, "Сообщение должно содержать дублирующийся код CM"
    assert "module_a" in msg or "module_b" in msg, (
        "Сообщение должно содержать имена конфликтующих модулей"
    )


# ---------------------------------------------------------------------------
# Тест 3: модуль не в MODULE_LAYERS и не в MODULES_WITHOUT_LOCAL_ADR → ValueError
# ---------------------------------------------------------------------------


def test_detect_missing_in_layers(tmp_path):
    """Модуль не в MODULE_LAYERS и не в MODULES_WITHOUT_LOCAL_ADR → ValueError с подсказкой."""
    orphan = ModuleAdrs(
        module_name="orphan_module",
        code="XX",
        adrs=[AdrEntry(num=1, title="Title")],
    )

    with pytest.raises(ValueError) as exc_info:
        validate_all(
            [orphan],
            module_layers=[],
            modules_without_local_adr=set(),
        )

    msg = str(exc_info.value)
    assert "_adr_layers.py" in msg, (
        "Сообщение должно содержать подсказку '_adr_layers.py'"
    )


# ---------------------------------------------------------------------------
# Тест 4: render_index детерминирован
# ---------------------------------------------------------------------------


def test_render_index_deterministic():
    """Два вызова render_index с одним входом → идентичный вывод."""
    modules = [
        ModuleAdrs(
            module_name="state_store_module",
            code="SS",
            adrs=[AdrEntry(num=1, title="T1"), AdrEntry(num=2, title="T2")],
        ),
        ModuleAdrs(
            module_name="config_module",
            code="CFG",
            adrs=[AdrEntry(num=1, title="C1")],
        ),
    ]
    layers = [
        ("state_store_module", "Resources & Config"),
        ("config_module", "Resources & Config"),
    ]

    result1 = render_index(modules, module_layers=layers)
    result2 = render_index(modules, module_layers=layers)

    assert result1 == result2, "render_index должен давать идентичный результат при одинаковых входах"


# ---------------------------------------------------------------------------
# Тест 5: _format_status для 1/2/3 ADR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "adrs, code, expected_fragment",
    [
        (
            [AdrEntry(num=1, title="T1")],
            "XX",
            "ADR-XX-001",
        ),
        (
            [AdrEntry(num=1, title="T1"), AdrEntry(num=2, title="T2")],
            "XX",
            "ADR-XX-001",
        ),
        (
            [AdrEntry(num=1, title="T1"), AdrEntry(num=2, title="T2"), AdrEntry(num=3, title="T3")],
            "XX",
            "ADR-XX-001",
        ),
    ],
    ids=["1_adr", "2_adrs", "3_adrs"],
)
def test_format_status_variants(adrs, code, expected_fragment):
    """Формат статуса для 1/2/3 ADR содержит ожидаемые фрагменты."""
    result = _format_status(adrs, code)

    assert expected_fragment in result, (
        f"Ожидался фрагмент '{expected_fragment}' в '{result}'"
    )

    if len(adrs) == 1:
        # 1 ADR: "ADR-XX-001 (T1)"
        assert "T1" in result, "Заголовок T1 должен быть в статусе"
    elif len(adrs) == 2:
        # 2 ADR: "ADR-XX-001…002 (T1, T2)"
        assert "T1" in result, "Первый заголовок T1 должен быть в статусе"
        assert "T2" in result, "Второй заголовок T2 должен быть в статусе"
        assert "…" in result, "Диапазон должен содержать символ '…'"
    else:
        # 3+ ADR: "ADR-XX-001…003 (T1, ..., T3)"
        assert "T1" in result, "Первый заголовок T1 должен быть в статусе"
        assert "T3" in result, "Последний заголовок T3 должен быть в статусе"
        assert "..." in result, "Должно быть многоточие '...' для 3+ ADR"
