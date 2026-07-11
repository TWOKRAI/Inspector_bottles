# -*- coding: utf-8 -*-
"""
normalize_config — универсальный нормализатор конфигурации.

Поддерживает три формата конфига (Dict at Boundary, ADR-008):
  - None            → дефолтный пустой dict {} (или переданный default)
  - dict            → используется as-is
  - RegisterBase    → вызывает obj.build() → (name, config_dict)
  - любой объект с build() → то же что RegisterBase

Применяется в ChannelRoutingManager.__init__() для унификации конфига
от RouterManager, LoggerManager, ErrorManager и любого будущего наследника.

ADR-CRM-008 (D1, constructor-master Ф5-добор): resolve_build_result() —
общий примитив извлечения (name, dict) из build()-объекта. LoggerCore и
ErrorManager используют его вместо собственных копий этой же логики — см.
DECISIONS.md.
"""

from typing import Any, Dict, Optional, Tuple, Union


def resolve_build_result(config: Any) -> Optional[Tuple[Optional[str], Dict[str, Any]]]:
    """Если у config есть callable build() — вызвать и извлечь (name, dict).

    Поддерживает конвенцию ``RegisterBase.build() -> (name, config_dict)`` и
    произвольный ``build() -> config_dict`` (тогда name = None).

    Returns:
        (name, dict) — payload извлечён и является dict.
        None         — build() отсутствует ИЛИ его результат не удалось
                       привести к dict (вызывающий код сам решает fallback).

    Note:
        Исключения из ``config.build()`` НЕ перехватываются — это
        ответственность вызывающего (см. normalize_config — глушит их сам).
    """
    if not (hasattr(config, "build") and callable(config.build)):
        return None

    result = config.build()

    if isinstance(result, tuple) and len(result) == 2:
        # RegisterBase.build() convention: (name: str, config_dict: dict)
        name, cfg = result
        return (name, dict(cfg)) if isinstance(cfg, dict) else None

    if isinstance(result, dict):
        return None, result

    return None


def normalize_config(
    config: Optional[Union[Dict[str, Any], Any]],
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Привести config к словарю.

    Args:
        config:  None | dict | объект с методом build()
        default: Значение по умолчанию если config=None или неподдерживаемый тип

    Returns:
        dict с параметрами конфигурации (никогда не None)

    Examples:
        >>> normalize_config(None)
        {}
        >>> normalize_config({"level": "INFO"})
        {"level": "INFO"}
        >>> normalize_config(RouterManagerConfig())
        {"manager_name": "RouterManager", "send_queue_size": 512, ...}
    """
    if config is None:
        return dict(default or {})

    if isinstance(config, dict):
        return config

    try:
        resolved = resolve_build_result(config)
    except Exception:
        return dict(default or {})

    if resolved is not None:
        return resolved[1]

    return dict(default or {})
