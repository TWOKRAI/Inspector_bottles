# -*- coding: utf-8 -*-
"""Задача 2.2 — цена бакетов: память, время, байты. Все числа — в одном прогоне.

**Как читать этот файл.** Абсолютные микросекунды и байты на разных машинах
разные, и порог, прибитый числом, либо мигает, либо не сторожит ничего. Поэтому
«до» измеряется В ТОМ ЖЕ ПРОГОНЕ: рядом лежит замороженная копия ПРЕЖНЕЙ модели
(:class:`_LegacyDistributionRecord` — полный список значений и p95 сортировкой),
и утверждение звучит как «новая модель не хуже старой», а не как «быстрее чем
X мкс». Приём взят у ``logger_module/tests/test_gate_cost_bench.py``.

Копия, а не импорт: прежней реализации в дереве больше нет, а сравнивать надо
именно с ней. Копия узкая — только то, что меряется.

Числа последнего замера (Windows 10, Python 3.12) занесены в отчёт задачи 2.2
и в ADR-SM-011.
"""

from __future__ import annotations

import gc
import time
import tracemalloc
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.statistics_module.channels.log_stats_channel import (
    DEFAULT_LOG_LINE_MAX_BYTES,
    LogStatsChannel,
)
from multiprocess_framework.modules.statistics_module.core.aggregation_window import AggregationWindow
from multiprocess_framework.modules.statistics_module.core.cardinality_guard import CardinalityGuard
from multiprocess_framework.modules.statistics_module.core.metric_record import (
    DEFAULT_DURATION_BUCKETS_SEC,
    MetricRecord,
    MetricType,
)

FRAME_60 = 1.0 / 60.0
FRAME_30 = 1.0 / 30.0


