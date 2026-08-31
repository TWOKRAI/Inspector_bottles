# -*- coding: utf-8 -*-
"""Задача 3.4 плана ``telemetry-stage6``: персист АДРЕСНОЙ (per-process) publish-дельты.

Написаны НЕЗАВИСИМЫМ тестировщиком, не видевшим реализации, ТОЛЬКО по критериям
приёмки, переданным оркестратором. Запрещено к чтению (явно, не «не подглядывать
вообще»): ``process/process_manager_process.py``, ``process/observability_broker.py``,
``plans/telemetry-stage6.md`` и всё под ``plans/``, любой ``DECISIONS.md``, ``git
diff``/``log -p``/``show``. Реализации задачи 3.4 на момент письма НЕ существует —
эта суита ОБЯЗАНА быть красной; зелёный прогон здесь означал бы, что тест закрепил
не то поведение.

Дефект, который чинит задача (репро с живого стенда, для понимания контракта, не
намёк на реализацию): фан-аут (без ``target``) правку PM персистит и доигрывает
пересозданному ребёнку — так уже работает и покрыто существующей суитой
(``test_telemetry_broadcast.py::TestRuntimeDeltaPersist``, в частности
``test_addressed_publish_not_persisted`` — она же документирует ТЕКУЩЕЕ отсутствие
персиста адресной правки как факт до фикса). Адресную (``target=<процесс>``) правку
PM сегодня НЕ персистит вовсе — respawn адресата тихо теряет её и откатывается на
boot-конфиг.

Гипотеза модели тестировщика (не проверена по коду, только по контракту в задании):
respawn = полная пересборка ребёнка через ``apply_topology`` (тот же путь, что уже
доигрывает глобальную дельту, см. ``test_apply_topology_replays_delta_to_children``
в разрешённом файле). Лестница приоритетов «файл → глобальная дельта → адресная
дельта» проверяется не как отдельный «файловый» слой (боевой boot-конфиг ребёнка
в этом mock-харнессе недостижим без чтения реализации — см. отчёт тестировщика),
а как ПОРЯДОК ДОСТАВКИ: адресная дельта обязана дойти до пересозданного ребёнка
ПОСЛЕ глобальной, так что при слиянии на её стороне её значение окажется
эффективным (последним применённым). Если реализация резолвит лестницу иначе
(например одним слитым конвертом, а не двумя по отдельности) — часть этих тестов
даст неверный диагноз, и это стоит явно свести на очной ставке с автором.

Харнесс скопирован/адаптирован (разрешено правилами задания) с плана расстановки
``test_ready_gate_redelivery.py::_pm_with_children`` (единый хронологический
журнал broadcast+send_to_process — без него нельзя проверить ПОРЯДОК доставки
между веерным и адресным путём) и ``test_telemetry_broadcast.py::_pm``
(регистрация детей в shared_resources для видимости fan-out).
"""

from __future__ import annotations

from .conftest import make_pm


class _Comm:
    """Единый хронологический журнал: broadcast и send_to_process — в ОДНОМ списке.

    Раздельные списки (как в ``_CommSpy`` из test_telemetry_broadcast.py) стирают
    относительный порядок между веерным и адресным путём — а лестница приоритетов
    (задача 3.4, критерий 3) наблюдаема именно как порядок доставки.
    """

    def __init__(self, reach: int) -> None:
        self.log: list[dict] = []
        self._reach = reach

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.log.append({"kind": "broadcast", **message})
        return self._reach

    def send_to_process(self, target: str, message) -> bool:
        self.log.append({"kind": "addressed", "target": target, **message})
        return True


def _pm(children: dict):
    """PM с единым comm-журналом + детьми, видимыми через shared_resources (fan-out)."""
    pm = make_pm(children)
    pm.communication = _Comm(reach=len(children))
    for name in children:
        pm.shared_resources.register_process(name, {})
    return pm


def _reconfigure_log(pm) -> list[dict]:
    """Весь журнал ``telemetry.reconfigure`` (веерный + адресный), в порядке отправки."""
    return [row for row in pm.communication.log if row.get("command") == "telemetry.reconfigure"]


def _received_by(pm, name: str) -> list[dict]:
    """Конверты ``telemetry.reconfigure``, которые реально дошли бы до `name`:
    веерные (доходят до ВСЕХ) + адресные, отправленные именно ему — в порядке отправки.
    """
    return [row for row in _reconfigure_log(pm) if row["kind"] == "broadcast" or row.get("target") == name]


def _metric_values(rows: list[dict], metric: str) -> list[float | None]:
    """Значения ``interval_sec`` метрики `metric` по конвертам, в порядке доставки.

    Конверты, не касающиеся `metric` вовсе, пропускаются (в отличие от «нет
    правки» это не значение, а отсутствие мнения этого конкретного конверта).
    """
    out: list[float | None] = []
    for row in rows:
        metrics = row.get("data", {}).get("publish", {}).get("metrics") or {}
        if metric in metrics:
            out.append(metrics[metric].get("interval_sec"))
    return out


