# -*- coding: utf-8 -*-
"""TabSpec — декларативное описание одной вкладки приложения.

Механизм табов (``TabRegistry``) generic и не знает конкретных вкладок
приложения. Приложение (composition root) описывает свои вкладки списком
``list[TabSpec]``; порядок списка = порядок вкладок в ``QTabWidget``.

Границы (NEW-D1): этот тип живёт во ``frontend_module`` и НЕ импортирует
ничего из прикладного слоя. Фабрика (``factory``) — callable, чью сигнатуру
задаёт приложение; ``TabRegistry`` форвардит ей ``factory_context`` без
интерпретации (Dict/opaque at boundary для UI-контекста).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget


@dataclass(frozen=True)
class TabSpec:
    """Описание вкладки: идентичность, отображение, право доступа, фабрика.

    Поля:
        id: стабильный идентификатор вкладки (например ``"settings"``). Служит
            ключом реестра и основой для permission-имён (``tabs.<id>.view``).
        title: заголовок вкладки в UI.
        view_permission: имя права на просмотр (``tabs.<id>.view``). Если у
            текущего ``AccessContext`` его нет — вкладка скрывается. ``None``
            означает «доступна всем» (гостевые вкладки до логина).
        factory: ``callable`` создания содержимого вкладки. Вызывается с
            ``*factory_context`` реестра. ``None`` → используется
            ``placeholder_factory`` реестра (заглушка).
        description: пояснение для заглушки/тултипа (необязательно).

    Порядок вкладок определяется позицией в списке ``list[TabSpec]``,
    отдельного поля порядка нет.
    """

    id: str
    title: str
    view_permission: Optional[str] = None
    factory: Optional[Callable[..., "QWidget"]] = None
    description: str = ""
