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
"""
from typing import Any, Dict, Optional, Union


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

    if hasattr(config, "build") and callable(config.build):
        try:
            result = config.build()
        except Exception:
            return dict(default or {})

        if isinstance(result, tuple) and len(result) == 2:
            # RegisterBase.build() convention: (name: str, config_dict: dict)
            _, cfg = result
            return dict(cfg) if isinstance(cfg, dict) else dict(default or {})

        if isinstance(result, dict):
            return result

    return dict(default or {})
