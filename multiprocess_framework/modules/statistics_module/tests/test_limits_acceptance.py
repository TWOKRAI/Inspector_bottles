# -*- coding: utf-8 -*-
"""Независимые приёмочные тесты Task 2.2 (`plans/telemetry-stage6.md`).

Написаны **от критериев приёмки задачи 2.2**, без чтения реализации: не открывались
``core/metric_record.py``, ``core/cardinality_guard.py``, ``core/aggregation_window.py``,
``core/stats_manager.py``, ``channels/hub_stats_channel.py``, ``channels/log_stats_channel.py``,
``configs/stats_config.py``, ``DECISIONS.md``, ``README.md`` модуля, ``chain_module/metrics/latency.py``,
и любые авторские тесты задачи (``test_bucket_hazards.py``, ``test_bucket_cost_bench.py``). Контракт
взят из текста задачи 2.2 и таблицы решений Р2.2-1…11 в плане; факты о форме возврата — только через
**вызов** публичного API (``interfaces.py``, экспорт пакета ``__init__.py``, ``adapters/stats_adapter.py``,
``console_module/commands/system_commands.py``, ``process_module/configs`` — ``expand_observability``)
и наблюдение результата, как и разрешает промпт задачи.

Числа-литералы ожиданий получены прогоном именно ЭТОГО кода (разведка через публичный API), а не
угаданы и не взяты из чужого теста — они посчитаны вручную рядом (см. комментарии).
"""

import threading
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.statistics_module import (
    DEFAULT_DURATION_BUCKETS_SEC,
    DEFAULT_MAX_SERIES,
    MetricRecord,
    MetricType,
    StatsManager,
    StatsManagerConfig,
)
from multiprocess_framework.modules.statistics_module.adapters.stats_adapter import StatsAdapter
from multiprocess_framework.modules.statistics_module.channels.log_stats_channel import LogStatsChannel
from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.command_module.core.command_manager import CommandManager
from multiprocess_framework.modules.console_module.commands.system_commands import SystemCommandHandler
from multiprocess_framework.modules.process_module.configs import expand_observability

# Настоящие кадровые периоды (§2-П7 спеки задачи 2.2) — НЕ литералы границ бакетов.
REAL_FRAME_60HZ = 1 / 60  # 0.016666...
REAL_FRAME_30HZ = 1 / 30  # 0.033333...


def _run_with_deadline(fn, timeout=10.0):
    """Гоняет ``fn()`` в потоке-демоне с дедлайном на join.

    Правило проекта: тест, который может заблокироваться, обязан падать по таймауту,
    а не виснуть — зависший тест хуже отсутствующего.
    """
    box = {}

    def _target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в основной поток
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"тест завис дольше {timeout}s — это красный, а не таймаут окружения"
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _SpyChannel(IChannel):
    """Канал-шпион: копит ровно те снапшоты, что реально прилетели через flush()."""

    def __init__(self, name="spy"):
        self._name = name
        self.received = []

    @property
    def name(self):
        return self._name

    def write(self, data):
        self.received.append(data)
        return {"status": "ok"}

    def close(self):
        pass


def _mgr(config_extra=None, managers=None):
    """StatsManager с выключенным логированием по умолчанию и пустыми каналами."""
    cfg = {"enable_logging": False, "channels": {}}
    if config_extra:
        cfg.update(config_extra)
    mgr = StatsManager(manager_name="AcceptanceMgr", config=cfg, managers=managers)
    assert mgr.initialize() is True
    return mgr


# ============================================================================
# 1. Память O(1) на обеих дорогах (timing И histogram)
# ============================================================================


