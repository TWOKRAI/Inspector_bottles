# -*- coding: utf-8 -*-
"""
contracts — реестр контрактов сообщений и middleware сверки (Ф4.2).

Публичный API:

    from multiprocess_framework.modules.message_module.contracts import (
        MessageContract, ContractCheck, MessageContractRegistry,
        make_contract_check_middleware,
    )

Дизайн: `plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md`.
"""
from .middleware import (
    MiddlewareFn,
    ViolationHook,
    contract_key_of,
    make_contract_check_middleware,
)
from .registry import ContractCheck, MessageContract, MessageContractRegistry

__all__ = [
    "MessageContract",
    "ContractCheck",
    "MessageContractRegistry",
    "make_contract_check_middleware",
    "contract_key_of",
    "MiddlewareFn",
    "ViolationHook",
]