@dataclass
class _LegacyDistributionRecord:
    """Замороженная копия модели ДО 2.2: полный список значений.

    Ровно то, что стояло в ``metric_record.py`` на HEAD ``d3dee23d`` для
    ``TIMING`` и ``HISTOGRAM``: ``List[float]`` целиком плюс p95 сортировкой
    сырого списка. Держится здесь, чтобы «стало не хуже» было измеримым, а не
    декларируемым.
    """

    name: str
    values: List[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.values.append(value)

    def aggregate(self) -> Dict[str, Any]:
        if not self.values:
            return {"count": 0, "min": None, "max": None, "avg": None, "p95": None}
        sorted_vals = sorted(self.values)
        n = len(sorted_vals)
        return {
            "count": n,
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "avg": sum(sorted_vals) / n,
            "p95": sorted_vals[max(0, int(n * 0.95) - 1)],
        }


def _retained_bytes(build, observations: int) -> int:
    """Сколько памяти УДЕРЖИВАЕТ запись после N наблюдений.

    ``tracemalloc`` здесь к месту (в отличие от бенча гейта, где он врал):
    список значений именно УДЕРЖИВАЕТСЯ до конца окна, а не умирает в той же
    инструкции. Запись создаётся внутри трассируемого участка и жива на момент
    замера — иначе сборщик унёс бы предмет измерения.
    """
    gc.collect()
    tracemalloc.start()
    try:
        before, _ = tracemalloc.get_traced_memory()
        record = build()
        for i in range(observations):
            record.add(0.001 + (i % 997) * 0.0001)
        after, _ = tracemalloc.get_traced_memory()
        assert record is not None  # держим живой до замера
        return after - before
    finally:
        tracemalloc.stop()


def _per_call_usec(call, repeats: int) -> float:
    """Медиана из трёх прогонов, мкс на вызов. Одиночный прогон ловит соседа по машине."""
    samples = []
    for _ in range(3):
        gc.collect()
        start = time.perf_counter()
        for i in range(repeats):
            call(i)
        samples.append((time.perf_counter() - start) / repeats * 1e6)
    return sorted(samples)[1]


class TestMemory:
    """Пара «свойство + контроль» на утверждение о памяти — на ОБЕИХ дорогах."""

    @pytest.mark.parametrize("kind", [MetricType.TIMING, MetricType.HISTOGRAM])
    def test_bucket_record_does_not_grow_with_observations(self, kind: MetricType, capsys) -> None:
        """Свойство: память записи с бакетами не зависит от числа наблюдений.

        Сравниваются 200 и 20 000 наблюдений на одной и той же записи. У модели
        с бакетами разница обязана быть нулевой — счётчиков ровно столько,
        сколько границ плюс один, при любом числе наблюдений.

        **Порог взят из физики, а не из замера (исправлено 2026-08-14).** Прежние
        512 Б были «наблюдалось 240, возьмём с запасом» — и запаса не оказалось:
        ``tracemalloc`` меряет кучу ВСЕГО процесса за окно, поэтому показание зависит
        от состояния аллокатора, то есть от того, что крутилось в этом же
        интерпретаторе до бенча. Замерено на одной машине в один день: 240 Б в
        одиночном прогоне (стабильно ×5), 312 Б в паре с двумя модулями, 344 Б в
        полном гейте на чистом HEAD, 496 Б после добавления 42 тестов в СОСЕДНИЕ
        модули — то есть чужой тест-файл двигает это число на 184 Б, не касаясь
        предмета измерения. `gc.disable()` внутри окна не помогает (проверено: 408 Б
        против 616 Б в тех же двух конфигурациях) — шум идёт от арен, не от сборщика.

        Физика: запись держит ``len(buckets) + 1`` счётчиков и несколько скаляров —
        величина, не зависящая от N. Порог обязан отделять «константа» от «растёт»,
        а не воспроизводить конкретный замер. Контроль
        (:meth:`test_control_the_old_model_did_grow`) даёт масштаб растущей модели —
        **647 016 Б** на тех же 20 000 наблюдений. 8 КиБ лежит на порядок выше
        полосы шума (~700 Б) и в 79 раз ниже контроля: разделение сохранено, ложные
        срабатывания от соседей по интерпретатору — нет.
        """

        class _Adapter:
            def __init__(self) -> None:
                self.rec = MetricRecord(name="t", metric_type=kind)

            def add(self, value: float) -> None:
                self.rec.observe(value)

        small = _retained_bytes(_Adapter, 200)
        large = _retained_bytes(_Adapter, 20_000)
        with capsys.disabled():
            print(f"\n[bucket/{kind.value}] 200 набл.: {small} Б; 20 000 набл.: {large} Б; рост {large - small} Б")
        assert large - small <= 8192, "запись с бакетами обязана быть O(1) от числа наблюдений"

    def test_control_the_old_model_did_grow(self, capsys) -> None:
        """Контроль на ПРЕЖНЕЙ модели: со списком память росла — и вот на сколько.

        Без этого контроля тест выше зелен и на вырожденной реализации, которая
        просто ничего не хранит. Пара «свойство + контроль» требует показать,
        что измеряемая величина вообще умеет расти.
        """
        small = _retained_bytes(lambda: _LegacyDistributionRecord(name="t"), 200)
        large = _retained_bytes(lambda: _LegacyDistributionRecord(name="t"), 20_000)
        growth = large - small
        with capsys.disabled():
            print(f"\n[legacy-list] 200 набл.: {small} Б; 20 000 набл.: {large} Б; рост {growth} Б")
        assert growth > 100_000, "прежняя модель обязана расти — иначе контроль ничего не контролирует"

    def test_window_of_many_series_stays_flat(self, capsys) -> None:
        """То же на уровне ОКНА: 30 серий по 5 000 наблюдений против × 50.

        Окно — та позиция, ради которой всё делалось: в нём метрика на кадр при
        30 fps даёт полтора миллиона значений за десятисекундное окно.
        """

        def measure(per_series: int) -> int:
            gc.collect()
            tracemalloc.start()
            try:
                before, _ = tracemalloc.get_traced_memory()
                window = AggregationWindow(flush_fn=lambda ch, batch: len(batch))
                for i in range(per_series):
                    for s in range(30):
                        window.enqueue("c", {"type": "timing", "name": f"m{s}", "value": 0.001 * (i % 60)})
                after, _ = tracemalloc.get_traced_memory()
                assert window is not None
                return after - before
            finally:
                tracemalloc.stop()

        light = measure(50)
        heavy = measure(5_000)
        extra_observations = (5_000 - 50) * 30
        per_observation = (heavy - light) / extra_observations
        with capsys.disabled():
            print(
                f"\n[window] 30x50: {light} Б; 30x5000: {heavy} Б; рост {heavy - light} Б "
                f"на {extra_observations} наблюдений = {per_observation:.4f} Б/наблюдение"
            )
        # Тот же ВЫВЕДЕННЫЙ порог, что и у записи: список хранил бы >= 8 Б на
        # наблюдение, то есть >= 1.1 МБ на этой дельте. Абсолютный порог рядом
        # с замером здесь уже мигал — 3856 Б в одиночном прогоне против 4104 Б
        # в общем; предмет измерения при этом не менялся.
        assert per_observation < 1.0


class TestDegeneration:
    """Контроль вырождения: тест памяти зелен и на модели, которая всё теряет."""

    #: Величины НАСТОЯЩИХ сегодняшних эмитентов, а не кадровые периоды.
    #: Замер ревью по восьми живым процессам: ``command_manager.command.
    #: execution.duration`` (n=8671) и ``dispatcher.dispatch.duration``
    #: (n=15389) — 30 мкс … 1.3 мс, медиана около 150 мкс. Кадровый эмитент,
    #: под который подбирались границы 0.017/0.034, пока НЕ СУЩЕСТВУЕТ, и
    #: контроль, построенный только на нём, проверял будущее вместо настоящего
    #: — потому и не заметил, что 99.28 % боевых наблюдений легли в один бакет.
    LIVE_MAGNITUDES_SEC = (
        0.000030,
        0.000045,
        0.000080,
        0.000120,
        0.000150,
        0.000210,
        0.000330,
        0.000480,
        0.000700,
        0.001200,
    )

    def test_real_emitter_magnitudes_do_not_collapse_into_one_bucket(self) -> None:
        """Боевые микросекундные тайминги обязаны лечь в РАЗНЫЕ бакеты, и p95 < max.

        **Добавлен по находке ревью, воспроизведённой на живом стенде.** Прежний
        контроль вырождения стоял на кадровых периодах 1/60 и 1/30 — эмитента с
        такими величинами в системе ещё нет, и контроль был зелёным ровно тогда,
        когда сетка ослепла к тому, что эмитируют на самом деле.

        Требуется ДВА свойства сразу: занято не меньше трёх бакетов И
        ``p95 < max``. Одного первого мало — перцентиль вырождается в максимум и
        при двух занятых бакетах, если ранг попадает в верхний.
        """
        rec = MetricRecord(name="live", metric_type=MetricType.TIMING)
        for _ in range(12):
            for value in self.LIVE_MAGNITUDES_SEC[:9]:
                rec.observe(value)
        rec.observe(self.LIVE_MAGNITUDES_SEC[9])

        agg = rec.aggregate()
        occupied = [i for i, c in enumerate(agg["buckets"]) if c]
        assert len(occupied) >= 3, f"боевые величины схлопнулись в {len(occupied)} бакет(а): {agg['buckets']}"
        assert agg["p95"] < agg["max"], "перцентиль выродился в максимум — сетка слепа к этому диапазону"

    def test_control_the_old_grid_did_collapse(self, capsys) -> None:
        """Контроль: на ПРЕЖНЕЙ сетке те же величины схлопывались в один бакет.

        Без этого контроля тест выше зелен и не доказывает, что новая сетка
        что-то изменила: он был бы зелёным и на сетке, где границы просто
        удачно расставлены. Здесь показано, ЧТО именно чинилось — и числом.
        """
        old_grid = (0.001, 0.002, 0.005, 0.010, 0.017, 0.034, 0.050, 0.100, 0.250, 1.0)
        values = [v for _ in range(12) for v in self.LIVE_MAGNITUDES_SEC[:9]] + [self.LIVE_MAGNITUDES_SEC[9]]

        counts = [0] * (len(old_grid) + 1)
        for value in values:
            counts[bisect_left(old_grid, value)] += 1
        occupied_old = [i for i, c in enumerate(counts) if c]

        rec = MetricRecord(name="live", metric_type=MetricType.TIMING)
        for value in values:
            rec.observe(value)
        occupied_new = [i for i, c in enumerate(rec.aggregate()["buckets"]) if c]

        with capsys.disabled():
            print(
                f"\n[сетка] боевые величины: старая — занято {len(occupied_old)} бакетов "
                f"({counts[0]} из {len(values)} наблюдений в первом); "
                f"новая — занято {len(occupied_new)}"
            )
        assert len(occupied_old) < len(occupied_new)
        assert counts[0] / len(values) > 0.9, "прежняя сетка обязана показать концентрацию в первом бакете"

    def test_p95_equals_max_share_before_and_after_the_grid_change(self, capsys) -> None:
        """Доля ``p95 == max`` — ЗАМЕРОМ на обеих сетках, а не рассуждением.

        Корпус синтетический (логнормаль по параметрам живого замера: min ~29
        мкс, медиана ~150 мкс, хвост до ~3.5 мс) — живой стенд принадлежит не
        этому прогону, и его числа названы в ADR отдельно как живые. Здесь
        важно НАПРАВЛЕНИЕ и порядок величины, измеренные одинаково для обеих
        сеток в одном прогоне.
        """
        import math
        import random

        old_grid = (0.001, 0.002, 0.005, 0.010, 0.017, 0.034, 0.050, 0.100, 0.250, 1.0)

        def p95_is_max(grid, samples):
            counts = [0] * (len(grid) + 1)
            for value in samples:
                counts[bisect_left(grid, value)] += 1
            biggest = max(samples)
            rank = math.ceil(0.95 * len(samples))
            cumulative = 0
            for index, count in enumerate(counts):
                cumulative += count
                if cumulative >= rank:
                    if index >= len(grid):
                        return True
                    bound = grid[index]
                    return (bound if bound < biggest else biggest) == biggest
            return True

        shares = {}
        for label, grid in (("старая", old_grid), ("новая", DEFAULT_DURATION_BUCKETS_SEC)):
            random.seed(20260813)  # один и тот же корпус обеим сеткам
            equal = 0
            for _ in range(500):
                n = random.choice([20, 40, 70, 120, 300])
                samples = [min(max(random.lognormvariate(math.log(0.00015), 0.85), 0.000029), 0.0035) for _ in range(n)]
                equal += p95_is_max(grid, samples)
            shares[label] = equal / 500 * 100

        with capsys.disabled():
            print(
                f"\n[вырождение p95] доля p95==max: старая сетка {shares['старая']:.1f}%, новая {shares['новая']:.1f}%"
            )
        assert shares["новая"] < shares["старая"], "новая сетка обязана уменьшить вырождение, а не просто отличаться"

    def test_real_frame_periods_spread_across_different_buckets(self) -> None:
        """Настоящие кадровые периоды обязаны лечь в РАЗНЫЕ бакеты.

        Числа — не литералы границ: 1/60, 1/30 и половина кадра. Если бы
        эмитент слал миллисекунды (16.67 вместо 0.01667) либо границы жили в
        миллисекундах, всё легло бы в ОДИН бакет при полностью зелёном тесте
        памяти — ровно та ловушка, ради которой этот контроль и существует.
        """
        rec = MetricRecord(name="frame", metric_type=MetricType.TIMING)
        for _ in range(40):
            rec.observe(FRAME_60)
        for _ in range(25):
            rec.observe(FRAME_30)
        for _ in range(10):
            rec.observe(FRAME_60 / 2)
        for _ in range(3):
            rec.observe(0.42)

        buckets = rec.aggregate()["buckets"]
        occupied = [i for i, c in enumerate(buckets) if c]
        assert len(occupied) == 4, f"распределение выродилось в {len(occupied)} бакет(а): {buckets}"
        assert buckets[0] == 0, "ни одно кадровое значение не имеет права лежать в самом первом бакете"

    def test_milliseconds_would_degenerate_and_the_test_would_see_it(self) -> None:
        """Красный-без-фикса для контроля выше: те же кадры, но в миллисекундах.

        Детектор, который никогда не срабатывал, ничего не доказывает. Здесь
        показано, ЧТО он ловит: миллисекундные значения (16.67 / 33.33) все до
        одного уезжают в ``+Inf``, и «разные бакеты» превращается в один.
        """
        rec = MetricRecord(name="frame_ms", metric_type=MetricType.TIMING)
        for _ in range(40):
            rec.observe(FRAME_60 * 1000)
        for _ in range(25):
            rec.observe(FRAME_30 * 1000)

        buckets = rec.aggregate()["buckets"]
        occupied = [i for i, c in enumerate(buckets) if c]
        assert occupied == [len(buckets) - 1], "миллисекунды обязаны выродиться в +Inf — это и ловит контроль"


class TestCost:
    """Цена наблюдения и цена стража — дельтой, числами."""

    def test_bucket_observation_costs_more_than_append_and_the_number_is_named(self, capsys) -> None:
        """ЗАПИСЬ с бакетами ДОРОЖЕ списка — измерено, а не предположено.

        Приёмка задачи ожидала «цена ``record`` с бакетами ≤ цены со списком»,
        и это ожидание **не подтвердилось**. Замер (Windows 10, Python 3.12):
        наблюдение 0.31 мкс против 0.11 мкс у ``append``, то есть **+0.20 мкс**.
        Причина арифметическая: посылка была в том, что снятая сортировка
        оплатит счётчики, — а сортировка стоит ~13 нс на наблюдение
        (амортизированно по окну), тогда как пять операций счёта стоят ~200 нс.
        Точки безубыточности по CPU нет ни при каком размере окна.

        Куплено за эти 0.20 мкс: память **в ~3100 раз** меньше (см. выше),
        перцентиль, который СЛИВАЕТСЯ между окнами и процессами, и готовность
        к экспорту. Для сравнения масштаба, замеры задачи 1.1 того же плана:
        фасад ``record_metric`` стоит 0.31–0.38 мкс, ОДИН тег внутри
        ``StatsManager`` — +1.15 мкс. То есть смена модели дешевле одного тега
        в шесть раз.

        Порог здесь — сторож РЕГРЕССИИ, а не доказательство «≤»: множитель 4.5
        при измеренных 2.6–3.3 (пять прогонов после расширения сетки до 13
        границ) ловит существенное ухудшение и не мигает на медленной машине,
        потому что обе стороны меряются в одном прогоне. Прибивать порог
        вплотную к замеру нельзя — первый прогон после старта интерпретатора
        стабильно даёт разогревочный выброс (0.93 мкс против 0.40 в установившемся
        режиме), и абсолютное число там втрое больше.
        """
        new = MetricRecord(name="t", metric_type=MetricType.TIMING)
        old = _LegacyDistributionRecord(name="t")

        new_us = _per_call_usec(lambda i: new.observe(0.001 + (i % 97) * 0.0002), 200_000)
        old_us = _per_call_usec(lambda i: old.add(0.001 + (i % 97) * 0.0002), 200_000)

        with capsys.disabled():
            print(
                f"\n[observe] бакеты: {new_us:.3f} мкс/вызов; список: {old_us:.3f} мкс/вызов; "
                f"дельта {new_us - old_us:+.3f} мкс (x{new_us / old_us:.1f})"
            )
        assert new_us <= old_us * 4.5, "запись подорожала больше, чем на измеренную цену модели"

    def test_aggregate_with_buckets_beats_sorting(self, capsys) -> None:
        """Вторая половина цены: ``aggregate`` больше не сортирует список.

        На окне в 5 000 наблюдений прежняя модель сортировала весь список на
        КАЖДОМ сбросе — вот здесь бакеты и отыгрывают то, что могли потерять на
        наблюдении.
        """
        new = MetricRecord(name="t", metric_type=MetricType.TIMING)
        old = _LegacyDistributionRecord(name="t")
        for i in range(5_000):
            value = 0.001 + (i % 997) * 0.0001
            new.observe(value)
            old.add(value)

        new_us = _per_call_usec(lambda i: new.aggregate(), 2_000)
        old_us = _per_call_usec(lambda i: old.aggregate(), 2_000)
        with capsys.disabled():
            print(f"\n[aggregate 5000 набл.] бакеты: {new_us:.2f} мкс; список: {old_us:.2f} мкс")
        assert new_us < old_us

    def test_guard_cost_on_the_hot_path_measured_as_a_delta(self, capsys) -> None:
        """Цена стража — ДЕЛЬТОЙ: то же окно со стражем и без него.

        Мерится ЗНАКОМЫЙ ключ (страж обязан пропускать его без работы) — это и
        есть горячий путь: новых серий за окно единицы, повторных эмиссий
        тысячи.

        **Замеры ЧЕРЕДУЮТСЯ, и берётся минимум по раундам.** Прежняя редакция
        мерила сперва все 200 000 вызовов без стража, потом все со стражем, и
        сравнивала два числа абсолютным порогом. Такой порог меряет не цену
        стража, а загрузку машины: два окна получают разную долю CPU, и дельта
        становится шумом. Воспроизведено — при работающем рядом живом стенде
        тест дал ``0.688 мкс`` против порога ``0.5`` и покраснел, а на той же
        сборке без стенда прошёл 3 раза из 3. Минимум по чередующимся раундам —
        стандартный устойчивый оценщик для бенчей: помеха может замер только
        замедлить, поэтому наименьший раунд ближе всего к настоящей цене.
        Порог при этом НЕ поднят — поднять его значило бы согласиться мерить
        загрузку.
        """
        plain = AggregationWindow(flush_fn=lambda ch, b: len(b))
        guarded = AggregationWindow(flush_fn=lambda ch, b: len(b), guard=CardinalityGuard(50_000))
        payload = {"type": "timing", "name": "hot", "value": 0.004}

        plain_rounds, guarded_rounds = [], []
        for _ in range(3):
            plain_rounds.append(_per_call_usec(lambda i: plain.enqueue("c", payload), 70_000))
            guarded_rounds.append(_per_call_usec(lambda i: guarded.enqueue("c", payload), 70_000))
        plain_us, guarded_us = min(plain_rounds), min(guarded_rounds)
        delta = guarded_us - plain_us
        with capsys.disabled():
            print(
                f"\n[enqueue] без стража: {plain_us:.3f} мкс; со стражем: {guarded_us:.3f} мкс; "
                f"дельта {delta:+.3f} мкс (минимум из 3 чередующихся раундов)"
            )
        assert delta < 0.5, "страж на знакомом ключе обязан стоить доли микросекунды"


class TestSnapshotLineBytes:
    """Цена ``buckets`` в байтах на строке ``performance.log`` (предел 2048)."""

    @staticmethod
    def _snapshot_metrics(count: int, with_buckets: bool) -> List[Dict[str, Any]]:
        out = []
        for i in range(count):
            rec = MetricRecord(name=f"plugin.stage{i}.duration", metric_type=MetricType.TIMING)
            for j in range(50):
                rec.observe(0.001 * (j % 40 + 1))
            agg = rec.aggregate()
            if not with_buckets:
                agg.pop("buckets")
                agg.pop("sum")
            out.append(agg)
        return out

    def test_report_bytes_per_metric_and_how_many_fit(self, capsys) -> None:
        """Число до/после: сколько байт стоит одна метрика и сколько их влезает.

        Байты здесь не абстрактные: строка ``performance.log`` режется по 2048
        байт с голосом о потере, поэтому каждый лишний байт в записи метрики
        прямо уменьшает ЧИСЛО МЕТРИК, доезжающих до приёмника в такте.
        """
        channel = LogStatsChannel(logger_manager=object(), max_bytes=DEFAULT_LOG_LINE_MAX_BYTES)

        with_b = self._snapshot_metrics(1, True)
        without_b = self._snapshot_metrics(1, False)
        bytes_with = len(repr(with_b[0]).encode("utf-8"))
        bytes_without = len(repr(without_b[0]).encode("utf-8"))

        def fitted(with_buckets: bool) -> int:
            metrics = self._snapshot_metrics(40, with_buckets)
            line = channel._format_snapshot(metrics, len(metrics), 1_700_000_000.0)
            assert len(line.encode("utf-8")) <= DEFAULT_LOG_LINE_MAX_BYTES
            return int(line.split("опущено ")[1].split(" ")[0]) if "опущено" in line else 0

        dropped_with = fitted(True)
        dropped_without = fitted(False)
        with capsys.disabled():
            print(
                f"\n[строка снапшота] одна метрика: без buckets/sum {bytes_without} Б, "
                f"с ними {bytes_with} Б (+{bytes_with - bytes_without} Б, "
                f"+{(bytes_with / bytes_without - 1) * 100:.0f}%); "
                f"из 40 метрик в 2048 Б влезает {40 - dropped_with} против {40 - dropped_without}"
            )
        assert bytes_with > bytes_without, "buckets не бесплатны, и число обязано быть названо"