class TestBoundedMemoryBothRoads:
    """Агрегат не растёт формой от числа наблюдений — ни у timing, ни у histogram.

    Критерий из задачи: «числа, а не "не растёт"» — берём две сильно разные величины
    наблюдений (1 и 5000) и сравниваем СТРУКТУРУ (набор ключей, длину списка бакетов),
    а не память процесса напрямую (агрегат — единственный переносимый носитель формы).
    """

    def test_timing_aggregate_shape_is_constant_across_observation_counts(self):
        mgr = _mgr()
        mgr.record_timing("t.one", 0.02)
        small = mgr.get_metric("t.one")

        for _ in range(5000):
            mgr.record_timing("t.many", 0.02)
        big = mgr.get_metric("t.many")

        assert set(small.keys()) == set(big.keys())
        assert len(small["buckets"]) == len(big["buckets"]) == 14  # 13 границ + неявный +Inf
        assert small["count"] == 1
        assert big["count"] == 5000
        mgr.shutdown()

    def test_histogram_aggregate_shape_is_constant_across_observation_counts(self):
        mgr = _mgr()
        mgr.histogram("h.one", 0.02)
        small = mgr.get_metric("h.one")

        for _ in range(5000):
            mgr.histogram("h.many", 0.02)
        big = mgr.get_metric("h.many")

        assert set(small.keys()) == set(big.keys())
        assert len(small["buckets"]) == len(big["buckets"]) == 14
        assert big["count"] == 5000
        mgr.shutdown()

    def test_bucket_boundaries_constant_are_thirteen_plus_implicit_inf(self):
        """Р2.2-1: константа границ фиксирована и её ровно 13 (плюс неявный +Inf).

        **Сетка расширена решением владельца во ВТОРОЙ итерации задачи, и это
        сознательная смена контракта, а не подгонка теста.** Прежние 10 границ
        начинались с 1 мс, а замер по восьми живым процессам показал, что
        99.28 % из 24 060 боевых наблюдений лежат НИЖЕ этой границы: сетка была
        слепа к диапазону, в котором живут все сегодняшние тайминги, и p95
        вырождался в max у 63.6 % агрегатов. Добавлены три под-миллисекундные
        границы. Ожидание теста обновлено вместе с решением; сам тест по-прежнему
        сторожит, что константа ФИКСИРОВАНА и ручкой не является.
        """
        assert DEFAULT_DURATION_BUCKETS_SEC == (
            0.0001,
            0.00025,
            0.0005,
            0.001,
            0.002,
            0.005,
            0.010,
            0.017,
            0.034,
            0.050,
            0.100,
            0.250,
            1.0,
        )


# ============================================================================
# 2. Контроль вырождения (§2-П7)
# ============================================================================


class TestQuantizationDegeneracy:
    """Настоящие кадровые периоды обязаны разложиться по РАЗНЫМ бакетам.

    0.016667 и 0.033333 — не литералы границ (0.017/0.034): значение ровно на границе
    ничего не говорит о соседстве (урок M1). Проверяем через сам список ``buckets``,
    не угадывая индекс из спеки — считываем, где реально встали счётчики.
    """

    def test_real_frame_periods_land_in_different_buckets_for_timing(self):
        mgr = _mgr()
        mgr.record_timing("frame.period", REAL_FRAME_60HZ)
        mgr.record_timing("frame.period", REAL_FRAME_30HZ)
        buckets = mgr.get_metric("frame.period")["buckets"]

        nonzero_positions = [i for i, c in enumerate(buckets) if c > 0]
        assert len(nonzero_positions) == 2, f"60Гц и 30Гц периоды обязаны лечь в РАЗНЫЕ бакеты, получили {buckets}"
        assert sum(buckets) == 2
        mgr.shutdown()

    def test_real_frame_periods_land_in_different_buckets_for_histogram(self):
        """То же самое на дороге HISTOGRAM (§2-П5: обе дороги одной механикой)."""
        mgr = _mgr()
        mgr.histogram("frame.period.hist", REAL_FRAME_60HZ)
        mgr.histogram("frame.period.hist", REAL_FRAME_30HZ)
        buckets = mgr.get_metric("frame.period.hist")["buckets"]

        nonzero_positions = [i for i, c in enumerate(buckets) if c > 0]
        assert len(nonzero_positions) == 2, (
            f"60Гц и 30Гц периоды обязаны лечь в РАЗНЫЕ бакеты (histogram), получили {buckets}"
        )
        mgr.shutdown()

    def test_millisecond_mistake_is_visibly_degenerate(self):
        """Контроль: те же величины, присланные в МИЛЛИСЕКУНДАХ (эмитент ошибся единицей),
        обязаны вырождаться в один (последний) бакет — и это обязано быть ВИДНО, не тихо.
        """
        mgr = _mgr()
        mgr.record_timing("frame.period.ms_bug", REAL_FRAME_60HZ * 1000)  # 16.666...
        mgr.record_timing("frame.period.ms_bug", REAL_FRAME_30HZ * 1000)  # 33.333...
        buckets = mgr.get_metric("frame.period.ms_bug")["buckets"]

        nonzero_positions = [i for i, c in enumerate(buckets) if c > 0]
        assert nonzero_positions == [len(buckets) - 1], (
            f"обе мс-величины (>1.0 с при секундных границах) обязаны схлопнуться "
            f"в ПОСЛЕДНИЙ бакет — получили {buckets}"
        )
        assert buckets[-1] == 2
        mgr.shutdown()

    def test_control_same_value_repeated_collapses_into_one_bucket(self):
        """Отрицательный контроль тестового метода: одинаковые величины ОБЯЗАНЫ лечь в
        один и тот же бакет — иначе тест выше «различаются» ничего бы не доказывал.
        """
        mgr = _mgr()
        mgr.record_timing("frame.same", REAL_FRAME_60HZ)
        mgr.record_timing("frame.same", REAL_FRAME_60HZ)
        buckets = mgr.get_metric("frame.same")["buckets"]
        assert [i for i, c in enumerate(buckets) if c > 0] == [i for i, c in enumerate(buckets) if c == 2]
        mgr.shutdown()


