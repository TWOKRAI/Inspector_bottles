# -*- coding: utf-8 -*-
"""Нейтральное имя приложения — единственный источник для всего фреймворка.

Фреймворк — конструктор: он не знает, какое приложение на нём построено.
До D4 имя продукта («inspector») было зашито в двух местах бэкенда — дефолт
``LoggerManagerConfig.app_name`` в ``managers_config`` и имя pid-реестра
``inspector_system_pids.jsonl``. Оба видны снаружи (в записях наблюдаемости и
в системном temp), и оба делали чужой продукт дефолтом фреймворка.

Имя берётся из env ``MPF_APP_NAME`` (его же читает ``frontend_module``
``AppIdentity`` — ручка одна на GUI и бэкенд), иначе нейтральное
``MultiprocessApp``. Composition root приложения выставляет env до spawn
(дети наследуют) либо передаёт имя явным аргументом.

**Читается при вызове, а не при импорте.** Модуль-уровневый снимок env
замёрз бы на первом импорте — а composition root выставляет ``MPF_APP_NAME``
позже, уже после того, как импорты фреймворка отработали.
"""

from __future__ import annotations

import os
import re

#: Env-ручка имени приложения. Общая с ``frontend_module.core.app_identity``.
APP_NAME_ENV = "MPF_APP_NAME"

#: Нейтральный дефолт: ни один продукт не является дефолтом фреймворка.
DEFAULT_APP_NAME = "MultiprocessApp"

#: Всё, что не подходит для имени файла, схлопывается в ``_``.
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_app_name(environ: dict[str, str] | None = None) -> str:
    """Имя приложения: env ``MPF_APP_NAME``, иначе ``MultiprocessApp``.

    Args:
        environ: словарь окружения (по умолчанию ``os.environ``).

    Returns:
        Непустое имя приложения. Пустое/пробельное значение env считается
        незаданным — иначе ``MPF_APP_NAME=""`` дал бы безымянные артефакты.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(APP_NAME_ENV) or "").strip()
    return raw or DEFAULT_APP_NAME


def app_name_slug(name: str | None = None, *, environ: dict[str, str] | None = None) -> str:
    """Имя приложения, безопасное для имени файла (pid-реестр и т.п.).

    ``"Inspector Bottles"`` → ``"Inspector_Bottles"``. Регистр сохраняется:
    два приложения, различающиеся только регистром, — патология, а не случай,
    который стоит молча схлопывать.

    Args:
        name: явное имя; ``None`` — взять из env через :func:`resolve_app_name`.
        environ: словарь окружения (по умолчанию ``os.environ``).

    Returns:
        Непустой slug. Имя, целиком состоящее из недопустимых символов,
        вырождается в дефолтный slug, а не в пустую строку.
    """
    raw = name if name is not None else resolve_app_name(environ)
    slug = _SLUG_UNSAFE.sub("_", raw).strip("._-")
    return slug or _SLUG_UNSAFE.sub("_", DEFAULT_APP_NAME)
