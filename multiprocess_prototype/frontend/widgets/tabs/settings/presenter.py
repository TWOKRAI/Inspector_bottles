# -*- coding: utf-8 -*-
"""SettingsPresenter — app-specific обёртка над TreeNavTabPresenter.

После Phase 4 post-review (ffa6f92→) presenter не содержит логики undo/redo:
`DiffScrollTabLayout.enable_undo_redo()` сам подписывает свои кнопки на
ActionBus. Класс оставлен ради явного типа `SettingsView` и точки расширения
для app-specific логики, которая может появиться в Phase 5+.

Task D.5: мигрирован на AppServices — принимает services вместо ctx.

См. ADR-126.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    TreeNavTabPresenter,
)

from .view import SettingsView

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices


class SettingsPresenter(TreeNavTabPresenter[SettingsView, None]):
    """Презентер таба Settings — тонкая обёртка над TreeNavTabPresenter.

    Task D.5: принимает AppServices. Нет прямых обращений к ctx.extras.
    """

    def __init__(
        self,
        *,
        view: SettingsView,
        rm=None,
        ui=None,
        services: "AppServices",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._services = services