# ============================================================================
# 3. Точность
# ============================================================================


class TestPrecision:
    def test_count_min_max_avg_are_exact_for_timing(self):
        mgr = _mgr()
        values = [0.001, 0.02, 0.5, 0.017, 0.9]
        for v in values:
            mgr.record_timing("precise.timing", v)
        m = mgr.get_metric("precise.timing")

        assert m["count"] == len(values)
        assert m["min"] == pytest.approx(min(values))
        assert m["max"] == pytest.approx(max(values))
        assert m["avg"] == pytest.approx(sum(values) / len(values))
        assert m["sum"] == pytest.approx(sum(values))
        assert m["min"] <= m["p95"] <= m["max"]
        mgr.shutdown()

    def test_count_min_max_avg_are_exact_for_histogram(self):
        mgr = _mgr()
        values = [1.0, 3.5, 7.25, 0.1, 2.2]
        for v in values:
            mgr.histogram("precise.hist", v)
        m = mgr.get_metric("precise.hist")

        assert m["count"] == len(values)
        assert m["min"] == pytest.approx(min(values))
        assert m["max"] == pytest.approx(max(values))
        assert m["avg"] == pytest.approx(sum(values) / len(values))
        assert m["min"] <= m["p95"] <= m["max"]
        mgr.shutdown()

    def test_p95_is_meaningful_on_a_single_observation(self):
        mgr = _mgr()
        mgr.record_timing("single.timing", 0.05)
        m = mgr.get_metric("single.timing")
        assert m["count"] == 1
        assert m["min"] == m["max"] == pytest.approx(0.05)
        assert m["p95"] == pytest.approx(0.05)

        mgr.histogram("single.hist", 3.3)
        h = mgr.get_metric("single.hist")
        assert h["p95"] == pytest.approx(3.3)
        mgr.shutdown()

    def test_p95_invariant_holds_across_a_skewed_distribution(self):
        """min <= p95 <= max на скошенном распределении (много мелких + один большой)."""
        mgr = _mgr()
        for _ in range(20):
            mgr.record_timing("skewed", 0.002)
        mgr.record_timing("skewed", 0.9)
        m = mgr.get_metric("skewed")
        assert m["min"] <= m["p95"] <= m["max"]
        assert m["count"] == 21
        mgr.shutdown()

    def test_p95_never_exceeds_max_when_the_bucket_bound_lies_above_it(self):
        """Инвариант там, где он ЕДИНСТВЕННО и может сломаться.

        Соседний тест выше инвариант не сторожит, и это выяснила инъекция
        «зажим p95 по max снят»: он остался зелёным. Его данные (20 × 0.002 и
        один 0.9) дают верхнюю границу сработавшего бакета 0.002 при максимуме
        0.9 — граница НИЖЕ максимума, значит зажимать нечего, и снятие зажима
        там ничего не меняет. Тест с именем «инвариант держится» обязан умирать
        от снятия того, что инвариант обеспечивает.

        Здесь наоборот: все наблюдения 0.0011 с, они попадают в бакет с верхней
        границей 0.002, а максимум серии — 0.0011. Без зажима p95 вернул бы
        0.002 — число выше всего, что вообще наблюдалось.
        """
        mgr = _mgr()
        for _ in range(3):
            mgr.record_timing("tight", 0.0011)
        m = mgr.get_metric("tight")
        assert m["max"] == 0.0011
        assert m["p95"] == 0.0011, "p95 вылез за наблюдавшийся максимум — зажим не сработал"
        assert m["min"] <= m["p95"] <= m["max"]
        mgr.shutdown()


