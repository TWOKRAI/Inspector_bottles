# -*- coding: utf-8 -*-
"""
BaseWidget — абстрактный базовый класс для MVP-виджетов с опциональным Model.

Жизненный цикл инициализации:
  1. _coerce_callbacks(callbacks), _coerce_ui(ui)
  2. _create_model() → Model или None
  3. _init_ui() — построение UI без привязки сигналов
  4. _create_presenter(model) → Presenter
  5. _connect_signals() — связь UI ↔ Presenter
  6. _on_presenter_ready(**kwargs) — пост-инициализация

Реализуйте в подклассе:
  - _coerce_callbacks, _coerce_ui
  - _create_model (опционально, по умолчанию None)
  - _init_ui, _create_presenter, _connect_signals
  - при необходимости _on_presenter_ready

Подкласс с моделью: class MyWidget(BaseWidget[MyModel]).
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_widget import BaseTab

from ..widget_signal_bus import WidgetSignalBus

TModel = TypeVar("TModel")


class BaseWidget(BaseTab, Generic[TModel]):
    """
    Базовый класс для MVP-виджетов с опциональным слоем Model.

    Generic[TModel] сохраняет тип модели в _create_presenter / свойстве model.

    Поддерживает два варианта:
    - С Model: _create_model() возвращает экземпляр, Presenter получает его
    - Без Model: _create_model() возвращает None, Presenter работает с rm/callbacks напрямую

    Наследует BaseTab для совместимости с TabWidget (on_tab_selected/on_tab_deselected).

    signal_bus: QObject с сигналом event_emitted(str, object) для внешних подписчиков.
    """

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        callbacks: Optional[Any] = None,
        ui: Optional[Any] = None,
        parent: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self._signal_bus = WidgetSignalBus(parent=self)
        self._registers_manager = registers_manager
        self._callbacks = self._coerce_callbacks(callbacks)
        self._ui = self._coerce_ui(ui)
        self._model = self._create_model()
        self._init_ui()
        self._presenter = self._create_presenter(self._model)
        self._connect_signals()
        self._on_presenter_ready(**kwargs)

    @property
    def signal_bus(self) -> WidgetSignalBus:
        """Подписка: signal_bus.event_emitted.connect(...)."""
        return self._signal_bus

    def emit_widget_event(self, event_id: str, payload: object = None) -> None:
        """Уведомить внешних подписчиков (логгер, метрики). payload — dict, str или None."""
        self._signal_bus.event_emitted.emit(event_id, payload)

    def _coerce_callbacks(self, callbacks: Optional[Any]) -> Any:
        """
        Нормализовать callbacks (dict → dataclass, None → default).
        Override в подклассе.
        """
        return callbacks

    def _coerce_ui(self, ui: Optional[Any]) -> Any:
        """
        Нормализовать ui (None/dict → UiConfig).
        Override в подклассе. Рекомендуется: coerce_schema_config(ui, XxxUiConfig).
        """
        raise NotImplementedError("_coerce_ui must be implemented")

    def _create_model(self) -> Optional[TModel]:
        """
        Создать Model. Override при наличии слоя Model.
        По умолчанию возвращает None (виджет без Model).
        """
        return None

    def _init_ui(self) -> None:
        """Построить UI (виджеты, layout). Без привязки сигналов. Override в подклассе."""
        raise NotImplementedError("_init_ui must be implemented")

    def _create_presenter(self, model: Optional[TModel]) -> Any:
        """
        Создать Presenter. Override в подклассе.
        Получает model (или None) и view=self.
        """
        raise NotImplementedError("_create_presenter must be implemented")

    def _connect_signals(self) -> None:
        """
        Привязать сигналы UI к методам Presenter.
        Override в подклассе.
        """
        raise NotImplementedError("_connect_signals must be implemented")

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """
        Пост-инициализация после _connect_signals.
        Override при необходимости.
        """
        pass

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    @property
    def presenter(self) -> Any:
        """Доступ к презентеру (для внешних вызовов update_*, sync_* и т.п.)."""
        return self._presenter

    @property
    def model(self) -> Optional[TModel]:
        """Доступ к модели, если создана."""
        return self._model
