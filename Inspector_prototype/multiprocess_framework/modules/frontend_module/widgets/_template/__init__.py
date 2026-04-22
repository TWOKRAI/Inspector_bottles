# -*- coding: utf-8 -*-
"""
Шаблон виджета — скопируй папку и переименуй.

Использование:
  1. Скопировать _template/ в widgets/<my_name>/
  2. Переименовать классы Template* → MyFeature*
  3. Заполнить schemas.py, model.py, presenter.py, panel_widget.py
  4. Обновить этот __init__.py — реэкспортировать свои классы
"""
from .panel_widget import TemplatePanelWidget
from .schemas import TemplateUiConfig

__all__ = ["TemplatePanelWidget", "TemplateUiConfig"]
