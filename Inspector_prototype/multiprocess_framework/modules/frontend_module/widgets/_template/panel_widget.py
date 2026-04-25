# -*- coding: utf-8 -*-
"""
Шаблон BaseWidget — панель с lifecycle.

TODO: заменить TemplatePanelWidget на имя своего виджета.
TODO: реализовать _init_ui() — создать layout и компоненты.
TODO: реализовать _connect_signals() — привязать сигналы к presenter.

Lifecycle BaseWidget.__init__:
  1. _coerce_callbacks(callbacks) — нормализация колбэков
  2. _coerce_ui(ui)              — нормализация UI-конфига
  3. _create_model()             — создание Model
  4. _init_ui()                  — построение UI (layouts, виджеты)
  5. _create_presenter(model)    — создание Presenter
  6. _connect_signals()          — привязка сигналов
  7. _on_presenter_ready()       — пост-инициализация
"""
from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import QLabel, QVBoxLayout
from multiprocess_framework.modules.frontend_module.widgets.base_widget import BaseWidget

from .model import TemplateModel
from .presenter import TemplatePresenter
from .schemas import TemplateUiConfig


class TemplatePanelWidget(BaseWidget[TemplateModel]):
    """
    Панель виджета.

    TODO: переименовать класс и реализовать UI.

    Конструктор принимает:
        registers_manager — менеджер регистров (или None)
        callbacks — колбэки для отправки команд в backend
        ui — UI-конфигурация (dict, TemplateUiConfig или None)
        parent — родительский Qt-виджет
    """

    def _coerce_callbacks(self, callbacks: Optional[Any]) -> Any:
        """
        Нормализация колбэков (dict → dataclass, None → дефолтный).

        TODO: определить свой Callbacks dataclass и конвертировать здесь.
        """
        return callbacks

    def _coerce_ui(self, ui: Optional[Any]) -> TemplateUiConfig:
        """Конвертация dict/None → TemplateUiConfig."""
        if isinstance(ui, TemplateUiConfig):
            return ui
        if isinstance(ui, dict):
            # Фильтрация: только известные поля
            known = set(TemplateUiConfig.__dataclass_fields__)
            return TemplateUiConfig(**{k: v for k, v in ui.items() if k in known})
        return TemplateUiConfig()

    def _create_model(self) -> TemplateModel:
        """Создание модели данных. TODO: передать зависимости в модель."""
        return TemplateModel(registers_manager=self._registers_manager)

    def _init_ui(self) -> None:
        """
        Построение UI — layouts, виджеты, Components.

        TODO: заменить заглушку на реальный интерфейс.
        Используйте Components из frontend_module.components:
            result = CheckboxControl.create(rm, BindingConfig(...), ...)
            layout.addWidget(result.widget)
        """
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("TODO: реализовать UI"))

    def _create_presenter(self, model: Optional[TemplateModel]) -> TemplatePresenter:
        """Создание Presenter. TODO: передать дополнительные зависимости."""
        return TemplatePresenter(model=model, view=self)

    def _connect_signals(self) -> None:
        """
        Привязка Qt-сигналов к методам Presenter.

        TODO: подключить сигналы кнопок, чекбоксов и т.п.:
            self._some_button.clicked.connect(self._presenter.on_button_clicked)
        """
        pass

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """
        Пост-инициализация после _connect_signals.

        TODO: вызвать presenter.on_activated() или другую начальную логику.
        """
        self._presenter.on_activated()