def _respawn(pm, *names: str) -> dict:
    """Пересоздать перечисленных детей: тот же набор имён, full-replace через
    FakePlanner (conftest) стопает/чистит/пересоздаёт КАЖДОЕ имя из ``_process_configs``,
    даже если оно есть и в старом, и в новом бланке (ровно так уже используется в
    разрешённом ``test_apply_topology_replays_delta_to_children``)."""
    return pm.apply_topology({"processes": [{"process_name": n, "process_class": f"m.{n.title()}"} for n in names]})


# ---------------------------------------------------------------------------
# Критерий 1 — адресная правка переживает respawn/hot-swap своего адресата
# ---------------------------------------------------------------------------


class TestAddressedDeltaSurvivesRespawn:
    def test_addressed_edit_is_replayed_to_the_respawned_target(self) -> None:
        """ГЛАВНЫЙ acceptance: fps=7.0, адресованный 'lines', доезжает до НОВОГО 'lines'."""
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        assert res["success"] is True  # адресная доставка уже работает сегодня (не то, что чиним)

        pm.communication.log.clear()  # интересует ТОЛЬКО то, что уедет из-за respawn
        result = _respawn(pm, "lines", "seg")
        assert result["success"] is True

        lines_fps = _metric_values(_received_by(pm, "lines"), "fps")
        assert 7.0 in lines_fps, (
            f"адресная правка fps=7.0 не переиграна пересозданному 'lines': {_received_by(pm, 'lines')}"
        )

    def test_addressed_edit_does_not_leak_to_a_neighbour_on_respawn(self) -> None:
        """'seg' не адресат правки 'lines' — respawn не имеет права разослать её всем."""
        pm = _pm({"lines": {"class": "m.Lines"}, "seg": {"class": "m.Seg"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        pm.communication.log.clear()
        _respawn(pm, "lines", "seg")

        seg_fps = _metric_values(_received_by(pm, "seg"), "fps")
        assert 7.0 not in seg_fps, f"адресная правка 'lines' утекла соседу 'seg' при respawn: {_received_by(pm, 'seg')}"


# ---------------------------------------------------------------------------
# Критерий 2 — существующий персист ГЛОБАЛЬНОЙ дельты не сломан новой веткой
# ---------------------------------------------------------------------------


class TestGlobalDeltaPersistenceStillWorks:
    def test_global_edit_still_survives_respawn(self) -> None:
        """Регресс-контроль: фан-аут правка latency_ms всё ещё доигрывается после respawn."""
        pm = _pm({"lines": {"class": "m.Lines"}})
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}})
        assert res["success"] is True

        pm.communication.log.clear()
        _respawn(pm, "lines")

        latency = _metric_values(_received_by(pm, "lines"), "latency_ms")
        assert 11.0 in latency, (
            f"глобальная дельта latency_ms=11.0 перестала доигрываться после введения "
            f"адресного персиста: {_received_by(pm, 'lines')}"
        )


# ---------------------------------------------------------------------------
# Критерий 3 — лестница «файл → глобальная дельта → адресная дельта»
# ---------------------------------------------------------------------------


