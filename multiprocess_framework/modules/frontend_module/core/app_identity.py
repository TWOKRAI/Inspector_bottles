# -*- coding: utf-8 -*-
"""
AppIdentity — инъекция app-специфичной идентичности (org/название/лого) в frontend_module.

frontend_module — generic UI-фреймворк-конструктор, не должен знать имя конкретного
продукта, построенного поверх него. Composition root приложения (например
multiprocess_prototype/frontend/app.py) вызывает set_app_identity(...) ДО создания
первого виджета, читающего идентичность (AppHeaderWidget → prefs_store.QSettings,
LoadingWindow — фолбэк-текст логотипа).

Дефолт — нейтральный (см. _default_identity): "MultiprocessApp" либо значение env
MPF_APP_NAME. Без явной инъекции фреймворк не тянет за собой чужой бренд.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppIdentity:
    """
    Идентичность приложения, инжектируемая composition root'ом.

    Attributes:
        org: Namespace для QSettings (QSettings(org, app)). КРИТИЧНО: смена org
            для уже задеплоенного приложения теряет сохранённые пользовательские
            preferences (реестр Windows / plist macOS / ini Linux ключуются по org+app).
        app_name: Человекочитаемое имя приложения.
        window_title: Заголовок окна по умолчанию, если не задан явно; по умолчанию = app_name.
        logo_text: Фолбэк-текст логотипа (например LoadingWindow, если нет logo_path/pixmap);
            по умолчанию = app_name.
    """

    org: str
    app_name: str
    window_title: str = ""
    logo_text: str = ""

    def __post_init__(self) -> None:
        # frozen=True → прямое присваивание запрещено, только через object.__setattr__.
        if not self.window_title:
            object.__setattr__(self, "window_title", self.app_name)
        if not self.logo_text:
            object.__setattr__(self, "logo_text", self.app_name)


def _default_identity() -> AppIdentity:
    """Нейтральный дефолт: env MPF_APP_NAME либо 'MultiprocessApp'."""
    name = os.environ.get("MPF_APP_NAME", "MultiprocessApp")
    return AppIdentity(org=name, app_name=name)


_identity: AppIdentity = _default_identity()


def set_app_identity(identity: AppIdentity) -> None:
    """
    Установить app-идентичность. Composition root вызывает ДО создания виджетов,
    читающих идентичность (иначе QSettings-namespace/лого успеют закэшироваться
    под дефолтным значением).
    """
    global _identity
    _identity = identity


def get_app_identity() -> AppIdentity:
    """Получить текущую app-идентичность (дефолт — нейтральный, см. _default_identity)."""
    return _identity
