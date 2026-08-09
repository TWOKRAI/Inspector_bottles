# -*- coding: utf-8 -*-
"""B1 — ручка темпа стат-плоскости: пол назван, пересборка действует, readback живой.

Основание — major-3 + major-13 приёмочного ревью 2026-08-09:

* ``AggregationWindow`` создавался ОДИН раз в ``__init__`` с
  ``flush_interval=max(flush_interval, aggregation_interval)``, а
  ``_rebuild_from_config`` пересобирал только каналы — рантайм-правка темпа не
  действовала вовсе (живой замер: 115 → 138 флашей за 187 с при заявленных «30»);
* пол ``max()`` не был объявлен нигде: конфигные 5.0 при дефолтном
  ``flush_interval=10.0`` молча становились 10.0, и ручка врала беззвучно;
* readback темпа брался из конфига, то есть был эхом запроса.

Решение владельца **Р-3(б)**: пол остаётся, но объявляется — в схеме, в WARNING
и в readback'е.

Числа здесь намеренно **вне дефолтов** (5.0 / 10.0): тест на дефолтных числах
проверяет дефолт, а не ручку (урок проекта). Берутся 12.0 / 36.0 / 3.0 / 2.0 —
значения, на которых кандидатные реализации расходятся.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..core.aggregation_window import AggregationWindow
from ..core.stats_manager import StatsManager


class _RecordingLogger:
    """Дубль logger-менеджера, который УМЕЕТ сохранить то, что мог бы потерять.

    Хранит и уровень, и текст, и ``**kwargs`` (там едет штамп ``module``).
    Дубль, выбрасывающий kwargs, делает свойство «запись пришла с адресом»
    непроверяемым в принципе — оплаченный урок задачи A2.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def _record(self, level: str, message: str, **kwargs: Any) -> None:
        self.calls.append((level, str(message), dict(kwargs)))

    def debug(self, message: str, **kwargs: Any) -> None:
        self._record("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._record("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._record("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._record("error", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._record("critical", message, **kwargs)

    def warnings(self) -> List[str]:
        return [message for level, message, _ in self.calls if level == "warning"]


def _cfg(path: Path, **over: Any) -> Dict[str, Any]:
    """Конфиг с ОДНИМ файловым приёмником: снапшоты проверяются по файлу.

    ``enable_logging=False`` — лог-канал статистики здесь не предмет проверки;
    единственный объявленный канал не даёт подняться и fallback'у, поэтому
    в файле лежит ровно то, что произвела эта плоскость.
    """
    cfg: Dict[str, Any] = {
        "enable_logging": False,
        "channels": {"probe": {"type": "file", "file_path": str(path), "format": "json"}},
    }
    cfg.update(over)
    return cfg


def _snapshots(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _metric_names(path: Path) -> List[str]:
    return [str(m.get("name")) for snap in _snapshots(path) for m in snap.get("metrics", [])]


class TestFloorIsSpokenOutLoud:
    """Пол ``max(flush_interval, aggregation_interval)`` перестаёт глушить молча."""

    def test_value_below_the_floor_is_raised_and_named_with_the_key_address(self, tmp_path: Path) -> None:
        logger = _RecordingLogger()
        mgr = StatsManager(
            manager_name="stats_floor",
            config=_cfg(tmp_path / "s.json", aggregation_interval=3.0),
            managers={"logger": logger},
        )
        mgr.initialize()
        try:
            assert mgr._buffer.flush_interval == 10.0, "пол не применился"
            spoken = [w for w in logger.warnings() if "stats.aggregation_interval" in w]
            assert spoken, f"пол поднял темп и промолчал; сказано было: {logger.warnings()}"
            said = spoken[0]
            assert "3.0" in said and "10.0" in said, f"в предупреждении нет обоих чисел: {said}"
            assert "stats.flush_interval" in said, f"не назван ключ пола: {said}"
        finally:
            mgr.shutdown()

    def test_the_floor_is_named_on_reload_too_not_only_at_startup(self, tmp_path: Path) -> None:
        """Правило проверяется в ДВУХ точках — старт и пересборка.

        Голос, поставленный только на старте, молчит ровно там, где оператор
        крутит ручку живьём: дефект, починенный на одном пути из двух,
        воскресает на соседнем.
        """
        logger = _RecordingLogger()
        path = tmp_path / "s.json"
        mgr = StatsManager(
            manager_name="stats_reload_floor",
            config=_cfg(path, aggregation_interval=12.0),
            managers={"logger": logger},
        )
        mgr.initialize()
        try:
            assert not [w for w in logger.warnings() if "stats.aggregation_interval" in w]
            mgr.reconfigure(_cfg(path, aggregation_interval=3.0))
            spoken = [w for w in logger.warnings() if "stats.aggregation_interval" in w]
            assert spoken, "пересборка подняла темп полом и промолчала"
            assert "10.0" in spoken[0], spoken[0]
        finally:
            mgr.shutdown()

    def test_value_above_the_floor_acts_and_stays_silent(self, tmp_path: Path) -> None:
        """Вторая половина пары: приём, а не только отказ."""
        logger = _RecordingLogger()
        mgr = StatsManager(
            manager_name="stats_ok",
            config=_cfg(tmp_path / "s.json", aggregation_interval=12.0),
            managers={"logger": logger},
        )
        mgr.initialize()
        try:
            assert mgr._buffer.flush_interval == 12.0
            assert not [w for w in logger.warnings() if "stats.aggregation_interval" in w], (
                "ложная тревога о поле там, где пол не сработал"
            )
        finally:
            mgr.shutdown()


class TestReconfigureChangesTheTempo:
    """``reconfigure`` пересобирает ОКНО, а не только каналы (major-3)."""

    def test_live_window_carries_the_new_tempo(self, tmp_path: Path) -> None:
        mgr = StatsManager(
            manager_name="stats_swap",
            config=_cfg(tmp_path / "s.json", aggregation_interval=12.0),
        )
        mgr.initialize()
        try:
            before = mgr._buffer
            assert before.flush_interval == 12.0
            assert mgr.reconfigure(_cfg(tmp_path / "s.json", aggregation_interval=36.0)) is True
            assert mgr._buffer.flush_interval == 36.0, "темп не доехал до живого окна"
            assert mgr._buffer is not before, "окно то же — пересборки не было"
        finally:
            mgr.shutdown()

    def test_the_old_window_stops_and_the_new_one_runs(self, tmp_path: Path) -> None:
        """Второго писателя со старым темпом рядом не остаётся."""
        mgr = StatsManager(
            manager_name="stats_swap2",
            config=_cfg(tmp_path / "s.json", aggregation_interval=12.0),
        )
        mgr.initialize()
        try:
            old = mgr._buffer
            assert old.stats["running"] is True
            mgr.reconfigure(_cfg(tmp_path / "s.json", aggregation_interval=36.0))
            assert old.stats["running"] is False, "старое окно продолжает крутиться своим темпом"
            assert mgr._buffer.stats["running"] is True, "новое окно не запущено — темпа нет вовсе"
        finally:
            mgr.shutdown()

    def test_same_tempo_keeps_the_window(self, tmp_path: Path) -> None:
        """Темп не менялся — окно не трогаем: пересоздание на каждом reload
        сбрасывало бы накопленную агрегацию без причины."""
        mgr = StatsManager(
            manager_name="stats_same",
            config=_cfg(tmp_path / "s.json", aggregation_interval=12.0),
        )
        mgr.initialize()
        try:
            before = mgr._buffer
            mgr.reconfigure(_cfg(tmp_path / "s.json", aggregation_interval=12.0, log_level="DEBUG"))
            assert mgr._buffer is before, "окно пересоздано при неизменном темпе"
        finally:
            mgr.shutdown()

    def test_metrics_recorded_before_the_change_reach_the_sink(self, tmp_path: Path) -> None:
        """Смена темпа не теряет накопленное (рубеж базы: flush ДО закрытия каналов)."""
        path = tmp_path / "s.json"
        mgr = StatsManager(manager_name="stats_keep", config=_cfg(path, aggregation_interval=12.0))
        mgr.initialize()
        try:
            mgr.record_metric("before.change", 7)
            mgr.reconfigure(_cfg(path, aggregation_interval=36.0))
            assert "before.change" in _metric_names(path), "запись до смены темпа потеряна"
        finally:
            mgr.shutdown()


class _LateEmitStats(StatsManager):
    """Метрика попадает в СТАРОЕ окно уже после базового ``flush()`` пересборки.

    Это не искусственный слом, а воспроизведение настоящего окна гонки:
    ``reconfigure`` сбрасывает буфер ДО закрытия каналов, а эмиссия идёт из
    чужих потоков и не останавливается на время пересборки. Барьер ставится
    ровно на ту операцию, внутри которой гонка и живёт (``_setup_channels``
    вызывается между базовым flush'ем и подменой окна) — вход в ``reconfigure``
    для этого не годится.
    """

    late_emit = False

    def _setup_channels(self) -> None:
        super()._setup_channels()
        if self.late_emit:
            self._buffer.enqueue(
                "__stats__",
                {"type": "counter", "name": "late.metric", "value": 1.0, "tags": {}},
            )


class TestFinalFlushOfTheOldWindow:
    def test_records_landing_in_the_old_window_after_the_base_flush_are_not_lost(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        mgr = _LateEmitStats(manager_name="stats_late", config=_cfg(path, aggregation_interval=12.0))
        mgr.initialize()
        try:
            mgr.late_emit = True
            mgr.reconfigure(_cfg(path, aggregation_interval=36.0))
            assert "late.metric" in _metric_names(path), (
                "запись, попавшая в старое окно после базового flush, исчезла при подмене окна"
            )
        finally:
            mgr.shutdown()


class TestReadbackIsLiveNotAnEcho:
    """major-13: ``effective`` темпа обязан читаться из ЖИВОГО окна."""

    def test_readback_reads_the_window_even_when_it_disagrees_with_the_config(self, tmp_path: Path) -> None:
        """Числа взяты там, где кандидаты РАСХОДЯТСЯ.

        Пересчёт из конфига дал бы 12.0 и выглядел бы правдой на любом здоровом
        пути. Окно здесь намеренно разведено с конфигом (99.0) — ровно так
        выглядит несработавшая пересборка, ради обнаружения которой readback и
        заводится.
        """
        mgr = StatsManager(
            manager_name="stats_readback",
            config=_cfg(tmp_path / "s.json", aggregation_interval=12.0),
        )
        mgr.initialize()
        try:
            mgr._buffer.stop()
            mgr._buffer = AggregationWindow(flush_fn=mgr._do_flush, flush_interval=99.0)
            assert mgr.observability_readback()["aggregation_interval"] == 99.0, (
                "readback пересчитал темп из конфига — это снова эхо запроса"
            )
        finally:
            mgr.shutdown()

    def test_readback_names_the_floor_separately(self, tmp_path: Path) -> None:
        mgr = StatsManager(
            manager_name="stats_readback_floor",
            config=_cfg(tmp_path / "s.json", aggregation_interval=3.0, flush_interval=2.0),
        )
        mgr.initialize()
        try:
            back = mgr.observability_readback()
            assert back["flush_interval"] == 2.0, "пол не виден — объяснить действующий темп нечем"
            assert back["aggregation_interval"] == 3.0
        finally:
            mgr.shutdown()

    def test_readback_says_whether_the_log_channel_is_actually_there(self, tmp_path: Path) -> None:
        """``enable_logging`` — про живой реестр, а не про то, что просили."""
        logger = _RecordingLogger()
        off = StatsManager(
            manager_name="stats_log_off",
            config=_cfg(tmp_path / "a.json", aggregation_interval=12.0),
            managers={"logger": logger},
        )
        off.initialize()
        on = StatsManager(
            manager_name="stats_log_on",
            config=_cfg(tmp_path / "b.json", aggregation_interval=12.0, enable_logging=True),
            managers={"logger": logger},
        )
        on.initialize()
        try:
            assert off.observability_readback()["enable_logging"] is False
            assert on.observability_readback()["enable_logging"] is True
        finally:
            off.shutdown()
            on.shutdown()