class TestPrecedenceLadder:
    """Три РАЗНЫХ значения по требованию задания (не совпадение констант).

    «Файловый» (boot) уровень в этом mock-харнессе недостижим напрямую — PM здесь
    не строит боевой proc_dict с секцией telemetry для 'lines' (см. отчёт
    тестировщика, пункт про недостижимые критерии). Наблюдается ДВА уровня из
    трёх: глобальная дельта (3.0) и адресная дельта (7.0, другое значение) — и
    лестница проверяется как ПОРЯДОК доставки пересозданному ребёнку: адресная
    обязана прийти ПОСЛЕ глобальной, чтобы при слиянии на стороне ребёнка её
    значение осталось эффективным (более узкий уровень побеждает более широкий).
    """

    def test_addressed_delta_is_delivered_after_global_delta_for_the_same_metric(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        # Глобальная (широкая) правка fps=3.0 — уровень ниже адресной по лестнице.
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 3.0}}}})
        # Адресная (узкая) правка ТОГО ЖЕ fps, ДРУГОЕ значение — верх лестницы.
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})

        pm.communication.log.clear()
        _respawn(pm, "lines")

        fps_values = _metric_values(_received_by(pm, "lines"), "fps")
        assert fps_values, f"fps ни разу не переигран пересозданному 'lines': {_received_by(pm, 'lines')}"
        assert fps_values[-1] == 7.0, (
            f"последним пересозданному 'lines' обязан прийти АДРЕСНЫЙ fps=7.0 (верх лестницы), "
            f"а не глобальный 3.0 — порядок доставки: {fps_values}"
        )

    def test_mixed_case_global_only_and_addressed_only_metrics_both_survive(self) -> None:
        """Одна метрика тронута ТОЛЬКО глобально, другая — ТОЛЬКО адресно, один ребёнок сразу.

        **Правлен после очной ставки с автором (ревью фазы 3, K-17) — ровно той, которую
        предсказала шапка этого файла:** «если реализация резолвит лестницу одним слитым
        конвертом, часть тестов даст неверный диагноз». Так и вышло, и вскрылось ДВОЙНОЕ
        расхождение, оба раза не в пользу прежней редакции:

        1. тест судил КОНВЕРТЫ на проводе, а не эффект у ребёнка. Прежняя редакция
           писала обе правки в дефолтном режиме ``replace``, и боевой приёмник на них
           отвечает ``{fps: 7.0}`` — ``latency_ms`` теряется НЕЗАВИСИМО от доигрывания
           (``replace`` пересобирает gate из секции целиком, это его документированный
           смысл). То есть тест был зелён на свойстве, которого у системы нет: лишний
           первый конверт доезжал, и его эффект тут же перетирался вторым;
        2. режим ``merge`` — тот, которым ходит операторская дверь (``telemetry_set``), —
           даёт заявленное «оба выжили» по-настоящему. Живая сверка 2026-08-16: адресно
           ``fps=7.0`` + фан-аутом ``latency_ms=11.0`` → после respawn пересозданный
           ``lines`` отдаёт ОБЕ.

        Поэтому проверяется ЭФФЕКТ у боевого приёмника, и в обоих режимах: под ``merge``
        обе метрики обязаны выжить, под ``replace`` — обязана выжить последняя, и это не
        дефект, а контракт.
        """
        from ...process_module.heartbeat.process_heartbeat import ProcessHeartbeat

        def _effective(mode: str) -> dict:
            pm = _pm({"lines": {"class": "m.Lines"}})
            pm._cmd_telemetry_broadcast(
                {"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}, "telemetry_mode": mode}
            )
            pm._cmd_telemetry_broadcast(
                {"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines", "telemetry_mode": mode}
            )
            pm.communication.log.clear()
            _respawn(pm, "lines")

            child = ProcessHeartbeat(None)
            for row in _received_by(pm, "lines"):
                data = row.get("data", {})
                child.reconfigure_telemetry(data["publish"], mode=data.get("telemetry_mode", "replace"))
            return ((child.current_telemetry_publish() or {}).get("metrics")) or {}

        merged = _effective("merge")
        assert merged.get("latency_ms", {}).get("interval_sec") == 11.0, (
            f"глобальная-only метрика latency_ms потеряна в смешанном случае (merge): {merged}"
        )
        assert merged.get("fps", {}).get("interval_sec") == 7.0, (
            f"адресная-only метрика fps потеряна в смешанном случае (merge): {merged}"
        )

        replaced = _effective("replace")
        assert replaced.get("fps", {}).get("interval_sec") == 7.0, f"последняя правка потеряна (replace): {replaced}"
        assert "latency_ms" not in replaced, (
            f"replace обязан снести неупомянутую метрику — иначе его контракт не тот, что документирован: {replaced}"
        )


# ---------------------------------------------------------------------------
# Критерий 4 — сброс (publish=None) гасит ОБА уровня разом
# ---------------------------------------------------------------------------


class TestResetClearsBothLevels:
    def test_fanout_reset_clears_both_global_and_addressed_delta(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"latency_ms": {"interval_sec": 11.0}}}})
        pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"interval_sec": 7.0}}}, "target": "lines"})
        # Сброс — валидная фан-аут команда «выключить gate у всех» (уже так
        # трактуется сегодня, см. test_publish_none_disables_gate_for_all).
        res = pm._cmd_telemetry_broadcast({"publish": None})
        assert res["success"] is True

        pm.communication.log.clear()
        _respawn(pm, "lines")

        received = _received_by(pm, "lines")
        assert received == [], (
            f"после сброса publish=None respawn всё равно доиграл сохранённую дельту "
            f"(глобальную и/или адресную): {received}"
        )


# ---------------------------------------------------------------------------
# Критерий 5 — повторный «reload конфига» без изменений не штормит broadcast'ами
# ---------------------------------------------------------------------------


class TestNoOpReloadStaysQuiet:
    """«Anti-storm» здесь читается как существующее свойство ``apply_topology``:
    без сохранённой ни глобальной, ни адресной дельты повторный reload/hot-swap
    НЕ шлёт ``telemetry.reconfigure`` вовсе (см. разрешённый
    ``test_apply_topology_without_delta_no_replay``). Тест ниже — регресс-щит на
    ЭТО свойство именно после того, как задача 3.4 добавит ветку адресного
    персиста: она не должна начать «доигрывать» пустоту при каждом reload.
    Если «anti-storm» на самом деле — отдельный механизм (дифф файла ДО вызова
    ``apply_topology``, а не сам ``apply_topology``) — это не проверяемо без
    запрещённых файлов, см. отчёт тестировщика.
    """

    def test_repeated_reload_without_any_delta_sends_zero_telemetry_broadcasts(self) -> None:
        pm = _pm({"lines": {"class": "m.Lines"}})

        r1 = _respawn(pm, "lines")
        r2 = _respawn(pm, "lines")

        assert r1["success"] is True
        assert r2["success"] is True
        assert _reconfigure_log(pm) == [], (
            f"повторный reload без единой сохранённой дельты дал telemetry.reconfigure: {_reconfigure_log(pm)}"
        )
