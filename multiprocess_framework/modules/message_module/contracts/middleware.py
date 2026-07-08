# -*- coding: utf-8 -*-
"""
Receive-middleware сверки сообщений с реестром контрактов (Ф4.2).

Чистая фабрика: не знает про `RouterManager`, возвращает функцию
``fn(msg: dict) -> dict | None``, совместимую с
:meth:`IRouterManager.add_receive_middleware`. Проводка в роутер (чтение
``FW_CONTRACTS_STRICT``, привязка логгера) — отдельный шаг композиции.

Семантика:
  - **warn** (``strict=False``, дефолт): нарушение контракта → вызвать
    ``on_violation(check)`` (обычно ``log.warning`` с diff полей), но сообщение
    ПРОПУСТИТЬ. Диагностика, не барьер.
  - **strict** (``strict=True``): нарушение → вернуть ``None`` (дроп). Барьер;
    default нигде — только по явному флагу.

Ключ маршрутизации извлекается как ``command`` → ``data_type`` → ``type``
(тот же приоритет, что у kind-router/event_dispatcher). Неизвестный ключ →
``validate`` вернёт ``None`` → сообщение проходит без изменений.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .registry import ContractCheck, MessageContractRegistry

MiddlewareFn = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
ViolationHook = Callable[[ContractCheck], None]


def contract_key_of(message: Dict[str, Any]) -> Optional[str]:
    """Ключ маршрутизации сообщения: command → data_type → type."""
    return message.get("command") or message.get("data_type") or message.get("type") or None


def make_contract_check_middleware(
    registry: MessageContractRegistry,
    *,
    strict: bool = False,
    on_violation: Optional[ViolationHook] = None,
) -> MiddlewareFn:
    """Собрать receive-middleware по реестру контрактов.

    Guard на пустой реестр — ноль оверхеда: `validate` по неизвестному ключу
    сразу возвращает `None`, нарушения не может быть.
    """

    def _contract_middleware(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = contract_key_of(message)
        check = registry.validate(key, message)
        if check is not None and not check.ok:
            if on_violation is not None:
                on_violation(check)
            if strict:
                return None  # дроп: сообщение не соответствует контракту
        return message

    return _contract_middleware


__all__ = ["MiddlewareFn", "ViolationHook", "contract_key_of", "make_contract_check_middleware"]
