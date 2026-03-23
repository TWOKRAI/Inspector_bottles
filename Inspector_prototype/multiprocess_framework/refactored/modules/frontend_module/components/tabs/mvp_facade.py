# -*- coding: utf-8 -*-
"""
MvpTabBase — фасад для вкладок с MVP (View + Presenter + Callbacks).

Устраняет дублирование: coerce callbacks/ui → init_ui → create presenter → on_ready.
Дочерний класс реализует 4 метода и View Protocol.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.interfaces import IRegistersManagerGui

from .tab_widget import BaseTab


class MvpTabBase(BaseTab):
    """
    Базовый класс для MVP-вкладок. Упрощает типичный flow:

    1. _coerce_callbacks(callbacks) → типизированный dataclass
    2. _coerce_ui(ui) → UiConfig
    3. _init_ui() — построение UI (виджет реализует View Protocol)
    4. _create_presenter() — презентер с view=self, rm, ui, callbacks
    5. _on_presenter_ready(**kwargs) — пост-инициализация (напр. sync_camera_type)

    Реализуйте в подклассе:
    - _coerce_callbacks, _coerce_ui
    - _init_ui, _create_presenter
    - при необходимости _on_presenter_ready
    - методы View Protocol
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
        self._registers_manager = registers_manager
        self._callbacks = self._coerce_callbacks(callbacks)
        self._ui = self._coerce_ui(ui)
        self._init_ui()
        self._presenter = self._create_presenter()
        self._on_presenter_ready(**kwargs)

    def _coerce_callbacks(self, callbacks: Optional[Any]) -> Any:
        """
        Нормализовать callbacks (dict → dataclass, None → default).

        Override в подклассе.
        """
        return callbacks

    def _coerce_ui(self, ui: Optional[Any]) -> Any:
        """
        Нормализовать ui (None/dict → UiConfig).

        Override в подклассе. Рекомендуется: coerce_schema_config(ui, XxxTabUiConfig).
        """
        raise NotImplementedError("_coerce_ui must be implemented")

    def _init_ui(self) -> None:
        """Построить UI. Override в подклассе."""
        raise NotImplementedError("_init_ui must be implemented")

    def _create_presenter(self) -> Any:
        """
        Создать презентер. Override в подклассе.

        Обычно: XxxTabPresenter(view=self, callbacks=self._callbacks, rm=..., ui=...)
        """
        raise NotImplementedError("_create_presenter must be implemented")

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """
        Пост-инициализация после создания презентера (напр. sync_camera_type).

        Override при необходимости. По умолчанию — no-op.
        """
        pass

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    @property
    def presenter(self) -> Any:
        """Доступ к презентеру (для внешних вызовов update_*, sync_* и т.п.)."""
        return self._presenter
