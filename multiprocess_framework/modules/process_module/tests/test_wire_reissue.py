# -*- coding: utf-8 -*-
"""Ф7 G.4.d (B-7) — чистая ЗАМЕНА wire-middleware при re-issue на switch/restart.

`_reissue_wires_for` шлёт ``wire.configure`` с ТЕМ ЖЕ ``wire_key``. Раньше
`_cmd_wire_configure` перезаписывал `_wire_middlewares[wire_key]` НОВЫМ middleware, НЕ
сняв старый с router'а → старый ``on_receive``/``on_send`` продолжал обрабатывать кадры
(двойная обработка) и держал стейл handle-cache (замороженные handles на старый регион =
зависшие/перепутанные кадры после switch). Теперь reconfigure с существующим wire_key
чисто снимает старый (helper `_teardown_wire_middleware`) → нет утечки, handles
получателя обновляются на switch (безопасно, без кросс-процессного дренажа живой очереди).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands


class _RecordingRouter:
    def __init__(self) -> None:
        self.send_mws: list = []
        self.recv_mws: list = []
        self.frame_mws: list = []

    def add_send_middleware(self, fn) -> None:
        self.send_mws.append(fn)

    def remove_send_middleware(self, fn) -> None:
        if fn in self.send_mws:
            self.send_mws.remove(fn)

    def add_receive_middleware(self, fn) -> None:
        self.recv_mws.append(fn)

    def remove_receive_middleware(self, fn) -> None:
        if fn in self.recv_mws:
            self.recv_mws.remove(fn)

    def register_frame_middleware(self, mw) -> None:
        self.frame_mws.append(mw)

    def unregister_frame_middleware(self, mw) -> None:
        if mw in self.frame_mws:
            self.frame_mws.remove(mw)


class _Svc:
    def __init__(self, router) -> None:
        self.router_manager = router
        self.memory_manager = None
        self.shared_resources = None

    def _log_info(self, *a, **k) -> None: ...
    def _log_error(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...


def _configure(bc, role, wire_key="w"):
    return bc._cmd_wire_configure(
        data={"wire_key": wire_key, "role": role, "shm_name": "output_frames", "shm_owner": "cam0"}
    )


def test_receiver_reissue_replaces_without_leak():
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))

    assert _configure(bc, "receiver")["success"] is True
    mw1 = bc._wire_middlewares["w"][0]
    assert len(router.recv_mws) == 1  # один on_receive зарегистрирован

    # Re-issue: тот же wire_key → старый снят, новый поставлен (НЕ два!).
    assert _configure(bc, "receiver")["success"] is True
    mw2 = bc._wire_middlewares["w"][0]
    assert mw2 is not mw1  # реально новый инстанс
    assert len(router.recv_mws) == 1  # НЕТ утечки/двойной обработки (было бы 2)


def test_sender_reissue_replaces_and_unregisters_frame_mw():
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))

    _configure(bc, "sender")
    mw1 = bc._wire_middlewares["w"][0]
    assert len(router.send_mws) == 1
    assert len(router.frame_mws) == 1

    _configure(bc, "sender")
    mw2 = bc._wire_middlewares["w"][0]
    assert mw2 is not mw1
    assert len(router.send_mws) == 1  # старый on_send снят
    assert len(router.frame_mws) == 1  # старый снят из агрегации счётчиков (не задвоен)


def test_many_reissues_no_accumulation():
    """N переключений подряд → ровно 1 зарегистрированный middleware (не N)."""
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))
    for _ in range(5):
        _configure(bc, "receiver")
    assert len(router.recv_mws) == 1
    assert len(bc._wire_middlewares) == 1


def test_deconfigure_still_removes():
    """Helper переиспользуется deconfigure — снятие по-прежнему работает."""
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))
    _configure(bc, "receiver")
    assert bc._cmd_wire_deconfigure(data={"wire_key": "w"})["success"] is True
    assert len(router.recv_mws) == 0
    assert "w" not in bc._wire_middlewares


def test_deconfigure_unknown_wire_ok():
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))
    res = bc._cmd_wire_deconfigure(data={"wire_key": "nope"})
    assert res["success"] is True
    assert "note" in res


def test_buffer_slots_gated_off_by_default(monkeypatch):
    """Ф7 G.4.b (ревью 2026-07-14): БЕЗ FW_QOS_PROFILES buffer_slots игнорируется →
    глубина кольца прежние 3 (откат бит-в-бит; buffer_slots дефолтит в 4 ещё до Ф7)."""
    monkeypatch.delenv("FW_QOS_PROFILES", raising=False)
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))
    bc._cmd_wire_configure(
        data={"wire_key": "w", "role": "receiver", "shm_name": "of", "shm_owner": "cam0", "buffer_slots": 8}
    )
    assert bc._wire_middlewares["w"][0]._coll == 3  # buffer_slots=8 проигнорирован


def test_buffer_slots_honored_with_flag(monkeypatch):
    """С FW_QOS_PROFILES buffer_slots задаёт глубину кольца per-camera."""
    monkeypatch.setenv("FW_QOS_PROFILES", "1")
    router = _RecordingRouter()
    bc = BuiltinCommands(_Svc(router))
    bc._cmd_wire_configure(
        data={"wire_key": "w", "role": "receiver", "shm_name": "of", "shm_owner": "cam0", "buffer_slots": 8}
    )
    assert bc._wire_middlewares["w"][0]._coll == 8
