"""
Deep merge для конфиг-словарей — тонкий делегат канонического ``deep_merge``.

Канон живёт в ``data_schema_module`` (нижний слой, дубль D3 / задача C5):
``multiprocess_framework.modules.data_schema_module.deep_merge``. Здесь —
делегат с сохранённой сигнатурой для обратной совместимости всех импортов::

    from multiprocess_framework.modules.config_module.tools import deep_merge, multi_merge

    result = deep_merge(defaults, user_overrides)
    result = multi_merge(defaults, env_config, user_config, cli_args)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from multiprocess_framework.modules.data_schema_module import (
    deep_merge as _canonical_deep_merge,
)


def deep_merge(
    base: Dict[str, Any],
    overlay: Optional[Dict[str, Any]],
    *,
    copy_base: bool = True,
    list_strategy: str = "replace",
) -> Dict[str, Any]:
    """
    Рекурсивный merge *overlay* поверх *base*. Overlay побеждает при конфликте.

    Тонкий делегат канонического
    :func:`multiprocess_framework.modules.data_schema_module.deep_merge`.

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
    return _canonical_deep_merge(
        base,
        overlay,
        copy_base=copy_base,
        list_strategy=list_strategy,
    )


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
