"""Тест обратной совместимости: 24 оригинальные переменные темы.

Проверяет, что дефолтные значения оригинальных переменных
не изменились после расширения схемы до 152+ переменных.

Оригинальные переменные — те, что существовали до Task 1.1 (design_tokens_system).
Фактические значения взяты из текущего schemas.py (не из истории git),
так как схема уже мигрирована и эти значения зафиксированы как «правильные».
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.registers.theme.schemas import (
    ThemeVariables,
    get_default_variables,
)

# ---------------------------------------------------------------------------
# Эталонные дефолты 24 оригинальных переменных
# Значения взяты напрямую из schemas.py (ThemeVariables) — единственный источник истины.
# ---------------------------------------------------------------------------
ORIGINAL_VARS: list[tuple[str, str]] = [
    # --- Фон (4 переменные) ---
    ("bg_deep",    "#1a1f28"),
    ("bg_mid",     "#2d3440"),
    ("bg_hi",      "#4a5362"),
    ("bg_hi2",     "#5c6573"),
    # --- Поверхности (4 переменные) ---
    ("surf_0",     "#3a414e"),
    ("surf_1",     "#5a6370"),
    ("surf_2",     "#6e7886"),
    ("surf_deep",  "#252a33"),
    # --- Серебро (3 переменные) ---
    ("silver_hi",  "#c8ccd4"),
    ("silver",     "#9ea6b2"),
    ("silver_lo",  "#6a7280"),
    # --- Текст (4 переменные) ---
    ("text_0",     "#f2f5fa"),
    ("text_1",     "#c0c7d2"),
    ("text_2",     "#8a93a1"),
    ("text_3",     "#5e6674"),
    # --- Акцент (4 переменные) ---
    ("accent",      "#2b7fff"),
    ("accent_hi",   "#4a95ff"),
    ("accent_lo",   "#1f5fcc"),
    ("accent_deep", "#153f8a"),
    # --- Семантика (3 переменные) ---
    ("danger",  "#e54863"),
    ("success", "#2ecc8f"),
    ("warn",    "#f0a23a"),
    # --- Шрифты (2 переменные) ---
    ("font_family",      "Rajdhani"),
    ("font_family_mono", "JetBrains Mono"),
]


class TestOriginalVarsDefaults:
    """Параметризованные тесты дефолтных значений 24 оригинальных переменных."""

    @pytest.mark.parametrize("var_name, expected", ORIGINAL_VARS)
    def test_theme_variables_default(self, var_name: str, expected: str) -> None:
        """ThemeVariables() должен иметь точные дефолты для каждой оригинальной переменной."""
        tv = ThemeVariables()
        actual = getattr(tv, var_name)
        assert actual == expected, (
            f"Дефолт переменной '{var_name}' изменился: "
            f"ожидается '{expected}', получено '{actual}'"
        )

    def test_get_default_variables_contains_all_original_keys(self) -> None:
        """get_default_variables() должен содержать все 24 оригинальные ключа."""
        defaults = get_default_variables()
        original_keys = [var_name for var_name, _ in ORIGINAL_VARS]

        missing = [key for key in original_keys if key not in defaults]
        assert not missing, (
            f"get_default_variables() не содержит оригинальные ключи: {missing}"
        )

    def test_original_vars_count(self) -> None:
        """Список ORIGINAL_VARS содержит ровно 24 переменные."""
        assert len(ORIGINAL_VARS) == 24, (
            f"Ожидается 24 оригинальных переменных, найдено: {len(ORIGINAL_VARS)}"
        )
