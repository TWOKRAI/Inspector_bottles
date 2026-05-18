# -*- coding: utf-8 -*-
"""SectionSpec — декларативное описание секции вкладки с tree-навигацией.

`SectionSpec` заменяет императивный набор методов `add_*_page()` в табе:
вместо «сначала создай SystemSection, потом AppearanceSection, потом …»
вкладка отдаёт `list[SectionSpec]`, а `BaseTreeNavTab` циклом строит UI.

Параметр `parent_key` задаёт иерархию (например, `users` живёт под `admin`),
`lazy=True` откладывает вызов фабрики до момента активации секции.

Pure-Python: модуль не импортирует Qt и пригоден для тестов без `pytest-qt`.

Пример::

    from multiprocess_framework.modules.frontend_module.widgets.tabs import (
        SectionSpec,
    )

    sections: list[SectionSpec[AppContext]] = [
        SectionSpec("system", "Настройки системы", SystemSection),
        SectionSpec("appearance", "Оформление", AppearanceSection),
        SectionSpec("admin", "Администрация", AdminDashboard),
        SectionSpec(
            "users",
            "Пользователи",
            UsersPanel,
            parent_key="admin",
            lazy=True,
        ),
    ]

См. ADR-126.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .section_protocol import SectionProtocol

# Тип контекста секции — конкретная вкладка задаёт свой (например, AppContext
# из multiprocess_prototype). Framework контекст не знает.
TCtx = TypeVar("TCtx")


@dataclass(frozen=True)
class SectionSpec(Generic[TCtx]):
    """Декларация секции для `BaseTreeNavTab`.

    Атрибуты:
        key:               уникальный строковый идентификатор (попадает в nav-tree
                           и content stack как ключ маршрутизации).
        title:             отображаемое название узла в дереве навигации.
        factory:           фабрика, создающая секцию по контексту вкладки
                           (`SectionProtocol` или совместимый QWidget).
        parent_key:        ключ родительской секции для построения иерархии
                           (`None` — top-level узел).
        lazy:              `True` — фабрика вызывается только при первой активации
                           секции; `False` — секция создаётся при `populate()`.
        presenter_factory: опциональная фабрика presenter'а.
                           Если задана — `BaseTreeNavTab._attach_section` создаёт
                           presenter через `presenter_factory(ctx, section)` и
                           инжектирует его в секцию через `section.set_presenter(presenter)`.
                           Вызывается **до** `_connect_section_events`, чтобы к моменту
                           подключения bus-callback'а presenter уже был установлен.
                           `None` — секция управляет presenter'ом самостоятельно.
    """

    key: str
    title: str
    factory: Callable[[TCtx], "SectionProtocol"]
    parent_key: str | None = None
    lazy: bool = False
    presenter_factory: Callable[[TCtx, object], object] | None = field(default=None, compare=False, hash=False)
