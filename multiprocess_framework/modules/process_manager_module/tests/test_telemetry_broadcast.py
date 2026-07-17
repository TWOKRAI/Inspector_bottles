# -*- coding: utf-8 -*-
"""PC 3.3: fan-out телеметрии на ВСЕХ детей + центральный троттл оркестратора.

Через conftest.make_pm (mock-компоненты) + communication-спай (как test_routing_epoch):
  - ``telemetry.broadcast {publish}`` → всем живым детям уходит ``telemetry.reconfigure``
    ТЕМ ЖЕ путём comm.broadcast, что routing.refresh; в результате виден охват;
  - ``publish=None`` — валидная команда «выключить gate у всех» — доезжает как под-секция;
  - ``throttle`` → применяется к ЦЕНТРАЛЬНОМУ ThrottleMiddleware оркестратора, детям НЕ шлётся;
  - нет state-plane → throttle.applied=False (виден «нет приёмника»);
  - после hot-swap (apply_topology) broadcast адресуется СВЕЖЕМУ набору детей;
  - общий примитив _broadcast_command строит корректный конверт и возвращает охват;
  - команда telemetry.broadcast зарегистрирована (introspect-видимость).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

from .conftest import make_pm


class _CommSpy:
    """Стаб communication: записывает broadcast'ы + адресные send'ы, возвращает заданный охват."""

    def __init__(self, reach: int = 0, *, deliver: bool = True) -> None:
        self.broadcasts: list = []
        self.sends: list = []  # (target, message) адресных send_to_process (Task 1.4)
        self.reach = reach
        self.deliver = deliver

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.broadcasts.append((message, exclude_self))
        return self.reach

    def send_to_process(self, target: str, message) -> bool:
        self.sends.append((target, message))
        return self.deliver


class _FakeStoreManager:
    """Минимальный StateStoreManager: держит живой ThrottleMiddleware по имени."""

    def __init__(self, throttle: ThrottleMiddleware) -> None:
        self._throttle = throttle

    def get_middleware(self, name: str):
        return self._throttle if name == "throttle" else None


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}


def _pm(
    children: dict | None = None,
    *,
    reach: int = 0,
    throttle: ThrottleMiddleware | None = None,
    deliver: bool = True,
):
    """PM с comm-спаем + опц. центральным троттлом + зарегистрированными детьми в PSR."""
    pm = make_pm(children or {})
    pm.communication = _CommSpy(reach=reach, deliver=deliver)
    # Дети видны через shared_resources.get_process_names (источник охвата fan-out).
    for name in children or {}:
        pm.shared_resources.register_process(name, {})
    if throttle is not None:
        pm._state_store_manager = _FakeStoreManager(throttle)
    return pm


def _telemetry_broadcasts(pm) -> list:
    return [m for m, _excl in pm.communication.broadcasts if m.get("command") == "telemetry.reconfigure"]


class TestPublishFanout:
    def test_publish_reaches_all_children(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"enabled": False}}}})

        assert res["success"] is True
        # Ровно один broadcast telemetry.reconfigure ушёл детям.
        bcasts = _telemetry_broadcasts(pm)
        assert len(bcasts) == 1
        msg = bcasts[0]
        assert msg["command"] == "telemetry.reconfigure"
        assert msg["type"] == "command"
        assert msg["sender"] == pm.name
        assert msg["queue_type"] == "system"
        assert msg["data"] == {"publish": {"metrics": {"fps": {"enabled": False}}}}
        # exclude_self=True — сам PM не переконфигурируется broadcast'ом.
        assert pm.communication.broadcasts[-1][1] is True
        # Охват виден: 2 цели, доставлено 2, полный.
        assert res["publish"]["target_count"] == 2
        assert res["publish"]["reached"] == 2
        assert res["publish"]["complete"] is True
        assert res["publish"]["targets"] == ["camera_0", "detector"]

    def test_publish_none_disables_gate_for_all(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)
        res = pm._cmd_telemetry_broadcast({"publish": None})
        assert res["success"] is True
        # publish=None доехал как валидная под-секция «выключить gate».
        assert _telemetry_broadcasts(pm)[0]["data"] == {"publish": None}

    def test_incomplete_coverage_is_visible(self) -> None:
        """reached < target_count → complete=False (наблюдаемость «no silent caps»)."""
        pm = _pm({"a": {"class": "m.A"}, "b": {"class": "m.B"}, "c": {"class": "m.C"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {}})
        assert res["publish"]["target_count"] == 3
        assert res["publish"]["reached"] == 2
        assert res["publish"]["complete"] is False


class TestThrottleToOrchestrator:
    def test_throttle_applied_to_central_middleware_not_broadcast(self) -> None:
        throttle = ThrottleMiddleware({"old.rule": 9.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"throttle": {"processes.**.state.fps": 2.0}})

        assert res["success"] is True
        assert res["throttle"] == {"requested": True, "applied": True}
        # set_rules ПОЛНОСТЬЮ заменяет набор (PC 0.1 семантика).
        assert throttle.rules == {"processes.**.state.fps": 2.0}
        # throttle НЕ рассылается детям — comm.broadcast не звали.
        assert _telemetry_broadcasts(pm) == []
        assert pm.communication.broadcasts == []

    def test_throttle_without_state_store_reports_no_receiver(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)  # без _state_store_manager
        res = pm._cmd_telemetry_broadcast({"throttle": {"a": 1.0}})
        assert res["success"] is True
        assert res["throttle"] == {"requested": True, "applied": False}


class TestBothPlanes:
    def test_publish_and_throttle_in_one_command(self) -> None:
        throttle = ThrottleMiddleware({})
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"shm": {"enabled": False}}}, "throttle": {"p.q": 4.0}}
        )
        # publish разослан детям, throttle применён к оркестратору.
        assert res["publish"]["reached"] == 2
        assert res["throttle"]["applied"] is True
        assert throttle.rules == {"p.q": 4.0}
        assert _telemetry_broadcasts(pm)[0]["data"] == {"publish": {"metrics": {"shm": {"enabled": False}}}}


class TestMergeMode:
    """Task 1.1: telemetry_mode прокидывается детям (publish) и в central-throttle."""

    def test_replace_default_omits_mode_from_child_payload(self) -> None:
        """replace (дефолт) → детям уходит прежний конверт без telemetry_mode (бит-в-бит)."""
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"enabled": False}}}})
        assert _telemetry_broadcasts(pm)[0]["data"] == {"publish": {"metrics": {"fps": {"enabled": False}}}}

    def test_merge_forwards_mode_to_children(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"enabled": False}}}, "telemetry_mode": "merge"})
        data = _telemetry_broadcasts(pm)[0]["data"]
        assert data["telemetry_mode"] == "merge"
        assert data["publish"] == {"metrics": {"fps": {"enabled": False}}}

    def test_merge_throttle_keeps_other_central_rules(self) -> None:
        """merge central-throttle: правится одно правило, дефолтная страховка соседей уцелела."""
        throttle = ThrottleMiddleware({"processes.**.state.latency_ms": 1.0, "processes.**.state.fps": 1.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"throttle": {"processes.**.state.fps": 0.2}, "telemetry_mode": "merge"})
        assert res["throttle"]["applied"] is True
        assert throttle.rules == {"processes.**.state.latency_ms": 1.0, "processes.**.state.fps": 0.2}


class TestThrottleFailureIsolated:
    def test_bad_throttle_does_not_lose_publish_coverage(self) -> None:
        """Исключение в throttle-ветке НЕ должно маскировать уже совершённый
        publish-fan-out. Регресс: без try/except throttle-исключение всплывало,
        и Dispatcher подменял ВЕСЬ ответ на generic-error — терялся охват доставки
        publish (нарушение «no silent caps»)."""
        throttle = ThrottleMiddleware({})
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2, throttle=throttle)
        # Не-dict throttle: set_rules → dict("bad") бросит ValueError внутри ветки.
        res = pm._cmd_telemetry_broadcast({"publish": {}, "throttle": "bad"})

        # Команда не упала, publish-охват сохранён и виден целиком.
        assert res["success"] is True
        assert res["publish"]["reached"] == 2
        assert res["publish"]["target_count"] == 2
        assert res["publish"]["complete"] is True
        # throttle-ветка отчиталась об ошибке, не применилась.
        assert res["throttle"]["requested"] is True
        assert res["throttle"]["applied"] is False
        assert "error" in res["throttle"]


class TestCappedByThrottle:
    """Task 1.3 (ADR-PM-017): «no silent caps» — поднятие частоты ниже central-правила
    сообщается явным флагом ``capped_by_throttle`` (троттл НЕ ослабляется автоматически)."""

    def test_publisher_raise_below_central_rule_is_flagged(self) -> None:
        """publisher fps=0.5с ниже central 2.0с → флаг в результате (троттл срезал бы)."""
        throttle = ThrottleMiddleware({"processes.**.state.fps": 2.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "telemetry_mode": "merge"}
        )
        assert res["success"] is True
        caps = res["publish"]["capped_by_throttle"]
        assert caps == {"fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 2.0}}
        # Страховка НЕ тронута (auto-relax отвергнут): central-правило осталось прежним.
        assert throttle.rules == {"processes.**.state.fps": 2.0}
        # publish всё равно разослан детям (детский gate поднят; central-троттл — отдельно).
        assert _telemetry_broadcasts(pm)[0]["data"]["publish"] == {"metrics": {"fps": {"interval_sec": 0.5}}}

    def test_no_flag_when_publisher_above_rule(self) -> None:
        """publisher fps=3.0с выше central 2.0с → троттл не режет → флага нет."""
        throttle = ThrottleMiddleware({"processes.**.state.fps": 2.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 3.0}}}})
        assert "capped_by_throttle" not in res["publish"]

    def test_no_flag_with_soft_default_throttle(self) -> None:
        """Мягкий дефолт-троттл (0.05с) ниже поднятого publisher (0.1с) → флага нет."""
        throttle = ThrottleMiddleware({"processes.**.state.fps": 0.05})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 0.1}}}})
        assert "capped_by_throttle" not in res["publish"]

    def test_no_flag_without_central_throttle(self) -> None:
        """Нет StateStoreManager у PM → нет central-правил → нечего срезать, флага нет."""
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)  # throttle=None
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 0.1}}}})
        assert "capped_by_throttle" not in res["publish"]

    def test_combined_publish_raise_and_throttle_relax_same_metric_not_flagged(self) -> None:
        """Ревью-фикс #3: комбинированная команда {publish: raise, throttle: relax} той же
        метрики В ОДНОМ вызове — cap-детекция обязана читать central-правило ПОСЛЕ
        применения throttle-под-секции, иначе ложноположительный `capped_by_throttle` по
        pre-relax строгому правилу (детектор раньше вызывался ДО throttle-apply)."""
        throttle = ThrottleMiddleware({"processes.**.state.fps": 2.0})  # строгое pre-relax правило
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {
                "publish": {"metrics": {"fps": {"interval_sec": 0.5}}},
                "throttle": {"processes.**.state.fps": 0.1},
                "telemetry_mode": "merge",
            }
        )
        assert res["success"] is True
        # Throttle-релакс применился (правило теперь мягче publisher-интервала).
        assert res["throttle"]["applied"] is True
        assert throttle.rules == {"processes.**.state.fps": 0.1}
        # Cap оценивается ПОСЛЕ relax → publisher (0.5с) уже НЕ строже финального правила
        # (0.1с) → флага нет (до фикса ловился бы ложный cap по старому 2.0с).
        assert "capped_by_throttle" not in res["publish"]


def _addressed_sends(pm) -> list:
    """Адресные send_to_process с командой telemetry.reconfigure (Task 1.4)."""
    return [(t, m) for t, m in pm.communication.sends if m.get("command") == "telemetry.reconfigure"]


class TestAddressedViaPm:
    """Task 1.4 (ADR-PM-017 Amendment): адресный per-process путь транзитом через PM.

    ``data["target"]`` = имя процесса → publish форвардится ОДНОМУ ребёнку через
    ``send_to_process`` (не broadcast всем), throttle применяется центрально, а
    ``capped_by_throttle`` детектится тем же PM-троттлом, что и на fan-out пути.
    """

    def test_addressed_publish_sends_to_single_child_not_broadcast(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"enabled": False}}}, "target": "camera_0"})
        assert res["success"] is True
        # Ушёл адресный send ОДНОМУ ребёнку, broadcast всем — НЕ звался.
        sends = _addressed_sends(pm)
        assert len(sends) == 1
        target, msg = sends[0]
        assert target == "camera_0"
        assert msg["command"] == "telemetry.reconfigure"
        assert msg["type"] == "command"
        assert msg["sender"] == pm.name
        assert msg["queue_type"] == "system"
        assert msg["data"] == {"publish": {"metrics": {"fps": {"enabled": False}}}}
        assert _telemetry_broadcasts(pm) == []  # fan-out НЕ использован
        # Охват адресный: одна цель, доставлено.
        assert res["publish"]["target_count"] == 1
        assert res["publish"]["reached"] == 1
        assert res["publish"]["targets"] == ["camera_0"]
        assert res["publish"]["complete"] is True

    def test_addressed_publish_below_central_rule_is_flagged(self) -> None:
        """ГЛАВНЫЙ acceptance Task 1.4: адресный raise ниже central-правила → capped_by_throttle
        в результате (а НЕ тихий success с молчаливым будущим срезом)."""
        throttle = ThrottleMiddleware({"processes.**.state.fps": 2.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 0.5}}}, "target": "camera_0", "telemetry_mode": "merge"}
        )
        assert res["success"] is True
        caps = res["publish"]["capped_by_throttle"]
        assert caps == {"fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 2.0}}
        # Страховка НЕ тронута (auto-relax отвергнут), publish всё равно доставлен ребёнку.
        assert throttle.rules == {"processes.**.state.fps": 2.0}
        assert _addressed_sends(pm)[0][1]["data"]["publish"] == {"metrics": {"fps": {"interval_sec": 0.5}}}

    def test_addressed_publish_above_rule_not_flagged(self) -> None:
        throttle = ThrottleMiddleware({"processes.**.state.fps": 0.05})  # мягкий дефолт
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"interval_sec": 0.1}}}, "target": "camera_0"}
        )
        assert "capped_by_throttle" not in res["publish"]

    def test_addressed_throttle_applies_centrally(self) -> None:
        """throttle на per-process путь всё равно центральный (троттл оркестратор-глобален)."""
        throttle = ThrottleMiddleware({})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"throttle": {"processes.**.state.fps": 3.0}, "target": "camera_0"})
        assert res["throttle"]["applied"] is True
        assert throttle.rules == {"processes.**.state.fps": 3.0}
        # throttle не форвардится ребёнку (у него нет central-троттла).
        assert _addressed_sends(pm) == []

    def test_addressed_merge_forwards_mode_to_child(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)
        pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"enabled": False}}}, "target": "camera_0", "telemetry_mode": "merge"}
        )
        data = _addressed_sends(pm)[0][1]["data"]
        assert data["telemetry_mode"] == "merge"
        assert data["publish"] == {"metrics": {"fps": {"enabled": False}}}

    def test_addressed_delivery_failure_reached_zero(self) -> None:
        """send_to_process вернул False (нет очереди/приёмника) → reached=0, complete=False."""
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, deliver=False)
        res = pm._cmd_telemetry_broadcast({"publish": {}, "target": "camera_0"})
        assert res["publish"]["reached"] == 0
        assert res["publish"]["target_count"] == 1
        assert res["publish"]["complete"] is False

    def test_target_all_is_fanout_not_addressed(self) -> None:
        """target='all' трактуется как fan-out (broadcast), НЕ адресный send."""
        pm = _pm({"a": {"class": "m.A"}, "b": {"class": "m.B"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {}, "target": "all"})
        assert len(_telemetry_broadcasts(pm)) == 1
        assert _addressed_sends(pm) == []
        assert res["publish"]["target_count"] == 2


class TestSendChildPrimitive:
    def test_send_child_command_builds_envelope_and_returns_delivered(self) -> None:
        pm = _pm({"a": {"class": "m.A"}}, reach=1)
        ok = pm._send_child_command("a", "custom.cmd", {"k": "v"})
        assert ok is True
        target, msg = pm.communication.sends[-1]
        assert target == "a"
        assert msg == {
            "type": "command",
            "command": "custom.cmd",
            "sender": pm.name,
            "queue_type": "system",
            "data": {"k": "v"},
        }

    def test_send_child_command_no_comm_is_noop(self) -> None:
        pm = make_pm({})
        pm.communication = None
        assert pm._send_child_command("a", "x", {}) is False


class TestUnknownModeRejected:
    """Task 1.2 finding-1: битый telemetry_mode → success=False ДО fan-out (broadcast
    fire-and-forget: ошибку детей никто не соберёт, поэтому валидируем в PM заранее)."""

    def test_unknown_mode_returns_failure_and_no_broadcast(self) -> None:
        throttle = ThrottleMiddleware({"keep": 1.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"fps": {"enabled": False}}}, "telemetry_mode": "mrege"}
        )
        assert res["success"] is False
        assert res["mode"] == "mrege"
        assert "mrege" in res["reason"]
        # Битый mode НЕ ушёл детям и НЕ тронул central-троттл.
        assert pm.communication.broadcasts == []
        assert throttle.rules == {"keep": 1.0}


class TestValidation:
    def test_empty_command_is_error(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}})
        res = pm._cmd_telemetry_broadcast({})
        assert res["success"] is False
        assert "publish" in res["reason"] or "throttle" in res["reason"]
        assert pm.communication.broadcasts == []


class TestAfterHotSwap:
    def test_broadcast_reaches_fresh_children_after_apply_topology(self) -> None:
        """После hot-swap fan-out адресуется СВЕЖЕМУ набору детей (актуальный PSR PM).

        apply_topology cleanup'ит старых (unregister_process) и provision'ит новых
        (register_process) → get_process_names отражает новый набор. Broadcast идёт
        тем же comm-путём, что и routing.refresh (PM держит свежие очереди) — так же
        надёжно долетает до пересозданных процессов.
        """
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2)
        new_bp = {
            "processes": [
                {"process_name": "cam_hd", "process_class": "m.CamHD"},
                {"process_name": "merger", "process_class": "m.Merge"},
            ]
        }
        result = pm.apply_topology(new_bp)
        assert result["success"] is True
        # Свежий PSR — новые дети.
        assert sorted(pm.shared_resources.get_process_names()) == ["cam_hd", "merger"]

        # Отбрасываем routing.refresh-рассылки switch'а, меряем только telemetry.
        pm.communication.broadcasts.clear()
        res = pm._cmd_telemetry_broadcast({"publish": {}})

        assert res["publish"]["targets"] == ["cam_hd", "merger"]
        assert res["publish"]["target_count"] == 2
        assert len(_telemetry_broadcasts(pm)) == 1


class TestBroadcastPrimitive:
    def test_broadcast_command_builds_envelope_and_returns_reach(self) -> None:
        pm = _pm({"a": {"class": "m.A"}}, reach=3)
        count = pm._broadcast_command("custom.cmd", {"k": "v"})
        assert count == 3
        msg, exclude = pm.communication.broadcasts[-1]
        assert msg == {
            "type": "command",
            "command": "custom.cmd",
            "sender": pm.name,
            "queue_type": "system",
            "data": {"k": "v"},
        }
        assert exclude is True

    def test_broadcast_command_no_comm_is_noop(self) -> None:
        pm = make_pm({})  # без communication
        pm.communication = None
        assert pm._broadcast_command("x", {}) == 0


class TestRegistration:
    def test_telemetry_broadcast_registered_with_description(self) -> None:
        pm = make_pm({})
        pm.command_manager = _FakeCommandManager()
        pm._register_builtin_commands()
        assert "telemetry.broadcast" in pm.command_manager.handlers
        # Description непустой → introspect.capabilities/handlers покажет команду.
        assert pm.command_manager.metadata["telemetry.broadcast"]["description"]
        # Handler — это _cmd_telemetry_broadcast.
        assert pm.command_manager.handlers["telemetry.broadcast"] == pm._cmd_telemetry_broadcast