# ============================================================================
# 4. Каждый читатель агрегата — поимённо
# ============================================================================


class TestEachReaderNamed:
    """Пять прежних ключей (count/min/max/avg/p95) ключ-в-ключ у каждого потребителя."""

    _KEYS = {"count", "min", "max", "avg", "p95"}

    def _loaded_manager(self, **kw):
        mgr = _mgr(**kw)
        mgr.record_timing("req.duration", 0.001)
        mgr.record_timing("req.duration", 0.5)
        mgr.histogram("req.size", 10.0)
        mgr.histogram("req.size", 20.0)
        return mgr

    def test_get_metrics_and_get_metric_via_stats_adapter_through_real_command_manager(self):
        """StatsAdapter регистрирует команды в НАСТОЯЩЕМ CommandManager — вызываем их так,
        как их реально зовут снаружи (``handle_command``), не читая менеджер напрямую.
        """
        mgr = self._loaded_manager()

        class _Proc:
            pass

        proc = _Proc()
        proc.command_manager = CommandManager("ReaderProc")
        assert proc.command_manager.initialize() is True

        adapter = StatsAdapter(mgr, process=proc)
        assert adapter.setup() is True

        def _dispatch():
            all_metrics = proc.command_manager.handle_command({"command": "get_metrics", "data": None})
            one_metric = proc.command_manager.handle_command(
                {"command": "get_metric", "data": {"name": "req.duration"}}
            )
            return all_metrics, one_metric

        all_metrics, one_metric = _run_with_deadline(_dispatch)

        assert self._KEYS <= set(all_metrics["req.duration"].keys())
        assert self._KEYS <= set(all_metrics["req.size"].keys())
        assert all_metrics["req.duration"]["count"] == 2
        assert all_metrics["req.duration"]["avg"] == pytest.approx(0.2505)

        assert self._KEYS <= set(one_metric.keys())
        assert one_metric["name"] == "req.duration"
        assert one_metric["count"] == 2
        assert one_metric["min"] == pytest.approx(0.001)
        assert one_metric["max"] == pytest.approx(0.5)

        proc.command_manager.shutdown()
        mgr.shutdown()

    def test_system_commands_stats_section_renders_without_crashing(self):
        """Консоль (`system_commands.stats`) — не падает и показывает count/avg по обеим метрикам."""
        mgr = self._loaded_manager()
        handler = SystemCommandHandler()
        out = handler.stats(mgr)

        assert "req.duration" in out
        assert "req.size" in out
        assert "count=2" in out
        assert "avg=0.2505" in out
        assert "avg=15.0" in out  # (10+20)/2
        mgr.shutdown()

    def test_log_stats_channel_carries_all_five_keys_for_both_metric_types(self):
        """`LogStatsChannel` → `performance.log`: пять ключей едут ключ-в-ключ на ОБЕИХ дорогах."""
        logger = MagicMock()
        channel = LogStatsChannel(logger_manager=logger, max_bytes=4000)
        mgr = self._loaded_manager()
        mgr.register_channel(channel)
        mgr.flush()

        assert logger.performance.call_count >= 1
        _, message = logger.performance.call_args[0]

        for key in ("count", "min", "max", "avg", "p95", "sum", "buckets"):
            assert f"'{key}'" in message, f"ключ {key!r} не доехал до строки лога: {message}"
        assert "'name': 'req.duration'" in message
        assert "'name': 'req.size'" in message
        mgr.shutdown()

    def test_bucket_bounds_travel_once_per_snapshot_only_when_distribution_present(self):
        """`bucket_bounds` едет один раз НА СНАПШОТ, и только если в нём есть распределение."""
        spy = _SpyChannel()
        mgr = _mgr()
        mgr.register_channel(spy)

        mgr.increment("counter.only")
        mgr.flush()
        snap_counter_only = spy.received[-1]
        assert "bucket_bounds" not in snap_counter_only, "снапшот без распределений не обязан таскать границы бакетов"

        mgr.record_timing("t", 0.02)
        mgr.flush()
        snap_with_timing = spy.received[-1]
        assert "bucket_bounds" in snap_with_timing
        assert tuple(snap_with_timing["bucket_bounds"]) == DEFAULT_DURATION_BUCKETS_SEC
        mgr.shutdown()


