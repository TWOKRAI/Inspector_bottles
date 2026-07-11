# -*- coding: utf-8 -*-
"""NEW-3: strict-валидация control-plane built-in команд (ADR-MSG-008, шаг 7).

Проверяет:
  - все схемы `BUILTIN_COMMAND_CONTRACTS` — `extra="forbid"` (неизвестный ключ ловится);
  - warn (дефолт): опечатка в имени параметра → WARNING с diff «лишние: ...» +
    счётчик `contract_violations`, но сообщение ДОХОДИТ (доставка не меняется);
  - strict (`FW_CONTRACTS_STRICT=1`): то же сообщение дропается;
  - транспортный `correlation_id` (зеркалится в `data` ЛЮБЫМ `router.request()`) не
    считается лишним полем ни для одного built-in контракта — регресс находки,
    вскрытой live-прогоном (backend_ctl/tests/test_capabilities.py, см. отчёт задачи).
"""

from __future__ import annotations

from pydantic import BaseModel

from multiprocess_framework.modules.message_module import (
    MessageContractRegistry,
    make_contract_check_middleware,
)
from multiprocess_framework.modules.process_module.commands.command_contracts import (
    BUILTIN_COMMAND_CONTRACTS,
    WireConfigureParams,
    WorkerNameParams,
)


def _registry_with_builtins() -> MessageContractRegistry:
    r = MessageContractRegistry()
    for cmd, schema in BUILTIN_COMMAND_CONTRACTS.items():
        r.register(cmd, schema, params_in_data=True, override=True)
    return r


class TestAllBuiltinContractsForbidExtra:
    """NEW-3: ни одна схема built-in команды не должна оставаться `extra="allow"`."""

    def test_every_schema_is_forbid(self):
        for cmd, schema in BUILTIN_COMMAND_CONTRACTS.items():
            assert issubclass(schema, BaseModel), cmd
            assert schema.model_config.get("extra") == "forbid", (
                f"{cmd}: схема параметров должна быть extra='forbid' (NEW-3), а не {schema.model_config.get('extra')!r}"
            )

    def test_registry_covers_all_built_in_commands(self):
        """Наполнение реестра идентично словарю (тот же путь, что и в BuiltinCommands)."""
        r = _registry_with_builtins()
        assert set(r.keys()) == set(BUILTIN_COMMAND_CONTRACTS)


class TestUnknownKeyDiagnostics:
    """Опечатка в имени параметра → внятный diff (unexpected), не тихий проход."""

    def test_typo_in_wire_configure_reported(self):
        r = _registry_with_builtins()
        # buffer_slotss вместо buffer_slots — типичная опечатка (H5-класс бага).
        msg = {"command": "wire.configure", "data": {"wire_key": "a", "buffer_slotss": 4}}
        check = r.validate("wire.configure", msg)
        assert check is not None and not check.ok
        assert check.unexpected == ["buffer_slotss"]
        assert "buffer_slotss" in check.diff_summary()

    def test_typo_in_worker_remove_reported(self):
        r = _registry_with_builtins()
        msg = {"command": "worker.remove", "data": {"worker_nam": "w1"}}  # опечатка в имени
        check = r.validate("worker.remove", msg)
        assert check is not None and not check.ok
        assert check.unexpected == ["worker_nam"]

    def test_no_params_command_rejects_any_data(self):
        """introspect.status не принимает параметров — любой ключ лишний."""
        r = _registry_with_builtins()
        msg = {"command": "introspect.status", "data": {"verbose": True}}
        check = r.validate("introspect.status", msg)
        assert check is not None and not check.ok
        assert check.unexpected == ["verbose"]

    def test_valid_payload_is_clean(self):
        r = _registry_with_builtins()
        msg = {"command": "wire.configure", "data": {"wire_key": "a→b", "role": "sender"}}
        check = r.validate("wire.configure", msg)
        assert check is not None and check.ok


