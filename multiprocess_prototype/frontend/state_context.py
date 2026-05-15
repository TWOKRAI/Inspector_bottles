# -*- coding: utf-8 -*-
"""StateContext — связка зависимостей state/registers domain.

Объединяет registers_manager + bindings в единый узкий контракт.
Импортируется потребителями (table presenters, inspector_panel) вместо
полного AppContext.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_framework.modules.registers_module import RegistersManager


@dataclass(frozen=True)
class StateContext:
    """State-домен: registers + reactive bindings.

    Attributes:
        registers_manager: RegistersManager (схемы регистров + IPC-sync).
        bindings: GuiStateBindings (реактивные подписки на StateStore).
    """

    registers_manager: "RegistersManager"
    bindings: "GuiStateBindings | None" = None
