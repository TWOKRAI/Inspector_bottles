# -*- coding: utf-8 -*-
"""Тесты B.3: system_overview — компактная сводка + anomalies на подставных счётчиках.

Acceptance плана: сводка компактна; аномалии детектятся на fake-ответах;
ноль новых IPC-команд (fan-out только существующими ручками).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


from backend_ctl.tests.conftest import (  # noqa: E402 — общие хелперы
    ROUTER_COUNTERS,
    full_router_stats,
)
from backend_ctl.tests.conftest import wire_line as _line  # noqa: E402 — общий хелпер


def _feed_state(d: BackendDriver, path: str, value: Any) -> None:
    d.dispatch_raw(_line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}))


def _fake_backend(
    monkeypatch, d: BackendDriver, *, procs: List[str], responses: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Подставной send_command: канонические ответы по (command) + журнал команд."""
    sent: List[str] = []

    def fake_send(target: str, command: str, args: Any = None, *, timeout: Any = None) -> Dict[str, Any]:
        sent.append(command)
        if command == "state.get_subtree":
            return {"success": True, "result": {"subtree": {p: {} for p in procs}}}
        per_target = responses.get(f"{command}@{target}")
        if per_target is not None:
            return per_target
        return responses.get(command, {"success": False, "error": "нет ответа (fake)"})

    monkeypatch.setattr(d, "send_command", fake_send)
    return sent


def _healthy_responses() -> Dict[str, Dict[str, Any]]:
    return {
        "introspect.status": {
            "success": True,
            "process": "p",
            "status": "running",
            "workers": {"w1": {"status": "running"}},
        },
        "introspect.router_stats": {"success": True, "router_stats": full_router_stats()},
        "introspect.queues": {"success": True, "queue_sizes": {"system": 1, "data": 2}},
        "introspect.memory": {
            "success": True,
            "memory": {},
            "pool": {},
            "queues": {},
            "shm_registry": {},
            "os": {"rss": 12345, "vms": 23456, "pid": 1},
        },
        "introspect.observability": {"success": True, "process": "p", "effective": {}, "counters": _quiet_planes()},
    }


def _quiet_planes() -> Dict[str, Any]:
    """Тишина в покое: все классы потери в нуле, ключи ПРИСУТСТВУЮТ (2.V2).

    Ключи с нулями, а не пустая секция: «ключа нет» и «потерь нет» — разные
    факты, и здоровый ответ обязан выглядеть как первый вариант, а не как
    второй (контракт ``_loss_counters_snapshot``).
    """
    return {
        plane: {
            "unresolved_channel_records": 0,
            "channel_write_errors": 0,
            "channel_refused_records": 0,
            "records_without_channels": 0,
            "errors_to_floor": 0,
            "buffer": {"pending": 0, "dropped": 0, "flush_failed": 0},
        }
        for plane in ("logger", "error", "stats")
    }