class TestCorrelationIdNotFlagged:
    """Регресс: `data.correlation_id` (транспорт `router.request()`) не должен
    считаться лишним полем ни для одного built-in контракта.

    Обнаружено live-прогоном `test_dump_matches_committed` — до фикса КАЖДАЯ
    команда, отправленная через request-response, получала ложный WARNING
    'лишние: correlation_id' на каждом процессе при загрузке headless-бэкенда.
    """

    def test_correlation_id_ignored_for_worker_name_params(self):
        r = _registry_with_builtins()
        msg = {"command": "worker.remove", "data": {"worker_name": "w1", "correlation_id": "abc-123"}}
        check = r.validate("worker.remove", msg)
        assert check is not None and check.ok

    def test_correlation_id_ignored_for_no_params_command(self):
        r = _registry_with_builtins()
        msg = {"command": "introspect.capabilities", "data": {"correlation_id": "abc-123"}}
        check = r.validate("introspect.capabilities", msg)
        assert check is not None and check.ok

    def test_real_typo_still_caught_alongside_correlation_id(self):
        """correlation_id не маскирует настоящую опечатку рядом с ним."""
        r = _registry_with_builtins()
        msg = {
            "command": "wire.configure",
            "data": {"wire_key": "a", "correlation_id": "abc-123", "buffer_slotss": 4},
        }
        check = r.validate("wire.configure", msg)
        assert check is not None and not check.ok
        assert check.unexpected == ["buffer_slotss"]


class TestWarnVsStrictDelivery:
    """Регресс: warn-режим (дефолт) НИКАК не меняет доставку — только диагностика."""

    def test_warn_mode_delivers_message_unchanged_despite_violation(self):
        seen = []
        mw = make_contract_check_middleware(_registry_with_builtins(), strict=False, on_violation=seen.append)
        msg = {"command": "wire.configure", "data": {"wire_key": "a", "buffer_slotss": 4}}
        out = mw(msg)
        assert out is msg  # доставлено как есть — ни одного бита не изменено
        assert len(seen) == 1 and not seen[0].ok

    def test_strict_mode_drops_same_violation(self):
        mw = make_contract_check_middleware(_registry_with_builtins(), strict=True)
        msg = {"command": "wire.configure", "data": {"wire_key": "a", "buffer_slotss": 4}}
        assert mw(msg) is None

    def test_warn_mode_passes_valid_messages_silently(self):
        """Клин на raskatku: валидный трафик под warn не генерирует нарушений вовсе."""
        seen = []
        mw = make_contract_check_middleware(_registry_with_builtins(), strict=False, on_violation=seen.append)
        for cmd, schema in BUILTIN_COMMAND_CONTRACTS.items():
            # Пустое data — валидно для схем без обязательных полей (все built-in
            # params-схемы — Optional-only, NEW-3).
            msg = {"command": cmd, "data": {}}
            out = mw(msg)
            assert out is msg
        assert seen == []  # ноль ложных нарушений на пустом валидном трафике

    def test_strict_mode_passes_valid_traffic_for_every_builtin_command(self):
        """Acceptance NEW-3: strict-раскатка не должна ронять корректные вызовы
        ни одной из built-in команд (0 violations на «чистом» вызове)."""
        mw = make_contract_check_middleware(_registry_with_builtins(), strict=True)
        for cmd in BUILTIN_COMMAND_CONTRACTS:
            msg = {"command": cmd, "data": {"correlation_id": "abc"}}
            assert mw(msg) is msg, f"{cmd}: валидный вызов дропнут в strict-режиме"


class TestParamsSchemaOfStillOptional:
    """NEW-3 намеренно не меняет required-ность полей — только extra=allow→forbid."""

    def test_wire_key_still_optional(self):
        from multiprocess_framework.modules.process_module.commands.command_contracts import params_schema_of

        fields = {f["name"]: f for f in params_schema_of(WireConfigureParams)}
        assert fields["wire_key"]["required"] is False

    def test_worker_name_optional(self):
        from multiprocess_framework.modules.process_module.commands.command_contracts import params_schema_of

        fields = {f["name"]: f for f in params_schema_of(WorkerNameParams)}
        assert fields["worker_name"]["required"] is False
