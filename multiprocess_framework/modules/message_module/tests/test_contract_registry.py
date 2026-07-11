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

    def test_transport_underscore_keys_not_flagged_unexpected(self):
        """Служебные `_`-поля (`_fence` fencing-Ф4.2, `_address`, `_receive_info`)
        не часть payload-контракта → не попадают в `unexpected` даже при extra=forbid."""
        check = _reg().validate(
            "ping",
            {
                "id": "1",
                "command": "p",
                "_fence": {"epoch": 5},
                "_address": ["proc", "worker"],
                "_receive_info": {"router_id": "x"},
                "_source_channel": "proc_system",
            },
        )
        assert check is not None
        assert check.unexpected == []
        assert check.ok

    def test_transport_correlation_id_not_flagged_unexpected(self):
        """NEW-3: `correlation_id` — транспортная метка `RouterManager.request()`
        (зеркалится в `data` ЛЮБОГО request-response вызова), не поле команды.
        Без исключения strict-раскатка built-in контрактов дропала бы КАЖДУЮ команду,
        отправленную через request-response (найдено live-прогоном capabilities-дампа)."""
        check = _reg().validate(
            "ping",
            {"id": "1", "command": "p", "correlation_id": "abc-123"},
        )
        assert check is not None
        assert check.unexpected == []
        assert check.ok

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


# --------------------------------------------------------------------------- #
# H5 (Ф4-добор): command-контракты валидируют message["data"], а не конверт
# --------------------------------------------------------------------------- #


class _WireParams(BaseModel):
    """Схема параметров команды — параметры едут в message["data"]."""

    model_config = ConfigDict(extra="forbid")

    wire_key: str  # обязательный
    buffer_slots: int = 4  # типизированный, опциональный


class TestParamsInData:
    """H5: params_in_data=True → сверка идёт по message["data"] (не по конверту).

    Без этого схема параметров сверялась с ключами конверта (command/data/target)
    и НИКОГДА не видела своих полей → warn-mw была структурно инертна.
    """

    def _reg(self):
        r = MessageContractRegistry()
        r.register("wire.configure", _WireParams, params_in_data=True)
        return r

    def test_contract_stores_params_in_data(self):
        assert self._reg().get("wire.configure").params_in_data is True

    def test_valid_params_ok(self):
        msg = {"command": "wire.configure", "data": {"wire_key": "a→b", "buffer_slots": 8}}
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and check.ok

    def test_type_error_in_data_caught(self):
        """Type-ошибка параметра в data теперь ловится (раньше была невидима)."""
        msg = {"command": "wire.configure", "data": {"wire_key": "a→b", "buffer_slots": "NaN"}}
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and not check.ok
        assert check.errors and "buffer_slots" in check.errors[0]

    def test_transport_correlation_id_in_data_not_flagged(self):
        """NEW-3: `correlation_id` в `message["data"]` (params_in_data=True) — та же
        транспортная метка, тот же исключающий путь `_TRANSPORT_KEYS`."""
        msg = {
            "command": "wire.configure",
            "data": {"wire_key": "a→b", "buffer_slots": 8, "correlation_id": "abc-123"},
        }
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and check.ok

    def test_missing_required_in_data_caught(self):
        msg = {"command": "wire.configure", "data": {"buffer_slots": 4}}  # нет wire_key
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and not check.ok
        assert check.missing == ["wire_key"]

    def test_typo_field_in_data_caught_when_forbid(self):
        """Опечатка имени параметра (extra=forbid) → unexpected → WARNING (acceptance H5)."""
        msg = {"command": "wire.configure", "data": {"wire_key": "a", "buffer_slotss": 4}}
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and not check.ok
        assert check.unexpected == ["buffer_slotss"]

    def test_envelope_keys_ignored(self):
        """Ключи конверта (command/target/type) НЕ считаются лишними/missing —
        сверяется только data."""
        msg = {
            "command": "wire.configure",
            "target": "b",
            "type": "command",
            "data": {"wire_key": "a→b"},
        }
        check = self._reg().validate("wire.configure", msg)
        assert check is not None and check.ok

    def test_no_data_key_uses_empty_payload(self):
        """Нет data (или не dict) → payload={} → обязательные всё равно missing, не падает."""
        check = self._reg().validate("wire.configure", {"command": "wire.configure"})
        assert check is not None and not check.ok
        assert check.missing == ["wire_key"]

    def test_old_flat_path_would_miss_data_error(self):
        """Демонстрация инертности, которую чиним: БЕЗ params_in_data type-ошибка
        в data не видна (сверялся конверт, не data)."""
        r = MessageContractRegistry()
        r.register("wire.configure", _WireParams)  # params_in_data=False (старый путь)
        msg = {"command": "wire.configure", "data": {"buffer_slots": "NaN"}}
        check = r.validate("wire.configure", msg)
        assert check is not None
        # type-ошибка buffer_slots в data НЕ попадает в errors (data не проверялась)
        assert not any("buffer_slots" in e for e in check.errors)
