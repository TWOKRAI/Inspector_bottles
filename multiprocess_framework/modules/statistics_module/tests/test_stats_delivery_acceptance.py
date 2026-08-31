# -*- coding: utf-8 -*-
"""
Приёмочные тесты задачи 2.1 (`plans/telemetry-stage6.md`) — доставка `kind=stats`
(снапшот окна `StatsManager`) в `ObservabilityStore` и живой хвост через канал
`hub_stats`.

Писаны НЕЗАВИСИМЫМ тестировщиком от критериев приёмки, БЕЗ чтения:
`record_display.py`, `drain_adapter.py`, `observability_hub.py`,
`hub_stats_channel.py`, `stats_manager.py`, `observability_wiring.py`,
`test_stats_aggregate_delivery.py`, `test_hub_stats_channel.py`.

Контракт восстановлен из `statistics_module/README.md`, `interfaces.py`,
`channel_routing_module/observability/README.md`,
`docs/observability/CONNECTORS.md` и уже существующих (разрешённых) тестов
`process_module/tests/test_observability_wiring.py` /
`test_observability_store_wiring.py` — в частности, из
`test_wire_attaches_the_hub_to_a_real_stats_manager`, показывающего, что СЫРАЯ
запись `hub.drain_all()["stats"]` для снапшота окна несёт ключ `metrics` (список
`{"name": ..., ...}`), а не одиночный `metric`/`value`, — этим объясняется,
почему точная форма `extra` после нормализации `record_display` здесь не
предполагается дословно: метрики ищутся ПОИМЕННО, где бы они ни лежали внутри
`extra`, а не по фиксированному пути ключей.

Темп агрегации везде взят далеко от дефолта (`aggregation_interval=3600.0` —
дефолт 5.0) — окна закрываются ЯВНЫМ вызовом `stats._buffer.flush_all()` (тот
же приём, что в `test_observability_wiring.py::test_wire_attaches_the_hub_to_a_real_stats_manager`
и в `test_tempo_knob.py`), а не ожиданием фонового таймера.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    drain_process_observability,
    wire_process_observability,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager
from multiprocess_framework.modules.worker_module.core.worker_manager import WorkerManager


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _stats_manager(tmp_path, name: str, **cfg_over: Any) -> StatsManager:
    """StatsManager с окном далеко от дефолта (3600 с) — flush только ручной."""
    cfg: Dict[str, Any] = {
        "enable_logging": False,
        "aggregation_interval": 3600.0,
        "channels": {"file_stats": {"type": "file", "file_path": str(tmp_path / f"{name}.json")}},
    }
    cfg.update(cfg_over)
    mgr = StatsManager(name, config=cfg)
    mgr.initialize()
    return mgr


def _wired(tmp_path, name: str, **cfg_over):
    """StatsManager + hub + adapter через ПРОДАКШН-функцию `wire_process_observability`
    (не мок) — та же проводка, что использует composition root процесса."""
    stats = _stats_manager(tmp_path, name, **cfg_over)
    worker = WorkerManager(f"workers_{name}")
    hub, adapter = wire_process_observability(name, worker, None, stats, None)
    return stats, worker, hub, adapter


def _collect_metric_entries(node: Any) -> List[Dict[str, Any]]:
    """Рекурсивно найти в JSON-структуре dict-элементы вида метрики (есть строковый 'name').

    Не завязано на конкретный путь ключей внутри `extra` (например `extra['value']`
    против `extra['metrics']`) — форма `extra` после нормализации `record_display`
    не была прочитана и не предполагается дословно; ищем ПОИМЕНОВАННЫЕ записи метрик
    там, где они лежат.
    """
    found: List[Dict[str, Any]] = []
    if isinstance(node, dict):
        if "name" in node and isinstance(node["name"], str):
            found.append(node)
        for v in node.values():
            found.extend(_collect_metric_entries(v))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_metric_entries(item))
    return found


def _metric_entries_by_name(row: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    entries = _collect_metric_entries(row.get("extra", {}))
    return [e for e in entries if e.get("name") == name]


# ---------------------------------------------------------------------------
# Критерий 1+2: ОДНА запись на снапшот (не по метрике), доезжает до стора
# ---------------------------------------------------------------------------


class TestOneRecordPerSnapshotReachesStore:
    def test_attach_registers_hub_stats_channel(self, tmp_path):
        from multiprocess_framework.modules.channel_routing_module.observability import (
            ObservabilityHub,
        )

        stats = _stats_manager(tmp_path, "attach_ch")
        try:
            hub = ObservabilityHub("attach_ch")
            assert stats.attach_observability_hub(hub) is True
            assert "hub_stats" in stats._channel_registry.names()
        finally:
            stats.shutdown()

    def test_three_metrics_one_window_yield_one_stats_row_not_three(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "onerow")
        store = ObservabilityStore(str(tmp_path / "onerow.db"))
        try:
            stats.record_metric("acc.alpha.first", 5)
            stats.record_metric("acc.beta.second", 7)
            stats.gauge("acc.gamma.third", 42.0)

            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1, f"ожидалась ОДНА запись на снапшот окна с тремя метриками, получено {len(rows)}"
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 3: СОДЕРЖИМОЕ, а не наличие — имена, значения, число метрик в окне
# ---------------------------------------------------------------------------


class TestSnapshotContentIsReal:
    def test_names_and_values_are_readable_from_the_store_row(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "content")
        store = ObservabilityStore(str(tmp_path / "content.db"))
        try:
            stats.record_metric("acc.content.counter", 713)
            stats.gauge("acc.content.gauge", 271828.0)

            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1
            row = rows[0]

            assert row["message"] != "", "message='' — маркер провала по критерию 3 (пустая запись)"
            assert row["extra"] != {"value": None}, (
                "extra={'value': None} — маркер провала по критерию 3, доехала пустая обёртка"
            )

            counter_entries = _metric_entries_by_name(row, "acc.content.counter")
            gauge_entries = _metric_entries_by_name(row, "acc.content.gauge")
            assert counter_entries, f"метрика 'acc.content.counter' не найдена в extra={row['extra']}"
            assert gauge_entries, f"метрика 'acc.content.gauge' не найдена в extra={row['extra']}"

            counter_values = [v for v in counter_entries[0].values() if isinstance(v, (int, float))]
            gauge_values = [v for v in gauge_entries[0].values() if isinstance(v, (int, float))]
            assert any(v == 713 for v in counter_values), f"значение counter=713 не найдено среди {counter_values}"
            assert any(v == pytest.approx(271828.0) for v in gauge_values), (
                f"значение gauge=271828.0 не найдено среди {gauge_values}"
            )
        finally:
            stats.shutdown()
            store.close()

    def test_metric_count_in_window_matches_recorded_names(self, tmp_path):
        """Число метрик в окне — читается по факту ПОИМЕНОВАННО найденных записей."""
        stats, _worker, hub, adapter = _wired(tmp_path, "count_in_window")
        store = ObservabilityStore(str(tmp_path / "count_in_window.db"))
        names = ["acc.win.m1", "acc.win.m2", "acc.win.m3", "acc.win.m4"]
        try:
            for i, n in enumerate(names, start=1):
                stats.record_metric(n, i)

            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1
            entries = _collect_metric_entries(rows[0].get("extra", {}))
            found_names = {e.get("name") for e in entries if e.get("name") in names}
            assert found_names == set(names), (
                f"в окне записано {len(names)} метрик {names}, в сторе поимённо найдено только {found_names}"
            )
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 4: единица record_timing — СЕКУНДЫ
# ---------------------------------------------------------------------------


class TestRecordTimingUnitIsSeconds:
    def test_0_0167_seconds_arrives_as_is_not_as_16_7(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "timing_unit")
        store = ObservabilityStore(str(tmp_path / "timing_unit.db"))
        try:
            stats.record_timing("acc.timing.metric", 0.0167)
            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1
            entries = _metric_entries_by_name(rows[0], "acc.timing.metric")
            assert entries, f"метрика тайминга не найдена: {rows[0]['extra']}"
            values = [v for v in entries[0].values() if isinstance(v, (int, float))]
            assert any(v == pytest.approx(0.0167, abs=1e-6) for v in values), (
                f"0.0167 c не найдено среди значений {values} — единица разъехалась"
            )
            assert not any(v == pytest.approx(16.7, abs=1e-3) for v in values), (
                f"найдено значение ~16.7 среди {values} — похоже на секунды, перепутанные с мс (x1000)"
            )
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 5: предохранитель петли — снапшот не должен вернуться в StatsManager
# ---------------------------------------------------------------------------


class TestNoFeedbackLoopThroughDrainAdapter:
    def test_stats_row_count_grows_linearly_across_windows_not_geometrically(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "loopguard")
        store = ObservabilityStore(str(tmp_path / "loopguard.db"))
        try:
            windows = 4
            for w in range(1, windows + 1):
                stats.record_metric("acc.loop.metric", 3)
                stats._buffer.flush_all()
                drain_process_observability(hub, adapter, store)

                rows = store.count(kind="stats")
                assert rows == w, f"после {w} окна(-он) эмиссий ожидалось {w} строк(и) в сторе, получено {rows}"
                # ВНИМАНИЕ (правка автора задачи после слом-инъекции): счёт СТРОК
                # петлю НЕ ловит — со снятым предохранителем строки тоже растут
                # линейно (замер: 1,2,3,4,5). Прежняя формулировка обещала здесь
                # обнаружение петли и была неправдой. Настоящий признак — серии
                # внутри записи, см. тест ниже.
        finally:
            stats.shutdown()
            store.close()

    def test_fed_back_snapshot_does_not_inflate_the_next_windows_count(self, tmp_path):
        """Одинаковая явная эмиссия в каждом окне обязана давать ОДИНАКОВОЕ значение,
        а не растущее — иначе снапшот окна N возвращается в окно N+1."""
        stats, _worker, hub, adapter = _wired(tmp_path, "loopguard_value")
        store = ObservabilityStore(str(tmp_path / "loopguard_value.db"))
        try:
            for _ in range(3):
                stats.record_metric("acc.loop.value.metric", 5)
                stats._buffer.flush_all()
                drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats", newest_first=False)
            assert len(rows) == 3
            for i, row in enumerate(rows, start=1):
                entries = _metric_entries_by_name(row, "acc.loop.value.metric")
                assert entries, f"метрика отсутствует в окне {i}: {row}"
                nums = [v for v in entries[0].values() if isinstance(v, (int, float))]
                assert any(v == 5 for v in nums), (
                    f"окно {i}: ожидался count=5 (эмиссия не менялась), получено {nums} — "
                    f"похоже на накопление через обратную петлю"
                )
        finally:
            stats.shutdown()
            store.close()

    def test_no_nameless_phantom_series_appears_from_the_second_window_on(self, tmp_path):
        """НАСТОЯЩИЙ сторож петли (добавлен автором задачи после слом-инъекции).

        Два теста выше остались зелёными при полностью снятом предохранителе:
        оба судили по строкам и по значению своей метрики, а вред у петли иной.
        У записи-агрегата нет ни `metric`, ни `value`, ни `metric_type`, поэтому
        адаптер сворачивает весь снапшот в ОДНУ безымянную метрику
        `record_metric("", 1)`. Замер со снятой проверкой, 5 окон: строк
        1,2,3,4,5 (линейно), а серий в записи 1 → 2 → 2 → 2 → 2, где вторая —
        `('', 1.0)`. Судить надо ИМЕНА серий, и начиная со ВТОРОГО окна.
        """
        stats, _worker, hub, adapter = _wired(tmp_path, "phantom")
        store = ObservabilityStore(str(tmp_path / "phantom.db"))
        try:
            for _ in range(3):
                stats.record_metric("acc.phantom.metric", 7)
                stats._buffer.flush_all()
                drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats", newest_first=False)
            assert len(rows) == 3
            for i, row in enumerate(rows, start=1):
                extra = row["extra"]
                if isinstance(extra, str):
                    import json as _json

                    extra = _json.loads(extra)
                names = sorted(m.get("name") for m in extra["metrics"])
                assert names == ["acc.phantom.metric"], (
                    f"окно {i}: в записи лишние серии {names} — снапшот вернулся в StatsManager"
                )
        finally:
            stats.shutdown()
            store.close()

    def test_worker_metric_and_own_snapshot_coexist_without_double_counting(self, tmp_path):
        """Реалистичная смешанная проводка: worker пишет метрику напрямую в hub,
        StatsManager параллельно кладёт туда же СВОЙ снапшот окна. Оба обязаны
        доехать по назначению, не заразив друг друга."""
        stats, worker, hub, adapter = _wired(tmp_path, "mixed_source")
        store = ObservabilityStore(str(tmp_path / "mixed_source.db"))
        try:
            worker._record_metric("acc.mixed.worker_metric", 1)
            stats.record_metric("acc.mixed.own_metric", 2)
            stats._buffer.flush_all()

            drain_process_observability(hub, adapter, store)

            assert stats.get_metric("acc.mixed.worker_metric") is not None, (
                "метрика worker'а не доехала до StatsManager через drain+adapter"
            )
            own = stats.get_metric("acc.mixed.own_metric")
            assert own is not None and own["count"] == 2.0, (
                f"acc.mixed.own_metric изменился после drain: {own} — похоже на возврат "
                f"собственного снапшота StatsManager'у"
            )
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 6: снапшот находится полнотекстовым поиском по имени метрики
# ---------------------------------------------------------------------------


class TestSnapshotFindableBySearch:
    def test_search_by_metric_name_finds_the_snapshot_row(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "searchable")
        store = ObservabilityStore(str(tmp_path / "searchable.db"))
        try:
            stats.record_metric("acc.findme.uniquename", 1)
            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows_before = store.list_records(kind="stats")
            assert len(rows_before) == 1
            expected_id = rows_before[0]["id"]

            found = store.search("findme")
            found_ids = {r["id"] for r in found}
            assert expected_id in found_ids, (
                f"полнотекстовый поиск по 'findme' не нашёл запись снапшота (id={expected_id}); найдено: {found}"
            )
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 7: пустое окно в стор не едет
# ---------------------------------------------------------------------------


class TestEmptyWindowDoesNotReachStore:
    def test_flush_with_no_emissions_produces_no_stats_row(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "emptywin")
        store = ObservabilityStore(str(tmp_path / "emptywin.db"))
        try:
            stats._buffer.flush_all()  # окно пустое — ни одной эмиссии
            drain_process_observability(hub, adapter, store)

            assert store.count(kind="stats") == 0, "пустое окно не должно доехать до стора (задача 3.2, Р-4г)"
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 8: канал переживает reconfigure()
# ---------------------------------------------------------------------------


class TestChannelSurvivesReconfigure:
    def test_snapshot_still_reaches_store_after_reconfigure(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "reconf")
        store = ObservabilityStore(str(tmp_path / "reconf.db"))
        try:
            new_cfg = {
                "enable_logging": False,
                "aggregation_interval": 1800.0,
                "channels": {"file_stats": {"type": "file", "file_path": str(tmp_path / "reconf2.json")}},
            }
            assert stats.reconfigure(new_cfg) is True

            stats.record_metric("acc.reconf.metric", 9)
            stats._buffer.flush_all()
            drain_process_observability(hub, adapter, store)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1, "после reconfigure() канал hub_stats обязан продолжать доставку снапшота"
            entries = _metric_entries_by_name(rows[0], "acc.reconf.metric")
            assert entries, f"метрика после reconfigure не найдена: {rows[0]['extra']}"
        finally:
            stats.shutdown()
            store.close()


# ---------------------------------------------------------------------------
# Критерий 9: оператор снимает канал дверью channels.hub_stats.enabled=false
# ---------------------------------------------------------------------------


class TestOperatorCanDisableHubStatsChannel:
    def test_disabled_via_config_blocks_delivery_enabled_allows_it(self, tmp_path):
        stats_on, _w_on, hub_on, adapter_on = _wired(tmp_path, "toggle_on")
        store_on = ObservabilityStore(str(tmp_path / "toggle_on.db"))

        stats_off, _w_off, hub_off, adapter_off = _wired(tmp_path, "toggle_off")
        store_off = ObservabilityStore(str(tmp_path / "toggle_off.db"))
        try:
            # Контроль: канал не тронут — снапшот обязан доехать.
            stats_on.record_metric("acc.toggle.metric", 1)
            stats_on._buffer.flush_all()
            drain_process_observability(hub_on, adapter_on, store_on)
            assert store_on.count(kind="stats") == 1, "контроль: без снятия канала снапшот обязан доехать"

            # Снимаем канал явной дверью конфига.
            reconf_ok = stats_off.reconfigure(
                {
                    "enable_logging": False,
                    "aggregation_interval": 3600.0,
                    "channels": {
                        "file_stats": {"type": "file", "file_path": str(tmp_path / "toggle_off.json")},
                        "hub_stats": {"enabled": False},
                    },
                }
            )
            assert reconf_ok is True

            stats_off.record_metric("acc.toggle.metric", 1)
            stats_off._buffer.flush_all()
            drain_process_observability(hub_off, adapter_off, store_off)
            assert store_off.count(kind="stats") == 0, (
                "channels.hub_stats.enabled=false обязан снимать доставку снапшота"
            )
        finally:
            stats_on.shutdown()
            stats_off.shutdown()
            store_on.close()
            store_off.close()


# ---------------------------------------------------------------------------
# Критерий 10: процесс без hub'а — штатное состояние
# ---------------------------------------------------------------------------


class TestProcessWithoutHubIsUnaffected:
    def test_record_and_flush_do_not_raise_without_a_hub(self, tmp_path):
        stats = _stats_manager(tmp_path, "nohub")
        try:
            stats.record_metric("acc.nohub.metric", 1)
            stats.increment("acc.nohub.counter")
            stats._buffer.flush_all()  # не должно упасть без hub'а
        finally:
            stats.shutdown()


# ---------------------------------------------------------------------------
# Критерий 11: последнее окно доезжает при финальном дренаже (stats_to_flush)
# ---------------------------------------------------------------------------


class TestFinalWindowFlushOnStop:
    def test_stats_to_flush_delivers_the_last_open_window_before_shutdown(self, tmp_path):
        stats, _worker, hub, adapter = _wired(tmp_path, "finalflush")
        store = ObservabilityStore(str(tmp_path / "finalflush.db"))
        try:
            stats.record_metric("acc.final.metric", 21)
            # Окно НЕ закрыто вручную — снапшота в hub'е ещё нет.
            drain_process_observability(hub, adapter, store, None, stats_to_flush=stats)

            rows = store.list_records(kind="stats")
            assert len(rows) == 1, (
                "финальный дренаж со stats_to_flush=stats_manager обязан закрыть последнее "
                "открытое окно и доставить его снапшот в стор"
            )
            entries = _metric_entries_by_name(rows[0], "acc.final.metric")
            assert entries, f"метрика последнего окна не найдена: {rows[0]['extra']}"
        finally:
            stats.shutdown()
            store.close()
