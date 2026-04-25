# multiprocess_prototype_v3/frontend/widgets/settings_tab/ui_preferences_schema.py
"""Схема пользовательских предпочтений UI (режим отображения вкладок)."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema


@register_schema("UiPreferencesConfig")
class UiPreferencesConfig(SchemaBase):
    """Предпочтения интерфейса: режим отображения (карточки / таблица)."""

    settings_view_mode: int = 0  # 0=карточки, 1=таблица
    recipes_view_mode: int = 0  # 0=карточки, 1=таблица