# ============================================================================
# 5. Потолок кардинальности
# ============================================================================


class TestCardinalityCeiling:
    """Числа теста — вдали от дефолта 1000 (используем 13), K=5 (константа задачи) не путать
    с потолком серий: это отдельная, отдельно проверяемая величина.
    """

    _CEILING = 13  # далеко от дефолта 1000 и от K=5

    def test_known_series_always_passes_even_after_ceiling_is_exhausted(self):
        mgr = _mgr({"max_series": self._CEILING})
        for i in range(self._CEILING):
            mgr.increment(f"known{i}")

        # известная серия продолжает расти и после исчерпания потолка новыми
        for _ in range(50):
            mgr.increment("known0")
        for i in range(self._CEILING, self._CEILING + 9):  # 9 новых сверх потолка
            mgr.increment(f"extra{i}")

        assert mgr.get_metric("known0")["count"] == 51  # 1 исходный + 50 добавленных
        assert mgr.get_stats()["metrics_count"] == self._CEILING
        assert mgr.get_stats()["series_dropped"] == 9
        assert mgr.get_metric(f"extra{self._CEILING}") is None, (
            "новая серия сверх потолка не обязана появляться в агрегатах"
        )
        mgr.shutdown()

    def test_overflow_is_visible_by_count_and_first_five_names_in_get_stats(self):
        """«Потеря обязана быть видна»: число + первые ≤5 имён — в `get_stats()`."""
        mgr = _mgr({"max_series": self._CEILING})
        for i in range(self._CEILING):
            mgr.increment(f"known{i}")
        for i in range(9):  # 9 отвергнутых — больше K=5
            mgr.increment(f"extra{i}")

        stats = mgr.get_stats()
        # Найдено экспериментально; если поимённых ключей нет вовсе — это отдельная
        # находка (не наш случай: см. отчёт).
        assert stats["max_series"] == self._CEILING
        assert stats["series_dropped"] == 9
        assert len(stats["dropped_series"]) <= 5, "первые ≤5 имён, не все 9"
        assert set(stats["dropped_series"]) <= {f"extra{i}" for i in range(9)}
        mgr.shutdown()

    def test_overflow_is_visible_in_the_window_snapshot_delivered_to_the_channel(self):
        """Та же видимость — в самой записи снапшота окна (не только в `get_stats()`)."""
        spy = _SpyChannel()
        mgr = _mgr({"max_series": self._CEILING})
        mgr.register_channel(spy)

        for i in range(self._CEILING):
            mgr.increment(f"known{i}")
        for i in range(9):
            mgr.increment(f"extra{i}")
        mgr.flush()

        snap = spy.received[-1]
        # total_count = «сколько серий БЫЛО в окне», включая опущенные.
        assert snap["total_count"] == self._CEILING + 9, snap
        assert len(snap["metrics"]) == self._CEILING, "в самих метриках — только допущенные"
        mgr.shutdown()

    def test_voice_fires_exactly_once_per_condition_not_per_rejection(self):
        """WARNING — один раз на переход «под потолком → уперлись», не на каждый отказ.

        Инвариант проверяется на количестве WARNING-вызовов после серии из МНОГИХ (9)
        отказов подряд — их не должно быть 9.
        """
        logger = MagicMock()
        mgr = _mgr({"max_series": self._CEILING, "enable_logging": True}, managers={"logger": logger})

        def _drive():
            for i in range(self._CEILING):
                mgr.increment(f"known{i}")
            for i in range(9):
                mgr.increment(f"extra{i}")
            mgr.flush()
            # второй flush без новых серий не должен добавить голосов
            mgr.flush()
            return [c for c in logger.method_calls if c[0] == "warning" and "потолок" in str(c)]

        cardinality_warnings = _run_with_deadline(_drive)

        # ровно по одному голосу на каждую из двух независимых позиций (окно, живой слой) —
        # НЕ по одному на каждую из 9 отвергнутых серий.
        assert 1 <= len(cardinality_warnings) <= 2, cardinality_warnings
        for c in cardinality_warnings:
            text = c.args[0]
            assert "9" in text
            assert "observability.stats.max_series" in text, "голос обязан называть адрес ручки"
        mgr.shutdown()

    def test_default_ceiling_is_1000_and_tested_separately_from_the_handle(self):
        """Дефолт — отдельно и явно, не «рядом» с числами остальных тестов класса."""
        assert DEFAULT_MAX_SERIES == 1000
        assert StatsManagerConfig.model_fields["max_series"].default == 1000

        mgr = _mgr()  # без max_series в конфиге -> дефолт
        for i in range(1000):
            mgr.increment(f"s{i}")
        assert mgr.get_stats()["metrics_count"] == 1000
        assert mgr.get_stats()["series_dropped"] == 0
        mgr.increment("s1000")  # 1001-я — уже сверх дефолтного потолка
        assert mgr.get_stats()["series_dropped"] == 1
        mgr.shutdown()

    def test_zero_means_unlimited(self):
        """`0` = без предела (как у `log_line_max_bytes` в 3.4) — не «дефолт», а явное значение."""
        mgr = _mgr({"max_series": 0})
        for i in range(50):  # заведомо больше и дефолта-теста, и потолка соседних тестов
            mgr.increment(f"unbounded{i}")
        assert mgr.get_stats()["metrics_count"] == 50
        assert mgr.get_stats()["series_dropped"] == 0
        mgr.shutdown()


