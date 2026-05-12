"""Theme domain: переменные темы оформления (CSS-палитра, шрифты, размеры)."""

from .schemas import (
    THEME_VAR_DESCRIPTIONS,
    THEME_VAR_TREE,
    ThemeVariables,
    flatten_theme_var_tree,
    get_default_variables,
)

# Обратная совместимость — виджеты, использующие плоскую структуру групп
THEME_VAR_GROUPS = flatten_theme_var_tree(THEME_VAR_TREE)

__all__ = [
    "ThemeVariables",
    "THEME_VAR_TREE",
    "THEME_VAR_GROUPS",
    "flatten_theme_var_tree",
    "THEME_VAR_DESCRIPTIONS",
    "get_default_variables",
]
