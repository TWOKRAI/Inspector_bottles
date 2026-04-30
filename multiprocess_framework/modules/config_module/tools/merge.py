"""
Канонический deep merge для конфиг-словарей.

Заменяет ad-hoc реализации:
- ``merge_with_defaults`` (data_schema_module) — shallow copy, небезопасно для nested mutable
- ``merge_managers`` (process_module) — deepcopy, но привязан к одному модулю

Использование::

    from multiprocess_framework.modules.config_module.tools import deep_merge, multi_merge

    result = deep_merge(defaults, user_overrides)
    result = multi_merge(defaults, env_config, user_config, cli_args)
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional


def deep_merge(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
    *,
    copy_base: bool = True,
    list_strategy: str = "replace",
) -> Dict[str, Any]:
    """
    Рекурсивный merge *overlay* поверх *base*. Overlay побеждает при конфликте.

    Args:
        base: Базовый dict (дефолты).
        overlay: Dict для наложения. ``None``/пустой → возвращает копию base.
        copy_base: ``True`` — deepcopy base (безопасно). ``False`` — мутация на месте.
        list_strategy: Стратегия для list-значений:
            - ``"replace"`` — overlay полностью заменяет base (по умолчанию)
            - ``"append"`` — overlay элементы добавляются к base

    Returns:
        Объединённый dict.
    """
    if copy_base:
        result = copy.deepcopy(base)
    else:
        result = base

    if not overlay:
        return result

    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            # Рекурсия для вложенных dict'ов — не копируем повторно,
            # base уже скопирован на верхнем уровне
            result[key] = deep_merge(
                result[key], value, copy_base=False, list_strategy=list_strategy,
            )
        elif (
            list_strategy == "append"
            and key in result
            and isinstance(result[key], list)
            and isinstance(value, list)
        ):
            result[key] = result[key] + copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def multi_merge(
    *layers: Optional[Dict[str, Any]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Merge N слоёв слева направо. Поздние перезаписывают ранние.

    Args:
        *layers: Словари для merge (``None`` пропускаются).
        **kwargs: Передаются в ``deep_merge`` (``list_strategy`` и т.д.).

    Returns:
        Объединённый dict.

    Example::

        result = multi_merge(defaults, env_config, user_config, cli_args)
    """
    result: Dict[str, Any] = {}
    for layer in layers:
        if layer is not None:
            result = deep_merge(result, layer, copy_base=False, **kwargs)
    return result
