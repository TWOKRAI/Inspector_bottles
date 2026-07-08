# -*- coding: utf-8 -*-
"""
Контракт-тесты реестра контрактов сообщений и middleware сверки (Ф4.2).

Дизайн: plans/2026-07-06_constructor-master/f4.2-fencing-contracts.md
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from ..contracts import (
    ContractCheck,
    MessageContract,
    MessageContractRegistry,
    contract_key_of,
    make_contract_check_middleware,
)
from ..schemas import CommandMessageSchema


class _Ping(BaseModel):
    """Тестовая схема: id/command обязательны, count опционально, extra запрещён."""

    model_config = ConfigDict(extra="forbid")

    id: str
    command: str
    count: int = 0


def _reg() -> MessageContractRegistry:
    r = MessageContractRegistry()
    r.register("ping", _Ping)
    return r


# --------------------------------------------------------------------------- #
# Регистрация / доступ
# --------------------------------------------------------------------------- #

class TestRegistration:
    def test_register_and_get(self):
        r = _reg()
        c = r.get("ping")
        assert isinstance(c, MessageContract)
        assert c.key == "ping" and c.schema is _Ping and c.plane == "control"

    def test_keys_contains_len(self):
        r = _reg()
        assert "ping" in r
        assert r.keys() == ["ping"]
        assert len(r) == 1

    def test_get_unknown_returns_none(self):
        assert MessageContractRegistry().get("nope") is None

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError):
            MessageContractRegistry().register("", _Ping)

    def test_non_basemodel_schema_rejected(self):
        with pytest.raises(ValueError):
            MessageContractRegistry().register("x", dict)  # type: ignore[arg-type]

    def test_duplicate_without_override_rejected(self):
        r = _reg()
        with pytest.raises(ValueError):
            r.register("ping", _Ping)

    def test_duplicate_with_override_replaces(self):
        r = _reg()
        r.register("ping", CommandMessageSchema, override=True)
        assert r.get("ping").schema is CommandMessageSchema

    def test_plane_data_stored(self):
        r = MessageContractRegistry()
        r.register("frame", _Ping, plane="data")
        assert r.get("frame").plane == "data"


# --------------------------------------------------------------------------- #
# Сверка (validate)
# --------------------------------------------------------------------------- #

class TestValidate:
    def test_unknown_key_returns_none(self):
        assert _reg().validate("other", {"id": "1"}) is None

    def test_none_key_returns_none(self):
        assert _reg().validate(None, {"id": "1"}) is None

    def test_empty_registry_returns_none(self):
        assert MessageContractRegistry().validate("ping", {"id": "1"}) is None

    def test_valid_message_ok(self):
        check = _reg().validate("ping", {"id": "1", "command": "ping", "count": 3})
        assert check is not None and check.ok
        assert check.diff_summary() == "ok"

    def test_missing_required_field(self):
        check = _reg().validate("ping", {"id": "1"})  # нет command
        assert check is not None and not check.ok
        assert check.missing == ["command"]
        assert "command" in check.diff_summary()

    def test_unexpected_field_when_extra_forbidden(self):
        check = _reg().validate("ping", {"id": "1", "command": "p", "bogus": 9})
        assert check is not None and not check.ok
        assert check.unexpected == ["bogus"]

    def test_type_error_reported_not_as_missing(self):
        check = _reg().validate("ping", {"id": "1", "command": "p", "count": "NaN"})
        assert check is not None and not check.ok
        assert check.errors and "count" in check.errors[0]
        assert check.missing == [] and check.unexpected == []

    def test_command_schema_realistic(self):
        r = MessageContractRegistry()
        r.register("process.restart", CommandMessageSchema)
        ok = r.validate(
            "process.restart",
            {"id": "cmd_1", "sender": "s", "targets": ["pm"], "command": "process.restart"},
        )
        assert ok is not None and ok.ok
        bad = r.validate("process.restart", {"id": "cmd_1", "sender": "s"})  # нет targets, command
        assert bad is not None and not bad.ok
        assert set(bad.missing) == {"targets", "command"}


# --------------------------------------------------------------------------- #
# Ключ маршрутизации + middleware
# --------------------------------------------------------------------------- #

class TestContractKeyOf:
    def test_command_priority(self):
        assert contract_key_of({"command": "c", "data_type": "d", "type": "t"}) == "c"

    def test_data_type_fallback(self):
        assert contract_key_of({"data_type": "d", "type": "t"}) == "d"

    def test_type_last(self):
        assert contract_key_of({"type": "t"}) == "t"

    def test_none_when_empty(self):
        assert contract_key_of({}) is None


class TestMiddleware:
    def test_warn_passes_and_calls_hook(self):
        seen: list[ContractCheck] = []
        mw = make_contract_check_middleware(_reg(), strict=False, on_violation=seen.append)
        msg = {"command": "ping", "id": "1"}  # нет обязательных полей схемы? id есть, command есть → ok
        assert mw(msg) is msg
        assert seen == []  # валидное — хук не звался

    def test_warn_reports_violation_but_passes(self):
        seen: list[ContractCheck] = []
        mw = make_contract_check_middleware(_reg(), strict=False, on_violation=seen.append)
        msg = {"command": "ping", "bogus": 1}  # нет id + лишнее bogus
        assert mw(msg) is msg  # warn → проходит
        assert len(seen) == 1 and not seen[0].ok
        assert "id" in seen[0].missing

    def test_strict_drops_violation(self):
        mw = make_contract_check_middleware(_reg(), strict=True)
        assert mw({"command": "ping"}) is None  # нет id → дроп

    def test_strict_passes_valid(self):
        mw = make_contract_check_middleware(_reg(), strict=True)
        msg = {"command": "ping", "id": "1"}
        assert mw(msg) is msg

    def test_unknown_key_passes(self):
        mw = make_contract_check_middleware(_reg(), strict=True)
        msg = {"command": "other", "whatever": 1}
        assert mw(msg) is msg  # нет контракта — проходит даже в strict

    def test_empty_registry_zero_overhead(self):
        mw = make_contract_check_middleware(MessageContractRegistry(), strict=True)
        msg = {"command": "ping"}
        assert mw(msg) is msg
