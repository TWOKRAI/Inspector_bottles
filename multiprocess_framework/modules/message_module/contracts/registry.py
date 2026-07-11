# -*- coding: utf-8 -*-
"""
Реестр контрактов сообщений (Ф4.2).

`MessageContractRegistry` связывает **ключ маршрутизации** (имя команды или
`data_type`) с Pydantic-схемой сообщения. Реестр — источник истины «какая форма
у сообщения X», который потом использует:

  - warn/strict middleware на receive (см. :mod:`..contracts.middleware`) —
    сверяет входящее сообщение со схемой и логирует diff полей вместо «тихого» no-op
    (класс бага 1.6: опечатка в имени поля/команды молча теряется);
  - «контактная книжка» `introspect.capabilities` v1 — отдаёт `params_schema`
    из реестра, чтобы агент/оператор видел форму команды без чтения исходников.

Дизайн-документ фазы: `plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md`.

Контракт по умолчанию (Design-by-Contract):
  - `register`: `key` непустой, `schema` — подкласс pydantic `BaseModel`;
    повторная регистрация того же ключа без `override=True` → `ValueError`.
  - `validate`: неизвестный ключ → `None` (нечего проверять, НЕ ошибка);
    известный → :class:`ContractCheck` с раздельными списками
    missing / unexpected / errors.

Пустой реестр = ноль оверхеда: `validate` по неизвестному ключу возвращает `None`
до любой валидации.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

#: Служебные ключи транспорта, не part payload-контракта команды (NEW-3, 2026-07-11).
#: `correlation_id` зеркалится в `data` ЛЮБОГО request-response вызова
#: (`RouterManager.request` → `data.setdefault("correlation_id", cid)`, PM-обёртка
#: `process.command`) — не поле конкретной команды, а транспортная метка сопоставления
#: ответа. Без исключения strict-раскатка built-in контрактов (NEW-3) дропала бы КАЖДУЮ
#: команду, отправленную через request-response (обнаружено live-прогоном
#: backend_ctl/tests/test_capabilities.py::test_dump_matches_committed).
_TRANSPORT_KEYS = frozenset({"correlation_id"})


@dataclass(frozen=True)
class MessageContract:
    """Один контракт: ключ маршрутизации → Pydantic-схема сообщения.

    plane: "control" (по умолчанию — валидируется реестром) | "data" (hot-path;
    валидируется НЕ здесь, а payload-валидатором 4.3 — инвариант для Ф7).

    params_in_data: True для command-контрактов, чьи ПАРАМЕТРЫ едут вложенно в
    ``message["data"]`` (схема описывает параметры команды, не конверт). Тогда
    сверка идёт по ``message["data"]``, а не по плоскому конверту — иначе схема
    параметров никогда не видит своих полей и warn-mw инертна (H5, Ф4-добор).
    """

    key: str
    schema: Type[BaseModel]
    plane: str = "control"
    params_in_data: bool = False


@dataclass
class ContractCheck:
    """Результат сверки сообщения с контрактом — для warn/strict middleware.

    Раздельные списки, чтобы WARNING показал понятный diff полей:
      - missing:    обязательные поля схемы, которых нет в сообщении;
      - unexpected: поля сообщения вне схемы (только для схем с extra="forbid");
      - errors:     прочие ошибки валидации известных полей (типы, диапазоны).
    """

    key: str
    ok: bool
    missing: List[str] = field(default_factory=list)
    unexpected: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def diff_summary(self) -> str:
        """Однострочный человекочитаемый diff для лога."""
        parts: List[str] = []
        if self.missing:
            parts.append(f"нет обязательных: {', '.join(self.missing)}")
        if self.unexpected:
            parts.append(f"лишние: {', '.join(self.unexpected)}")
        if self.errors:
            parts.append(f"ошибки: {'; '.join(self.errors)}")
        return " | ".join(parts) if parts else "ok"


class MessageContractRegistry:
    """Реестр контрактов: `command|data_type` → :class:`MessageContract`."""

    def __init__(self) -> None:
        self._contracts: Dict[str, MessageContract] = {}

    # ------------------------------------------------------------------ #
    # Регистрация / доступ
    # ------------------------------------------------------------------ #

    def register(
        self,
        key: str,
        schema: Type[BaseModel],
        *,
        plane: str = "control",
        params_in_data: bool = False,
        override: bool = False,
    ) -> MessageContract:
        """Зарегистрировать контракт для ключа маршрутизации.

        Повторная регистрация того же ключа без ``override=True`` — ошибка
        (дубль контрактов = рассинхрон источника истины). ``params_in_data=True``
        — параметры команды едут в ``message["data"]`` (сверять именно их).
        """
        if not key or not isinstance(key, str):
            raise ValueError(f"contract key должен быть непустой строкой, получено: {key!r}")
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(f"schema для '{key}' должна быть подклассом pydantic BaseModel, получено: {schema!r}")
        if key in self._contracts and not override:
            raise ValueError(
                f"контракт для '{key}' уже зарегистрирован "
                f"({self._contracts[key].schema.__name__}); передайте override=True для замены"
            )
        contract = MessageContract(key=key, schema=schema, plane=plane, params_in_data=params_in_data)
        self._contracts[key] = contract
        return contract

    def get(self, key: str) -> Optional[MessageContract]:
        """Контракт по ключу или ``None``."""
        return self._contracts.get(key)

    def keys(self) -> List[str]:
        """Отсортированный список зарегистрированных ключей."""
        return sorted(self._contracts)

    def __contains__(self, key: str) -> bool:
        return key in self._contracts

    def __len__(self) -> int:
        return len(self._contracts)

    # ------------------------------------------------------------------ #
    # Сверка
    # ------------------------------------------------------------------ #

    def validate(self, key: Optional[str], message: Dict[str, Any]) -> Optional[ContractCheck]:
        """Сверить сообщение с контрактом по ключу.

        Неизвестный ключ (или ``None``) → ``None``: контракта нет, проверять
        нечего — это НЕ нарушение (частичное покрытие реестра допустимо).
        """
        if not key:
            return None
        contract = self._contracts.get(key)
        if contract is None:
            return None
        return self._check(contract, message)

    @staticmethod
    def _check(contract: MessageContract, message: Dict[str, Any]) -> ContractCheck:
        schema = contract.schema
        fields = schema.model_fields
        forbid_extra = schema.model_config.get("extra") == "forbid"

        # H5: для command-контрактов параметры вложены в message["data"] — сверяем
        # именно их. Иначе схема параметров (wire_key/role/…) сверяется с ключами
        # конверта (command/data/target) и НИКОГДА не видит своих полей → warn-mw
        # инертна. data не dict (или нет) → {} (нечего сверять, не нарушение).
        if contract.params_in_data:
            payload = message.get("data")
            if not isinstance(payload, dict):
                payload = {}
        else:
            payload = message

        missing = [name for name, info in fields.items() if info.is_required() and name not in payload]
        # `_`-префиксные ключи — служебные transport-поля (`_address`, `_receive_info`,
        # `_source_channel`, `_relayed`, `_fence` fencing-токена Ф4.2), плюс именованные
        # transport-ключи из `_TRANSPORT_KEYS` (`correlation_id` — NEW-3). Они не часть
        # payload-контракта и не должны попадать в diff «лишних» полей.
        unexpected = (
            [k for k in payload if k not in fields and not k.startswith("_") and k not in _TRANSPORT_KEYS]
            if forbid_extra
            else []
        )

        errors: List[str] = []
        # Валидируем только известные поля — типы/диапазоны; missing/unexpected уже
        # посчитаны отдельно, чтобы diff был читаемым, а не сырым Pydantic-текстом.
        known = {k: v for k, v in payload.items() if k in fields}
        try:
            schema(**known)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                # required-ошибки уже покрыты списком missing — не дублируем
                if err.get("type") == "missing":
                    continue
                errors.append(f"{loc}: {err.get('msg', 'invalid')}")

        ok = not missing and not unexpected and not errors
        return ContractCheck(
            key=contract.key,
            ok=ok,
            missing=missing,
            unexpected=unexpected,
            errors=errors,
        )


__all__ = ["MessageContract", "ContractCheck", "MessageContractRegistry"]
