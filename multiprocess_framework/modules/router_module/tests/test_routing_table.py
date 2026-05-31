# -*- coding: utf-8 -*-
"""
Contract-тесты таблицы маршрутизации и address-aware резолвера (P0.2 transport-router-hub).

Покрывают: ``MESSAGE_TYPE_TO_CHANNEL`` объявлена; нормализация ``command``/``type`` → kind
(recon #1: STATE из ``command="state.*"`` несмотря на ``type``); ``channel_name`` склейка;
``resolve_route``/``resolve_routes`` (оси адрес × kind, recon #2/#6); громкий отказ на
неизвестном type вместо тихого drop.
"""

import pytest

from ...message_module import AddressValidationError, MessageType
from ..routing import (
    CHANNEL_KINDS,
    DATA,
    EVENT,
    MESSAGE_TYPE_TO_CHANNEL,
    STATE,
    SYSTEM,
    RouteDecision,
    UnknownMessageTypeError,
    channel_name,
    resolve_channel_kind,
    resolve_route,
    resolve_routes,
)


class TestRoutingTableDeclared:
    """Таблица type→channel объявлена и непротиворечива."""

    def test_table_covers_core_types(self):
        assert MESSAGE_TYPE_TO_CHANNEL[MessageType.COMMAND] == SYSTEM
        assert MESSAGE_TYPE_TO_CHANNEL[MessageType.SYSTEM] == SYSTEM
        assert MESSAGE_TYPE_TO_CHANNEL[MessageType.DATA] == DATA
        assert MESSAGE_TYPE_TO_CHANNEL[MessageType.EVENT] == EVENT

    def test_all_targets_are_valid_kinds(self):
        assert set(MESSAGE_TYPE_TO_CHANNEL.values()) <= CHANNEL_KINDS

    def test_no_state_member_in_enum(self):
        # STATE — channel-kind, выводимый из command, а НЕ член MessageType (план: no new kind).
        assert not hasattr(MessageType, "STATE")
        assert STATE in CHANNEL_KINDS


class TestResolveChannelKind:
    """Нормализация command/type → channel-kind (recon #1)."""

    def test_command_message_to_system(self):
        assert resolve_channel_kind({"type": "command", "command": "worker.create"}) == SYSTEM

    def test_data_message(self):
        assert resolve_channel_kind({"type": "data"}) == DATA

    def test_event_message(self):
        assert resolve_channel_kind({"type": "event"}) == EVENT

    def test_state_changed_despite_event_type(self):
        # B9: DeltaDispatcher шлёт type="event", но семантика STATE (command="state.changed").
        msg = {"type": "event", "command": "state.changed", "data": {"deltas": []}}
        assert resolve_channel_kind(msg) == STATE

    def test_state_set_despite_command_type(self):
        # B8: StateProxy шлёт type="command", command="state.set" → STATE.
        assert resolve_channel_kind({"type": "command", "command": "state.set"}) == STATE

    def test_command_prefix_wins_over_type(self):
        # Префикс command имеет приоритет над таблицей type.
        assert resolve_channel_kind({"type": "data", "command": "state.merge"}) == STATE

    def test_unknown_type_raises_not_silent(self):
        # B10: type="system_event" вне enum, command не покрыт → громкий отказ (P1.2).
        with pytest.raises(UnknownMessageTypeError):
            resolve_channel_kind({"type": "system_event", "command": "system_event"})

    def test_missing_type_raises(self):
        with pytest.raises(UnknownMessageTypeError):
            resolve_channel_kind({})


class TestChannelName:
    def test_naming_convention(self):
        # Совпадает с существующими очередями {proc}_system / {proc}_data.
        assert channel_name("ProcessManager", SYSTEM) == "ProcessManager_system"
        assert channel_name("camera_proc", DATA) == "camera_proc_data"


class TestResolveRoute:
    """Резолвер маршрута: оси адрес × kind."""

    def test_simple_command(self):
        d = resolve_route("ProcessManager", {"type": "command", "command": "heartbeat"})
        assert d == RouteDecision(
            process="ProcessManager",
            kind=SYSTEM,
            channel="ProcessManager_system",
            subpath=[],
        )

    def test_worker_address_subpath(self):
        d = resolve_route("proc.worker_in", {"type": "data"})
        assert d.process == "proc"
        assert d.kind == DATA
        assert d.channel == "proc_data"
        assert d.subpath == ["worker_in"]

    def test_invalid_address_raises(self):
        with pytest.raises(AddressValidationError):
            resolve_route(".worker", {"type": "command"})

    def test_unknown_kind_raises(self):
        with pytest.raises(UnknownMessageTypeError):
            resolve_route("proc", {"type": "system_event"})


class TestResolveRoutes:
    """Мультикаст + сосуществование target/targets (recon #2) + broadcast (recon #6)."""

    def test_targets_list(self):
        routes = resolve_routes({"type": "command", "command": "x", "targets": ["a", "b"]})
        assert [r.process for r in routes] == ["a", "b"]
        assert all(r.kind == SYSTEM for r in routes)

    def test_scalar_target_data_plane(self):
        # B2/B3: data-plane использует скаляр target.
        routes = resolve_routes({"type": "data", "target": "display_proc"})
        assert len(routes) == 1
        assert routes[0].channel == "display_proc_data"

    def test_broadcast_addresses_skipped(self):
        # recon #6: all/broadcast — отдельный fan-out путь, не иерархический адрес.
        routes = resolve_routes({"type": "command", "command": "x", "targets": ["all", "proc"]})
        assert [r.process for r in routes] == ["proc"]

    def test_empty_targets(self):
        assert resolve_routes({"type": "command", "command": "x"}) == []