# ============================================================================
# 6. Дорога ручки целиком (три точки §3.2) + reconfigure на лету
# ============================================================================


class TestHandleRoadIsWholeAndLive:
    _VALUE = 57  # далеко от дефолта 1000

    def test_expand_observability_facade_emits_the_value(self):
        out = expand_observability({"stats": {"max_series": self._VALUE}})
        assert out["stats"]["max_series"] == self._VALUE

    def test_facade_output_validates_against_the_manager_schema(self):
        out = expand_observability({"stats": {"max_series": self._VALUE}})
        cfg = StatsManagerConfig.model_validate(out["stats"])
        assert cfg.max_series == self._VALUE

    def test_default_facade_emits_the_default_value(self):
        out = expand_observability({})
        assert out["stats"]["max_series"] == DEFAULT_MAX_SERIES

    def test_readback_reports_the_value_from_the_live_manager(self):
        out = expand_observability({"stats": {"max_series": self._VALUE}})
        mgr = StatsManager(manager_name="RoadProbe", config=out["stats"])
        assert mgr.initialize() is True
        try:
            assert mgr.observability_readback()["max_series"] == self._VALUE
        finally:
            mgr.shutdown()

    def test_reconfigure_on_the_fly_moves_the_live_ceiling(self):
        """Правка на лету действует: `reconfigure` меняет живой потолок, не только конфиг."""
        out = expand_observability({"stats": {"max_series": self._VALUE}})
        mgr = StatsManager(manager_name="RoadProbe2", config=out["stats"])
        assert mgr.initialize() is True
        try:
            assert mgr.observability_readback()["max_series"] == self._VALUE

            new_out = expand_observability({"stats": {"max_series": 84}})
            assert mgr.reconfigure(new_out["stats"]) is True
            assert mgr.observability_readback()["max_series"] == 84

            # и поведенчески: новый потолок реально применяется, а не только читается.
            for i in range(84):
                mgr.increment(f"live{i}")
            assert mgr.get_stats()["series_dropped"] == 0
            mgr.increment("live_over")
            assert mgr.get_stats()["series_dropped"] == 1
        finally:
            mgr.shutdown()