class TestOverviewShape:
    def test_compact_summary_healthy_system(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert res["success"] is True
        card = res["processes"]["cam"]
        assert card["status"] == "running"
        assert card["workers"] == {"w1": "running"}  # компактно: имя → статус-строка
        assert card["router"]["middleware_dropped"] == 0
        assert "raw" not in json.dumps(card)  # сырые ответы в сводку не протекают
        assert res["anomaly_count"] == 0

    def test_zero_new_ipc_commands(self, monkeypatch) -> None:
        """Fan-out только существующими ручками — новых IPC-команд ноль."""
        d = BackendDriver()
        sent = _fake_backend(monkeypatch, d, procs=["cam", "gui"], responses=_healthy_responses())
        d.system_overview()
        allowed = {
            "state.get_subtree",
            "introspect.status",
            "introspect.router_stats",
            "introspect.queues",
            "introspect.memory",
            # 2.V2: ручка существует с Ф0.3 (BuiltinCommands), сводка её только
            # СПРАШИВАЕТ. Критерий B.3 — «ноль НОВЫХ IPC-команд», а не «ноль вызовов».
            "introspect.observability",
        }
        assert set(sent) <= allowed

    def test_empty_topology_hint(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=[], responses={})
        res = d.system_overview()
        assert res["processes"] == {}
        assert any(a["kind"] == "empty_topology" for a in res["anomalies"])


class TestAnomalies:
    def test_router_dropped_and_queue_depth_detected(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {
            "success": True,
            "router_stats": full_router_stats(sent_ok=5, received=9, middleware_dropped=3, errors=1),
        }
        responses["introspect.queues"] = {"success": True, "queue_sizes": {"data": 120}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert {"router_dropped", "router_errors", "queue_depth"} <= kinds

    def test_tail_transport_loss_is_an_anomaly_without_touching_errors(self, monkeypatch) -> None:
        """Ф7.х.2 (Н-3 верификации корзины): потеря хвоста видна overview.

        По замыслу Ф7.3 транспортные потери хвоста молчат в логах и НЕ растят
        общий ``errors`` — значит, аномалия отсюда и есть единственное место, где
        оператор их увидит. До правки overview был к ним слеп целиком: величина
        класса Б-6 (97 066) доставалась только ручным чтением raw.
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {
            "success": True,
            "router_stats": full_router_stats(
                sent_ok=5,
                received=9,
                middleware_dropped=0,
                errors=0,
                queue_observability_evicted=1744,
                observability_delivery_failed=97066,
            ),
        }
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "observability_loss"]
        assert hits, "потеря хвоста невидима для overview — класс «проглоченный сбой»"
        detail = hits[0]["detail"]
        assert "observability_delivery_failed=97066" in detail
        assert "queue_observability_evicted=1744" in detail
        # Контраст обеих сторон: errors=0 не даёт router_errors — мьют Ф7.х B-3
        # не подменён обратно ложной тревогой.
        assert not any(a["kind"] == "router_errors" for a in res["anomalies"])

    def test_fps_zero_while_running_detected(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        _feed_state(d, "processes.cam.workers.w1.state.fps", 0)  # локальный read-model
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "fps_zero_while_running"]
        assert hits and hits[0]["process"] == "cam"

    def test_fps_zero_on_stopped_process_not_flagged(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = {"success": True, "process": "cam", "status": "stopped", "workers": {}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        _feed_state(d, "processes.cam.workers.w1.state.fps", 0)
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert "fps_zero_while_running" not in kinds  # fps=0 у остановленного — норма
        assert "process_not_running" in kinds

    def test_recovery_and_driver_counters_surface(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        _feed_state(d, "processes.cam.supervisor.event", "recovered")
        d._late_replies = 2  # подставной счётчик driver'а
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert {"recent_recovery", "late_replies"} <= kinds
        assert res["driver"]["late_replies"] == 2

    def test_events_evicted_visible(self, monkeypatch) -> None:
        d = BackendDriver(event_queue_maxlen=2)
        _fake_backend(monkeypatch, d, procs=[], responses={})
        for i in range(5):
            _feed_state(d, "processes.cam.state.fps", i)  # переполняем кольца
        res = d.system_overview()
        assert any(a["kind"] == "events_evicted" for a in res["anomalies"])
        assert res["driver"]["events_evicted"]["state"] == 3

    def test_introspect_failure_is_honest(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        del responses["introspect.router_stats"]  # ручка «не отвечает» (fake error)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["ok"] is False
        assert any(a["kind"] == "introspect_failed" for a in res["anomalies"])

    def test_missing_router_stats_is_loud_not_zero(self, monkeypatch) -> None:
        """Ручка ответила успехом, но без секции счётчиков → counter_missing.

        Плечо «OFF» пары: раньше такой ответ давал ``sent_ok=0`` и НИ ОДНОЙ аномалии
        — «0 и тишина», неотличимое от доказанного «трафика не было».
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {"success": True, "process": "cam"}  # секции нет
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        hits = [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert hits, "отсутствие счётчиков обязано быть слышно"
        assert hits[0]["process"] == "cam"
        assert "sent_ok" in hits[0]["detail"]
        assert "ручка ответила" in hits[0]["detail"], "причина обязана отличать «не ответила» от «форма разошлась»"

        card = res["processes"]["cam"]
        assert card["router"]["sent_ok"] is None, "нет показания ≠ ноль"
        assert card["missing"] == {"router": list(ROUTER_COUNTERS)}

    def test_healthy_shape_has_no_missing_key(self, monkeypatch) -> None:
        """Плечо «ON» той же пары: полная форма → ни аномалии, ни ключа missing."""
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert not [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert "missing" not in res["processes"]["cam"], "шум в здоровой сводке недопустим"
        assert res["processes"]["cam"]["router"]["sent_ok"] == 10

    def test_missing_queue_sizes_flagged(self, monkeypatch) -> None:
        """Пустые очереди и отсутствующая секция очередей — разные факты."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.queues"] = {"success": True, "process": "cam"}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert hits and "queue_sizes" in hits[0]["detail"]
        assert res["processes"]["cam"]["queues"] is None

    def test_none_counters_do_not_crash_thresholds(self, monkeypatch) -> None:
        """Пороговые проверки None-safe: сводка обязана собраться, а не упасть.

        До строгого края ``rs.middleware_dropped > 0`` было сравнением int'а;
        с ``None`` оно бросило бы TypeError и убило первую команду сессии.
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {"success": True, "router_stats": {"sent_ok": 3}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["success"] is True
        kinds = {a["kind"] for a in res["anomalies"]}
        assert "router_dropped" not in kinds, "None — не превышение порога"
        assert "router_errors" not in kinds
        assert "counter_missing" in kinds

    def test_memory_failure_flags_process(self, monkeypatch) -> None:
        """Отказ introspect.memory — тоже introspect_failed, а не тихий memory_ok=False.

        Ревью фазы B: mem.ok выпадал из агрегата ok — агент, читающий только
        ok/anomalies, считал процесс здоровым при сломанном memory-канале.
        """
        d = BackendDriver()
        responses = _healthy_responses()
        del responses["introspect.memory"]
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["ok"] is False
        hits = [a for a in res["anomalies"] if a["kind"] == "introspect_failed"]
        assert hits and "memory" in hits[0]["detail"]


class TestEffectiveHz:
    """Task 3.2 — effective_hz per-process в сводке + аномалия hz_degraded (пара ON/OFF)."""

    @staticmethod
    def _status_with_workers(workers: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "process": "cam", "status": "running", "workers": workers}

    def test_effective_hz_surfaces_in_card(self, monkeypatch) -> None:
        """Ведущий темп процесса виден в карточке — не теряется при схлопывании воркеров."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"fast": {"status": "running", "effective_hz": 21.3}, "slow": {"status": "running", "effective_hz": 0.5}}
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 21.3  # максимум по воркерам — ведущий темп
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_hz_degraded_flagged_below_target(self, monkeypatch) -> None:
        """ON-плечо: effective_hz ниже доли target → hz_degraded с названным воркером."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 5.0, "target_interval_ms": 33.0}}  # target ~30 Гц, 5 < 15
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]
        assert hits and hits[0]["process"] == "cam"
        assert "w1" in hits[0]["detail"]

    def test_hz_at_target_not_flagged(self, monkeypatch) -> None:
        """OFF-плечо той же пары: темп у цели → карточка несёт hz, аномалии нет."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 25.0, "target_interval_ms": 33.0}}  # 25 >= 15
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 25.0
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_hz_without_target_not_judged(self, monkeypatch) -> None:
        """Воркер без target порогом не судится: hz в карточке есть, hz_degraded — нет."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 0.1}}  # медленно, но не с чем сравнить
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 0.1
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_no_hz_reported_is_none(self, monkeypatch) -> None:
        """Воркер без effective_hz → hz=None (running-процесс без темпа — сам по себе сигнал)."""
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] is None

    def test_seven_process_summary_under_byte_cap(self, monkeypatch) -> None:
        """Приёмка: свод 7 процессов с воркерами+hz остаётся под RESPONSE_BYTE_CAP."""
        from backend_ctl.mcp_tools import RESPONSE_BYTE_CAP

        procs = [f"proc_{i}" for i in range(7)]
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"capture": {"status": "running", "effective_hz": 21.3, "target_interval_ms": 33.0}}
        )
        _fake_backend(monkeypatch, d := BackendDriver(), procs=procs, responses=responses)
        res = d.system_overview()
        assert all("hz" in res["processes"][p] for p in procs)
        payload = json.dumps(res, ensure_ascii=False).encode("utf-8")
        assert len(payload) < RESPONSE_BYTE_CAP, f"свод {len(payload)}Б превысил cap {RESPONSE_BYTE_CAP}"


class TestOverviewResilience:
    """Task 5.3 — сводка не падает целиком и не помнит старые беды вечно."""

    def test_throwing_process_does_not_kill_whole_overview(self, monkeypatch) -> None:
        """Исключение по ОДНОМУ процессу → у него error-секция, остальные собраны.

        Контракт модуля — best-effort, но raise внутри пула (разрыв связи, кривой ответ)
        пробивался через pool.map и ронял ВЕСЬ overview: первая команда сессии падала
        целиком из-за одного больного процесса.
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam", "плохой"], responses=_healthy_responses())

        healthy_worker_status = d.worker_status

        def boom(proc: str, **kw: Any) -> Any:
            if proc == "плохой":
                raise ConnectionError("процесс не отвечает")
            return healthy_worker_status(proc, **kw)

        monkeypatch.setattr(d, "worker_status", boom)
        res = d.system_overview()

        assert res["success"] is True, "сводка обязана собраться, несмотря на больной процесс"
        assert res["processes"]["cam"]["status"] == "running", "здоровый процесс обязан быть собран"
        bad = res["processes"]["плохой"]
        assert bad["ok"] is False
        assert "ConnectionError" in bad["error"], "причина обязана быть названа, а не проглочена"
        assert any(a["kind"] == "introspect_failed" and a.get("process") == "плохой" for a in res["anomalies"])

    def test_cumulative_counter_flags_once_not_forever(self, monkeypatch) -> None:
        """Счётчик тикнул один раз → аномалия в первой сводке, но не во второй.

        Счётчики driver'а кумулятивны: раньше одна давняя ошибка светилась в КАЖДОЙ
        последующей сводке, и свежая беда была неотличима от старого шрама.
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())

        d._late_replies = 2  # подставной счётчик driver'а
        first = d.system_overview()
        assert any(a["kind"] == "late_replies" for a in first["anomalies"]), "первый раз обязан быть виден"
        assert first["driver"]["late_replies"] == 2, "lifetime-значение обязано остаться в ответе"
        assert first["driver"]["deltas"]["late_replies"] == 2

        second = d.system_overview()
        assert not any(a["kind"] == "late_replies" for a in second["anomalies"]), (
            "старый шрам не должен светиться снова"
        )
        assert second["driver"]["late_replies"] == 2, "lifetime-значение никуда не девается"
        assert second["driver"]["deltas"]["late_replies"] == 0

        d._late_replies = 5  # новая беда — снова видна
        third = d.system_overview()
        assert any(a["kind"] == "late_replies" for a in third["anomalies"]), "прирост обязан снова поднять аномалию"
        assert third["driver"]["deltas"]["late_replies"] == 3


# =============================================================================
# 2.V2 — тишина в покое как живой инвариант
# =============================================================================


class TestObservabilitySilence:
    """Ненулевой класс потери наблюдаемости обязан быть виден ПЕРВОЙ командой сессии.

    Резидуал P3 (свежий ErrorManager давал два ``unresolved_channel_records`` в
    полном покое) прожил незамеченным всю Ф0 ровно потому, что спросить об этом
    снаружи было нечем: счётчики читал только тест.
    """

    def test_quiet_process_raises_nothing(self, monkeypatch) -> None:
        """Контроль к остальным: в тишине аномалий нет, а секция ЕСТЬ и пуста.

        Без этого теста «аномалия найдена» ничего не стоит: детектор, который
        ругается всегда, неотличим от сломанного.
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert res["processes"]["cam"]["observability_losses"] == {}
        assert not [a for a in res["anomalies"] if a["kind"].startswith("observability")]

    def test_each_loss_class_is_named_with_its_plane(self, monkeypatch) -> None:
        responses = _healthy_responses()
        planes = _quiet_planes()
        planes["logger"]["unresolved_channel_records"] = 3
        planes["error"]["errors_to_floor"] = 1
        planes["stats"]["buffer"]["dropped"] = 7
        responses["introspect.observability"] = {"success": True, "counters": planes}
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        losses = res["processes"]["cam"]["observability_losses"]
        assert losses == {
            "logger": {"unresolved_channel_records": 3},
            "error": {"errors_to_floor": 1},
            "stats": {"buffer.dropped": 7},
        }
        hits = [a for a in res["anomalies"] if a["kind"] == "observability_loss"]
        assert len(hits) == 3, hits
        details = " | ".join(a["detail"] for a in hits)
        for expected in ("unresolved_channel_records=3", "errors_to_floor=1", "buffer.dropped=7"):
            assert expected in details, details

    def test_lifetime_value_keeps_flagging_unlike_driver_counters(self, monkeypatch) -> None:
        """Потеря наблюдаемости — не шрам: она светится и во второй сводке.

        Сознательно иначе, чем кумулятивные счётчики driver'а (Task 5.3): там
        прирост отделяет свежую беду от старой, здесь «случилось давно» не делает
        потерю записи приемлемой.
        """
        responses = _healthy_responses()
        planes = _quiet_planes()
        planes["logger"]["channel_write_errors"] = 2
        responses["introspect.observability"] = {"success": True, "counters": planes}
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)

        first = d.system_overview()
        second = d.system_overview()
        for res in (first, second):
            assert any(a["kind"] == "observability_loss" for a in res["anomalies"])

    def test_unavailable_handle_is_not_silence(self, monkeypatch) -> None:
        """«Не спросили» обязано отличаться от «потерь нет».

        Молчание при неответившей ручке делало бы процесс, которому команду не
        задали, самым здоровым в сводке.
        """
        responses = _healthy_responses()
        responses["introspect.observability"] = {"success": False, "error": "нет такой команды"}
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        assert res["processes"]["cam"]["observability_losses"] is None
        assert any(a["kind"] == "observability_unavailable" for a in res["anomalies"])

    def test_answered_without_counters_section_is_a_shape_mismatch(self, monkeypatch) -> None:
        """Ручка ответила, секции ``counters`` нет — расхождение формы, не тишина."""
        responses = _healthy_responses()
        responses["introspect.observability"] = {"success": True, "effective": {}}
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        assert res["processes"]["cam"]["observability_losses"] == {}
        assert any(a["kind"] == "counter_missing" and "observability" in a["detail"] for a in res["anomalies"]), res[
            "anomalies"
        ]

    def test_loss_keys_match_the_real_publisher(self) -> None:
        """Фейк выше проверяет ФОРМУ; этот тест связывает её с ЖИВЫМ публикатором.

        Правило проекта: где командная поверхность тестируется на фейках, нужен
        один тест на реальных объектах — иначе переименование счётчика во
        фреймворке оставляет все тесты зелёными, а фича мертва. Ровно так уже
        было: правило читало ``drops_count`` при реальном ``drops``.
        """
        import tempfile
        from pathlib import Path

        from backend_ctl.protocol import OBSERVABILITY_BUFFER_LOSS_KEYS, OBSERVABILITY_LOSS_KEYS
        from multiprocess_framework.modules.logger_module.core.log_config import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_counters,
        )

        tmp = Path(tempfile.mkdtemp())
        logger = LoggerManager(config=LoggerManagerConfig(app_name="silence_probe", log_directory=str(tmp)))
        try:
            plane = observability_counters(logger=logger)["logger"]
        finally:
            logger.shutdown()

        # Не «хотя бы один», а поимённо: плоскость логов обязана публиковать все
        # ключи перечня.
        for key in OBSERVABILITY_LOSS_KEYS:
            assert key in plane, f"логгер перестал публиковать {key!r} — детектор 2.V2 ослеп на этот класс"
        # Ф7.х.2: буфера ЗАПИСИ у логгера больше нет — ``BatchBuffer`` снят
        # (Ф7.4), нормализация в ``_plane_counters`` его секцию не производит.
        # Отсутствие и есть контракт: вернувшийся ключ значил бы, что буфер
        # воскрес (или что фальшивка снова кормит нормализацию, как до Ф7.х).
        # Прежняя редакция требовала здесь buffer.dropped/flush_failed — её
        # посылка истекла вместе с буфером.
        assert "buffer" not in plane, "у плоскости логов снова появился буфер — батчинг воскрес?"
        # Перечень буферных потерь остаётся для плоскости статистики (окно
        # агрегации живо, его ``flush_failed`` публикуется); чтение защищено —
        # отсутствие ключа у плоскости без буфера не расхождение формы.
        assert "flush_failed" in OBSERVABILITY_BUFFER_LOSS_KEYS

    def test_all_three_fresh_planes_are_silent_for_real(self) -> None:
        """Приёмка 2.V2 на живых менеджерах: три плоскости в покое молчат.

        Инвариант «тишина в покое» на РЕАЛЬНЫХ объектах, а не на подставном
        ответе. Плоскость ошибок здесь не для симметрии: именно она и была
        резидуалом P3 — свежий ``ErrorManager`` наследовал от конфига логов
        скоупы со ссылками на каналы, которых у него нет, и давал два
        ``unresolved_channel_records`` не сделав ничего. Сорвётся тест ровно так
        же: чей-то дефолт снова начнёт слать записи в несуществующий канал.
        """
        import tempfile
        from pathlib import Path

        from backend_ctl.protocol import ObservabilityCounters
        from multiprocess_framework.modules.error_module.configs.error_manager_config import ErrorManagerConfig
        from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
        from multiprocess_framework.modules.logger_module.core.log_config import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_counters,
        )
        from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager

        tmp = Path(tempfile.mkdtemp())
        logger = LoggerManager(config=LoggerManagerConfig(app_name="silence_probe", log_directory=str(tmp)))
        errors = ErrorManager(
            config=ErrorManagerConfig(
                app_name="silence_probe",
                critical_file_path=str(tmp / "critical.log"),
                error_file_path=str(tmp / "errors.log"),
                warnings_file_path=str(tmp / "warnings.log"),
            )
        )
        errors.initialize()
        stats = StatsManager()
        stats.initialize()
        try:
            for manager in (logger, errors, stats):
                manager.flush()
            counters = observability_counters(logger=logger, error=errors, stats=stats)
        finally:
            errors.shutdown()
            logger.shutdown()

        # Все три секции обязаны присутствовать: пустой ``nonzero`` при пустом
        # ``counters`` означал бы «никого не спросили», а не «все молчат».
        assert set(counters) == {"logger", "error", "stats"}, counters
        parsed = ObservabilityCounters.from_response({"success": True, "counters": counters})
        assert parsed.nonzero == {}, f"свежие плоскости шумят в покое: {parsed.nonzero}"
