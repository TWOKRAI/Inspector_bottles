# -*- coding: utf-8 -*-
"""
env — общий парсер булевых env-флагов (единый список truthy-литералов).

Выделено, чтобы модули не плодили свои списки ``("1", "true", "yes", ...)``
(ревью Ф7 G.2 F9). Пустая/отсутствующая строка → False.
"""

from __future__ import annotations

import os
from typing import Optional

#: Канонический набор truthy-литералов (регистронезависимо, после strip).
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def env_truthy(value: Optional[str]) -> bool:
    """True, если строка — один из canonical truthy-литералов (иначе False).

    None/пустая строка → False. Регистр и окружающие пробелы игнорируются.
    """
    if not value:
        return False
    return value.strip().lower() in _TRUTHY


def env_flag(name: str, default: bool = False) -> bool:
    """Прочитать булев env-флаг ``name``.

    Если переменная НЕ задана (или пустая) → ``default``. Иначе — truthy-разбор
    (в т.ч. явное выключение ``name=0`` возвращает False, перекрывая default).
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return env_truthy(raw)