# ============================================================================
# 7. Слияние агрегатов
# ============================================================================


class TestAggregateMerge:
    """Слияние двух окон/процессов даёт то же, что одно окно с объединённым входом.

    Числа заведомо расходящиеся (не симметричные) — урок «совпадение констант прячет
    реализации»: если бы слияние молча удваивало один из наборов, симметричный вход
    этого не поймал бы.
    """

    def test_merge_matches_a_single_combined_window_for_timing(self):
        left_values = (0.01, 0.02, 0.5)
        right_values = (0.001, 0.9, 0.03, 0.03)

        left = MetricRecord(name="req.dur", metric_type=MetricType.TIMING)
        for v in left_values:
            left.add_timing(v)
        right = MetricRecord(name="req.dur", metric_type=MetricType.TIMING)
        for v in right_values:
            right.add_timing(v)
        merged = left.merged_with(right)

        combined = MetricRecord(name="req.dur", metric_type=MetricType.TIMING)
        for v in (*left_values, *right_values):
            combined.add_timing(v)

        merged_agg = merged.aggregate()
        combined_agg = combined.aggregate()

        for key in ("count", "min", "max", "avg", "sum", "p95", "buckets"):
            assert merged_agg[key] == combined_agg[key], key

        assert merged_agg["count"] == 7
        assert merged_agg["min"] == pytest.approx(0.001)
        assert merged_agg["max"] == pytest.approx(0.9)
        assert merged_agg["sum"] == pytest.approx(1.491)

    def test_merge_matches_a_single_combined_window_for_histogram(self):
        left_values = (2.0, 40.0, 3.5)
        right_values = (0.2, 17.0)

        left = MetricRecord(name="req.size", metric_type=MetricType.HISTOGRAM)
        for v in left_values:
            left.add_histogram(v)
        right = MetricRecord(name="req.size", metric_type=MetricType.HISTOGRAM)
        for v in right_values:
            right.add_histogram(v)
        merged = left.merged_with(right)

        combined = MetricRecord(name="req.size", metric_type=MetricType.HISTOGRAM)
        for v in (*left_values, *right_values):
            combined.add_histogram(v)

        merged_agg = merged.aggregate()
        combined_agg = combined.aggregate()
        for key in ("count", "min", "max", "avg", "sum", "p95", "buckets"):
            assert merged_agg[key] == combined_agg[key], key

        assert merged_agg["count"] == 5
        assert merged_agg["sum"] == pytest.approx(62.7)


# ============================================================================
# 8. Независимость стражей двух позиций
# ============================================================================


class TestGuardsAreIndependent:
    """Живой слой упёрся → доставка новой серии в снапшот окна всё равно происходит.

    Механика: живой слой (`StatsManager._metrics` через публичный `get_metric`) не
    чистится между flush(), а окно — чистится (новое окно на каждый flush). Насыщаем
    живой слой, затем делаем flush (окно освобождается), и заводим НОВУЮ серию — она
    обязана быть отвергнута живым слоем (не видна в `get_metric`), но обязана доехать
    до снапшота следующего окна.
    """

    def test_new_series_reaches_the_window_snapshot_even_when_the_live_layer_is_saturated(self):
        spy = _SpyChannel()
        mgr = _mgr({"max_series": 3})
        mgr.register_channel(spy)

        for name in ("A", "B", "C"):
            mgr.increment(name)
        mgr.flush()  # окно освобождается; живой слой (A,B,C) насыщен и таким остаётся

        mgr.increment("D")  # новая серия сверх потолка ЖИВОГО слоя

        assert mgr.get_metric("D") is None, "живой слой обязан отказать D — он уже насыщен"

        mgr.flush()
        last_snapshot = spy.received[-1]
        delivered_names = [m["name"] for m in last_snapshot["metrics"]]
        assert "D" in delivered_names, "отказ живого слоя не имеет права блокировать доставку в окно/снапшот (Р2.2-7)"
        mgr.shutdown()
