"""Env-алиасы ``MULTIPROCESS_*`` ↔ ``INSPECTOR_*`` — де-брендинг фреймворка (Ф5.11).

Брендинг ``INSPECTOR_*`` протёк во framework исторически (``pid_registry``,
``log_paths``, точка входа прототипа). Каноничное имя для фреймворка-конструктора —
нейтральный префикс ``MULTIPROCESS_*``; ``INSPECTOR_*`` остаётся **алиасом**
(back-compat, НЕ переименование — существующий код и второе приложение работают оба).

``apply_env_aliases`` зеркалит недостающий ключ пары из заданного (в любую сторону):
если выставлен только ``MULTIPROCESS_PID_FILE`` — код, читающий ``INSPECTOR_PID_FILE``,
всё равно видит значение, и наоборот. Если заданы оба — не трогаем (уважаем явное).

Вызывается один раз в начале ``run_app`` (до spawn — дети наследуют env).
"""

from __future__ import annotations

import os

#: Пары ``(каноничный MULTIPROCESS_*, легаси INSPECTOR_*)`` — оба читаются кодом.
ENV_ALIAS_PAIRS: tuple[tuple[str, str], ...] = (
    ("MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE"),
    ("MULTIPROCESS_LOG_DIR", "INSPECTOR_LOG_DIR"),
    ("MULTIPROCESS_MANIFEST", "INSPECTOR_MANIFEST"),
)


def apply_env_aliases(environ: dict[str, str] | None = None) -> list[str]:
    """Заполнить недостающий ключ каждой пары ``MULTIPROCESS_*``/``INSPECTOR_*``.

    Идемпотентно: повторный вызов ничего не меняет. Если заданы оба ключа пары —
    не трогаем (явное значение приоритетно). Если задан ровно один — копируем его
    во второй (алиас в обе стороны).

    Args:
        environ: словарь окружения (по умолчанию ``os.environ``). Мутируется на месте.

    Returns:
        Список имён ключей, которые были дозаполнены (для логов/тестов).
    """
    env = os.environ if environ is None else environ
    filled: list[str] = []
    for canonical, legacy in ENV_ALIAS_PAIRS:
        has_canonical = canonical in env and env[canonical] != ""
        has_legacy = legacy in env and env[legacy] != ""
        if has_canonical and not has_legacy:
            env[legacy] = env[canonical]
            filled.append(legacy)
        elif has_legacy and not has_canonical:
            env[canonical] = env[legacy]
            filled.append(canonical)
    return filled
