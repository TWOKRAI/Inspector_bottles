# -*- coding: utf-8 -*-
"""Задача 2.2 — АВТОРСКИЕ тесты: опасности механизма, а не критерии приёмки.

Приёмку пишет независимый тестер, который этого кода не видел. Здесь — то, что
видно только автору: крайние значения бакетов, порядок при подмене окна,
поведение стража под двумя разными локами и ассоциативность слияния на
расходящихся числах.

**Числа в тестах намеренно далеко от дефолтов** (потолок 7 и 13, а не 1000;
границы проверяются не литералами константы, а настоящими кадровыми периодами):
тест со значением, равным дефолту, проверяет дефолт, а не ручку. Сам дефолт
сверяется отдельно — с ``model_fields[...].default``, а не со вторым написанием
числа.
"""

import math
import threading
import time

import pytest

from multiprocess_framework.modules.statistics_module.configs.stats_config import (
    DEFAULT_MAX_SERIES,
    StatsManagerConfig,
)
from multiprocess_framework.modules.statistics_module.core.aggregation_window import AggregationWindow
from multiprocess_framework.modules.statistics_module.core.cardinality_guard import (
    VOICE_NAME_LIMIT,
    CardinalityGuard,
)
from multiprocess_framework.modules.statistics_module.core.metric_record import (
    DEFAULT_DURATION_BUCKETS_SEC,
    MetricRecord,
    MetricType,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager

#: Настоящие кадровые периоды, а НЕ литералы границ. Значение, равное границе,
#: ничего не говорит о соседстве: оно легло бы верно и при сдвинутой на шаг
#: сетке. 1/60 и 1/30 — те самые числа, ради которых границы 0.017/0.034
#: выбраны вместо круглых 0.016/0.033.
FRAME_60 = 1.0 / 60.0  # 0.0166666…
FRAME_30 = 1.0 / 30.0  # 0.0333333…


def _timing(name: str = "t") -> MetricRecord:
    return MetricRecord(name=name, metric_type=MetricType.TIMING)


def _histogram(name: str = "h") -> MetricRecord:
    return MetricRecord(name=name, metric_type=MetricType.HISTOGRAM)


# =============================================================================
# Крайние значения бакетов
# =============================================================================


class TestBucketEdges:
    """Что делает ``float(value)`` на краях — и что должно."""

    def test_value_exactly_on_bound_falls_into_that_bucket(self) -> None:
        """Семантика границы — ``le``: значение, равное границе, ЕЁ бакет.

        Опасность: ``bisect_right`` вместо ``bisect_left`` сдвинул бы ровно эти
        значения на бакет вправо, и вся сетка врала бы на своих же границах —
        дефект, который на случайных числах почти не виден.
        """
        rec = _timing()
        for bound in DEFAULT_DURATION_BUCKETS_SEC:
            rec.observe(bound)
        buckets = rec.aggregate()["buckets"]
        assert buckets[: len(DEFAULT_DURATION_BUCKETS_SEC)] == [1] * len(DEFAULT_DURATION_BUCKETS_SEC)
        assert buckets[-1] == 0, "ни одно значение-граница не имеет права уехать в +Inf"

    def test_frame_periods_land_above_the_round_bound(self) -> None:
        """1/60 и 1/30 попадают в 0.017 и 0.034, а не выше.

        Это и есть довод против круглых 0.016/0.033: при них штатный кадр
        60 fps уехал бы в бакет 0.017, а 30 fps — в 0.050, и распределение
        читалось бы как систематическое опоздание, которого нет.
        """
        rec = _timing()
        rec.observe(FRAME_60)
        rec.observe(FRAME_30)
        buckets = rec.aggregate()["buckets"]
        i_017 = DEFAULT_DURATION_BUCKETS_SEC.index(0.017)
        i_034 = DEFAULT_DURATION_BUCKETS_SEC.index(0.034)
        assert buckets[i_017] == 1
        assert buckets[i_034] == 1
        assert sum(buckets) == 2

    def test_below_first_bound_and_above_last(self) -> None:
        """Значение ниже первой границы — бакет 0; выше последней — ``+Inf``."""
        rec = _timing()
        rec.observe(0.0000004)
        rec.observe(3.7)
        buckets = rec.aggregate()["buckets"]
        assert buckets[0] == 1
        assert buckets[-1] == 1

    def test_negative_value_goes_to_the_first_bucket_and_becomes_min(self) -> None:
        """Отрицательная длительность (часы шагнули назад) — на дно шкалы.

        Наблюдение не выбрасывается: потерять его дороже, чем показать. Но и
        молчать о нём нельзя — оно видно как ``min < 0``.
        """
        rec = _timing()
        rec.observe(-0.005)
        rec.observe(0.020)
        agg = rec.aggregate()
        assert agg["buckets"][0] == 1
        assert agg["min"] == -0.005
        assert agg["count"] == 2

    def test_positive_infinity_is_honest(self) -> None:
        """``+Inf`` едет в бакет ``+Inf``, становится ``max`` и не прячется в p95.

        Опасность: зажим p95 по ``max`` при бесконечном ``max`` мог бы отдать
        границу последнего бакета и превратить «бесконечность» в «1.0 с».
        """
        rec = _timing()
        rec.observe(math.inf)
        agg = rec.aggregate()
        assert agg["buckets"][-1] == 1
        assert agg["max"] == math.inf
        assert agg["p95"] == math.inf

    def test_nan_is_dropped_with_a_count_and_does_not_poison_the_series(self) -> None:
        """NaN отбрасывается со счётом — иначе он отравил бы серию НАВСЕГДА.

        Без отсева ``sum`` стал бы NaN, а ``min``/``max`` замерли бы на первом
        значении: ``nan < x`` ложно при любом x, поэтому минимум больше никогда
        бы не обновился. Проверяется и то, что соседние наблюдения целы.
        """
        rec = _timing()
        rec.observe(0.010)
        rec.observe(float("nan"))
        rec.observe(0.002)
        agg = rec.aggregate()
        assert agg["count"] == 2, "NaN не считается наблюдением"
        assert agg["nan_dropped"] == 1
        assert agg["min"] == 0.002
        assert agg["max"] == 0.010
        assert agg["sum"] == pytest.approx(0.012)
        assert not math.isnan(agg["avg"])

    def test_nan_key_absent_when_no_nan(self) -> None:
        """Ключа ``nan_dropped`` в норме нет: постоянный ноль весил бы в каждой записи."""
        rec = _timing()
        rec.observe(0.010)
        assert "nan_dropped" not in rec.aggregate()

    def test_p95_invariant_min_le_p95_le_max_on_a_wide_spread(self) -> None:
        """``min <= p95 <= max`` держится и на разбросе в четыре порядка.

        Опасность: p95 берётся как ГРАНИЦА бакета, то есть число, которого в
        серии может не быть вовсе. Без зажима сверху настоящим ``max`` оно
        выходило бы за наблюдавшийся диапазон — «перцентиль больше максимума».
        """
        rec = _timing()
        for value in (0.0003, 0.0007, 0.0011, 0.0012, 0.0013):
            rec.observe(value)
        agg = rec.aggregate()
        assert agg["min"] <= agg["p95"] <= agg["max"]
        assert agg["p95"] == 0.0013, "зажим сверху обязан вернуть настоящий max, а не границу 0.002"

    def test_p95_takes_the_first_bucket_that_REACHES_the_rank(self) -> None:
        """Ранг сравнивается через ``>=``, а не ``>`` — и разница здесь видна.

        **Добавлен по находке слом-инъекции.** Инъекция «p95 читает не тот
        бакет» (``cumulative >= rank`` → ``cumulative > rank``) не покраснила
        НИ ОДНОГО теста: на прежнем наборе (пять значений в двух соседних
        бакетах) обе версии давали один ответ — при ``>`` перебор доходил до
        конца и возвращал ``max``, который и был правильным ответом. Совпадение
        результата прятало противоположную реализацию.

        Здесь набор подобран так, чтобы версии РАЗОШЛИСЬ: 19 наблюдений из 20
        лежат в одном бакете, двадцатое — далеко справа. Ранг ``ceil(0.95·20)
        = 19`` достигается ровно на этом бакете, значит p95 = его граница.
        Версия с ``>`` проскочила бы бакет и вернула 0.9 — значение выброса,
        то есть ответ ближе к p100, чем к p95.
        """
        rec = _timing()
        for _ in range(19):
            rec.observe(0.0005)
        rec.observe(0.9)
        agg = rec.aggregate()
        assert agg["count"] == 20
        assert agg["max"] == 0.9
        assert agg["p95"] == 0.0005, "ранг достигнут бакетом наблюдений — берётся ЕГО граница"

    def test_timing_on_a_record_created_as_counter_does_not_crash(self) -> None:
        """Столкновение типов под одним именем не роняет эмитента.

        **Найдено прогоном золотого пути.** Ключ записи — имя плюс теги, ТИП в
        него не входит, поэтому ``record_metric("x")`` с последующим
        ``record_timing("x", …)`` достаёт запись типа COUNTER. Пока счётчики
        бакетов заводились только у распределений, второй вызов падал
        ``IndexError`` прямо на горячем пути — регресс против прежней модели,
        которая молча дописывала значение в список.

        Тест сторожит именно ОТСУТСТВИЕ отказа. То, что тайминг под именем
        счётчика в агрегат не попадёт, — отдельный дефект СТАРШЕ задачи 2.2
        (тип не участвует в ключе); он назван в докстринге ``__post_init__`` и
        здесь закрепляется как известное поведение, а не как желаемое.
        """
        mgr = _manager()
        try:
            mgr.record_metric("collide", 1)
            mgr.record_timing("collide", 0.00021)  # не должно бросать
            mgr.histogram("collide", 0.5)
            agg = mgr.get_metric("collide")
            assert agg["type"] == "counter", "тип записи задаёт ПЕРВЫЙ эмитент — известное поведение"
            assert agg["count"] == 1.0
        finally:
            mgr.shutdown()

    def test_histogram_walks_the_same_road_as_timing(self) -> None:
        """Обе дороги — ОДНА механика, и это проверяется совпадением агрегатов.

        Опасность именно здесь: у 2.2 был соблазн починить timing и оставить
        histogram (§2-П5 плана — «воскрешение на соседней развилке»). Тест
        краснеет, если дороги разойдутся хоть одним ключом.
        """
        values = (0.0004, FRAME_60, FRAME_30, 2.5)
        t, h = _timing("x"), _histogram("x")
        for v in values:
            t.add_timing(v)
            h.add_histogram(v)
        agg_t, agg_h = t.aggregate(), h.aggregate()
        assert agg_t.pop("type") == "timing"
        assert agg_h.pop("type") == "histogram"
        assert agg_t == agg_h


# =============================================================================
# Слияние
# =============================================================================


class TestMerge:
    """Ассоциативность — на РАСХОДЯЩИХСЯ числах."""

    @staticmethod
    def _filled(kind: MetricType, values) -> MetricRecord:
        rec = MetricRecord(name="m", metric_type=kind)
        for v in values:
            rec.observe(v)
        return rec

    @pytest.mark.parametrize("kind", [MetricType.TIMING, MetricType.HISTOGRAM])
    def test_distribution_merge_is_associative(self, kind: MetricType) -> None:
        """``(a ⊕ b) ⊕ c == a ⊕ (b ⊕ c)`` на числах из РАЗНЫХ бакетов.

        Совпадающие константы прячут противоположные реализации: три серии по
        одному и тому же значению сошлись бы и при «побеждает последний».
        Здесь у каждой стороны свой бакет, свой размер и свои края.
        """
        a = self._filled(kind, (0.0004, 0.0009))
        b = self._filled(kind, (FRAME_60, FRAME_30, 0.06))
        c = self._filled(kind, (0.9, 4.2, 0.0011, 0.0011))

        left = a.merged_with(b).merged_with(c)
        right = a.merged_with(b.merged_with(c))

        assert left.aggregate() == right.aggregate()
        assert left.obs_count == 9
        assert left.min_value == 0.0004
        assert left.max_value == 4.2
        assert sum(left.bucket_counts) == 9

    def test_merge_does_not_mutate_either_side(self) -> None:
        """Слияние чистое: иначе тест ассоциативности проверял бы порядок вызовов."""
        a = self._filled(MetricType.TIMING, (0.001,))
        b = self._filled(MetricType.TIMING, (0.5, 0.5))
        a.merged_with(b)
        assert a.obs_count == 1 and b.obs_count == 2

    @pytest.mark.parametrize("kind", [MetricType.COUNTER, MetricType.GAUGE, MetricType.TIMING])
    def test_merge_result_shares_no_mutable_object_with_its_sources(self, kind: MetricType) -> None:
        """Результат не делит с исходниками НИ ОДНОГО изменяемого объекта.

        **Добавлен по находке ревью.** ``dataclasses.replace`` копирует поля
        ССЫЛКАМИ: ``tags`` (а у counter и gauge ещё и ``bucket_counts``)
        доставались результату общими с левым аргументом, и правка одного меняла
        второй. Обещание «чистая функция» было неверным ровно там, где его
        читают. Проверяется ИДЕНТИЧНОСТЬ объектов, а не равенство значений:
        равенство держится и у общей ссылки — до первой мутации.
        """
        left = MetricRecord(name="m", metric_type=kind, tags={"env": "prod"})
        right = MetricRecord(name="m", metric_type=kind, tags={"env": "prod"})
        merged = left.merged_with(right)

        assert merged.tags is not left.tags
        assert merged.tags is not right.tags
        assert merged.bucket_counts is not left.bucket_counts
        assert merged.bucket_counts is not right.bucket_counts

        merged.tags["env"] = "test"
        assert left.tags["env"] == "prod", "правка результата дотянулась до исходника"

    def test_counter_merge_is_associative(self) -> None:
        a = MetricRecord(name="c", metric_type=MetricType.COUNTER, count=3.0)
        b = MetricRecord(name="c", metric_type=MetricType.COUNTER, count=11.0)
        c = MetricRecord(name="c", metric_type=MetricType.COUNTER, count=101.0)
        assert a.merged_with(b).merged_with(c).count == a.merged_with(b.merged_with(c)).count == 115.0

    def test_gauge_merge_is_last_wins_and_order_dependent(self) -> None:
        """У gauge ассоциативности НЕТ — и это природа типа, а не дефект.

        Тест закрепляет именно ЭТО, чтобы следующий читатель не «починил»
        gauge сведением к сумме: значение зависит от того, кто правый.
        """
        a = MetricRecord(name="g", metric_type=MetricType.GAUGE, value=1.0)
        b = MetricRecord(name="g", metric_type=MetricType.GAUGE, value=2.0)
        assert a.merged_with(b).value == 2.0
        assert b.merged_with(a).value == 1.0

    def test_merge_of_different_types_refuses_loudly(self) -> None:
        """Молча выбрать один из двух типов значило бы отдать число без смысла."""
        a = MetricRecord(name="m", metric_type=MetricType.TIMING)
        b = MetricRecord(name="m", metric_type=MetricType.COUNTER)
        with pytest.raises(ValueError, match="разных типов"):
            a.merged_with(b)


# =============================================================================
# Страж кардинальности
# =============================================================================


class TestCardinalityGuard:
    def test_known_key_passes_even_at_a_full_ceiling(self) -> None:
        """Уже заведённая серия проходит ВСЕГДА.

        Самая дорогая ошибка потолка: если он начнёт отказывать известным
        ключам, живая метрика замолчит ровно в тот момент, когда справочник
        переполнится ЧУЖИМИ сериями. Потолок 3 — вдали от дефолта 1000.
        """
        guard = CardinalityGuard(3)
        known = {}
        for i in range(3):
            key = f"k{i}"
            assert guard.allow(key, known, key) is True
            known[key] = object()

        assert guard.allow("new", known, "new") is False
        for key in list(known):
            assert guard.allow(key, known, key) is True, "известный ключ обязан пройти под потолком"

    def test_zero_means_no_limit(self) -> None:
        guard = CardinalityGuard(0)
        known = {f"k{i}": object() for i in range(500)}
        assert guard.allow("k500", known, "k500") is True
        assert guard.report()["series"] == 0
        assert guard.report()["observations"] == 0

    def test_voice_fires_once_per_condition_and_carries_number_names_and_knob(self) -> None:
        """Голос — один раз на условие, но с ПОЛНЫМИ числами такта.

        Опасность двусторонняя: WARNING на каждый отказ превратил бы горячий
        путь в шторм, а голос, произнесённый в момент перехода в упор, всегда
        сообщал бы «опущено 1, имя одно» — переход-то случается на ПЕРВОМ
        отказе. Поэтому долг копится, а произносится на такте окна. Потолок 2
        и семь отказов — числа вдали от дефолта 1000.
        """
        said = []
        guard = CardinalityGuard(2, position="живой слой", warn=said.append)
        known = {"a": 1, "b": 2}
        for i in range(7):
            guard.allow(f"x{i}", known, f"x{i}")
        guard.speak()
        guard.speak()

        assert len(said) == 1, "второй голос на том же условии — шторм"
        text = said[0]
        assert "живой слой" in text
        assert "observability.stats.max_series" in text
        assert "7 эмиссий" in text, "голос обязан нести числа такта, а не первой секунды"
        assert "опущено серий" in text, "серии и эмиссии в голосе названы РАЗДЕЛЬНО"
        assert "x0" in text and "x4" in text
        assert guard.report()["observations"] == 7

    def test_voice_remembers_at_most_five_distinct_names(self) -> None:
        """K=5 РАЗЛИЧНЫХ имён: судить поимённо, но не превращать голос во второй взрыв."""
        said = []
        guard = CardinalityGuard(1, warn=said.append)
        known = {"a": 1}
        for i in range(20):
            guard.allow(f"key{i}", known, f"name{i % 9}")
        guard.speak()
        names = guard.report()["names"]
        assert len(names) == VOICE_NAME_LIMIT
        assert names == [f"name{i}" for i in range(VOICE_NAME_LIMIT)]

    def test_voice_returns_after_the_condition_lifts(self) -> None:
        """Потолок отпустило и снова упёрло — оператор обязан услышать второй раз."""
        said = []
        guard = CardinalityGuard(2, warn=said.append)
        known = {"a": 1, "b": 2}
        guard.allow("c", known, "c")
        guard.speak()
        assert len(said) == 1

        known.pop("a")  # окно почистилось / серию убрали
        guard.allow("d", known, "d")  # прошла — мы снова под потолком
        guard.speak()
        known["d"] = 1
        guard.allow("e", known, "e")
        guard.speak()
        assert len(said) == 2

    def test_set_limit_restores_the_right_to_speak(self) -> None:
        """Смена потолка — смена УСЛОВИЯ, голос обязан прозвучать заново."""
        said = []
        guard = CardinalityGuard(1, warn=said.append)
        known = {"a": 1}
        guard.allow("b", known, "b")
        guard.speak()
        guard.set_limit(2)
        assert guard.limit == 2
        known["b"] = 1
        guard.allow("c", known, "c")
        guard.speak()
        assert len(said) == 2

    def test_take_report_resets_but_report_keeps_the_lifetime_total(self) -> None:
        """Два счётчика — два вопроса. Один на оба ответа врал бы на любом из них."""
        guard = CardinalityGuard(1)
        known = {"a": 1}
        for i in range(4):
            guard.allow(f"x{i}", known, f"x{i}")
        assert guard.take_report()["observations"] == 4
        assert guard.take_report()["observations"] == 0, "период окна обнулился"
        assert guard.report()["observations"] == 4, "срок процесса — нет"
        assert guard.report()["names"] == ["x0", "x1", "x2", "x3"], "имена за срок тоже пережили"


# =============================================================================
# Окно агрегации: страж, снапшот, порядок
# =============================================================================


class TestWindowGuard:
    def test_snapshot_counts_omitted_series_and_names_them(self) -> None:
        """``total_count`` — сколько БЫЛО, а не сколько доехало.

        По этой разности снаружи считают опущенное (``snapshot_message``,
        заголовок ``performance.log``). Стань ``total_count`` числом доехавших
        — потеря исчезла бы из виду при полностью зелёной доставке.
        """
        sent = []
        guard = CardinalityGuard(5)
        window = AggregationWindow(flush_fn=lambda ch, batch: sent.append(batch) or len(batch), guard=guard)
        for i in range(9):
            window.enqueue("c", {"type": "counter", "name": f"m{i}", "value": 1})
        window.flush_all()

        snapshot = sent[0][0]
        assert len(snapshot["metrics"]) == 5
        assert snapshot["total_count"] == 9
        assert snapshot["series_dropped"] == 4
        assert snapshot["observations_dropped"] == 4, "по одной эмиссии на серию — числа совпали законно"
        assert snapshot["dropped_series"] == ["m5", "m6", "m7", "m8"]
        assert "series_dropped_is_lower_bound" not in snapshot

    def test_repeated_emissions_of_refused_series_do_not_inflate_total_count(self) -> None:
        """Шесть эмиссий ТРЁХ отказанных серий — ``total_count == 6``, а не 12.

        **Воспроизведение находки ревью, дословно.** Страж зовут заново на
        КАЖДУЮ эмиссию отказанной серии: ключа в словаре так и нет, мембершип
        не срабатывает. Пока «опущено» считало эмиссии, запись в сторе
        говорила ``total_count=12, доехало=3, series_dropped=9`` при шести
        настоящих сериях — и противоречила сама себе: девять опущенных рядом с
        тремя именами. Живой прогон подтвердил то же: счётчик шёл 18 → 22 без
        единой НОВОЙ серии.

        Число эмиссий не выброшено — оно едет рядом и отвечает на свой вопрос.
        """
        sent = []
        guard = CardinalityGuard(3)
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b), guard=guard)

        for _ in range(2):  # два круга по всем шести сериям
            for i in range(6):
                window.enqueue("c", {"type": "counter", "name": f"seg{i}", "value": 1})
        window.flush_all()

        snapshot = sent[0][0]
        assert len(snapshot["metrics"]) == 3
        assert snapshot["total_count"] == 6, "серий было шесть — три доехали, три опущены"
        assert snapshot["series_dropped"] == 3
        assert snapshot["observations_dropped"] == 6, "эмиссий отвергнуто вдвое больше, чем серий"
        assert snapshot["dropped_series"] == ["seg3", "seg4", "seg5"]
        assert "series_dropped_is_lower_bound" not in snapshot

    def test_saturated_key_set_says_the_number_is_a_lower_bound(self) -> None:
        """Множество отказанных ключей упёрлось — число обязано назваться оценкой.

        Множество ограничено тем же ``max_series``: наивный ``set`` взорвался
        бы ровно на потоке уникальных ключей, то есть на сценарии, который
        потолок и лечит. Но заниженное число, выданное как точное, — та самая
        молчаливая оценка, ради которой весь этап и затевался. Потолок 4 и
        30 серий — вдали от дефолта.
        """
        sent = []
        guard = CardinalityGuard(4)
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b), guard=guard)
        for i in range(30):
            window.enqueue("c", {"type": "counter", "name": f"u{i}", "value": 1})
        window.flush_all()

        snapshot = sent[0][0]
        # Потолок множества — max(limit, K имён) = max(4, 5) = 5: число опущенных
        # серий не имеет права оказаться меньше числа имён рядом с ним.
        assert snapshot["series_dropped"] == 5, "различных ключей запомнено ровно столько, сколько влезло"
        assert snapshot["series_dropped_is_lower_bound"] is True
        assert snapshot["observations_dropped"] == 26, "эмиссии считаются все, они не требуют памяти"
        assert snapshot["total_count"] == 9, "4 доехали + 5 известных опущенных — и это ОЦЕНКА СНИЗУ"
        assert snapshot["series_dropped"] >= len(snapshot["dropped_series"])

    def test_series_dropped_is_never_smaller_than_the_names_beside_it(self) -> None:
        """``series_dropped >= len(dropped_series)`` — иначе запись врёт сама себе.

        **Найдено прогоном золотого пути, а не чтением.** Множество отказанных
        ключей ограничено ``max_series``, а имён запоминается до пяти — при
        потолке 3 запись выдавала «опущено серий 3» рядом с ЧЕТЫРЬМЯ именами.
        Это то же самопротиворечие, из-за которого счёт эмиссий и признали
        дефектом, только меньшего масштаба. Потолок множества поднят до
        ``max(limit, K)``; на дефолте 1000 это ничего не меняет.
        """
        sent = []
        guard = CardinalityGuard(2)
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b), guard=guard)
        for i in range(12):
            window.enqueue("c", {"type": "counter", "name": f"z{i}", "value": 1})
        window.flush_all()

        snapshot = sent[0][0]
        assert snapshot["series_dropped"] >= len(snapshot["dropped_series"])
        assert snapshot["series_dropped_is_lower_bound"] is True

    def test_snapshot_omits_the_drop_keys_when_nothing_was_dropped(self) -> None:
        sent = []
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b), guard=CardinalityGuard(50))
        window.enqueue("c", {"type": "counter", "name": "m", "value": 1})
        window.flush_all()
        assert "series_dropped" not in sent[0][0]
        assert "dropped_series" not in sent[0][0]

    def test_bucket_bounds_ride_once_per_snapshot_and_only_when_needed(self) -> None:
        """Границы едут ОДИН раз и только при наличии распределения.

        В каждой записи они стоили бы байт на дороге с пределом строки 2048;
        не ехать вовсе они не могут — константа переживёт запись в сторе.
        """
        sent = []
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b))
        window.enqueue("c", {"type": "counter", "name": "only_counter", "value": 1})
        window.flush_all()
        assert "bucket_bounds" not in sent[0][0]

        window.enqueue("c", {"type": "timing", "name": "t", "value": FRAME_60})
        window.flush_all()
        snapshot = sent[1][0]
        assert snapshot["bucket_bounds"] == list(DEFAULT_DURATION_BUCKETS_SEC)
        assert all("bucket_bounds" not in m for m in snapshot["metrics"])

    def test_window_drop_counters_belong_to_the_window(self) -> None:
        """Опущенное в прошлом окне не имеет права подсвечивать следующее."""
        sent = []
        guard = CardinalityGuard(3)
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b), guard=guard)
        for i in range(5):
            window.enqueue("c", {"type": "counter", "name": f"a{i}", "value": 1})
        window.flush_all()
        assert sent[0][0]["series_dropped"] == 2

        window.enqueue("c", {"type": "counter", "name": "b", "value": 1})
        window.flush_all()
        assert "series_dropped" not in sent[1][0]

    def test_emission_from_a_foreign_thread_during_flush_does_not_lose_the_snapshot(self) -> None:
        """Эмиссия из чужого потока во время ``flush_all`` — оба числа целы.

        ``flush_all`` строит снапшот и чистит окно под тем же локом, под
        которым идёт ``enqueue``. Опасность — не гонка данных (лок её
        закрывает), а АРИФМЕТИКА: запись, пришедшая между построением снапшота
        и чисткой, исчезла бы бесследно. Сумма по всем снапшотам обязана
        сойтись с числом эмиссий.
        """
        sent = []
        window = AggregationWindow(flush_fn=lambda ch, b: sent.append(b) or len(b))
        stop = threading.Event()
        emitted = 0

        def writer() -> None:
            nonlocal emitted
            while not stop.is_set():
                window.enqueue("c", {"type": "counter", "name": "hot", "value": 1})
                emitted += 1

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        for _ in range(40):
            window.flush_all()
            time.sleep(0.001)
        stop.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "поток-писатель завис — значит лок не отпускался"
        window.flush_all(include_empty=True)

        delivered = sum(m["count"] for batch in sent for snap in batch for m in snap["metrics"])
        assert delivered == emitted


# =============================================================================
# Менеджер: две позиции, подмена окна, ручка
# =============================================================================


def _manager(**cfg) -> StatsManager:
    base = {"enable_logging": False, "channels": {"file_stats": {"enabled": False}}}
    base.update(cfg)
    return StatsManager(config=base)


class TestManagerPositions:
    def test_live_layer_refusal_does_not_stop_delivery(self) -> None:
        """Р2.2-7: стражи независимы — отказ справочника не трогает окно.

        Потерять доставку ради ограничения ``get_metric`` было бы дороже
        болезни. Потолок 4 — вдали от дефолта.
        """
        mgr = _manager(max_series=7)
        for i in range(10):
            mgr.record_metric(f"n{i}")
            mgr.record_metric(f"n{i}")  # второй круг: эмиссий вдвое больше, чем серий

        assert len(mgr.get_all_metrics()) == 7
        stats = mgr.get_stats()
        assert stats["series_dropped"] == 3, "СЕРИЙ не пущено три"
        assert stats["observations_dropped"] == 6, "ЭМИССИЙ отвергнуто шесть — это другое число"
        assert stats["series_dropped_is_lower_bound"] is False
        assert stats["max_series"] == 7
        # Окно живёт своим стражем с тем же потолком — но это ДРУГОЙ счётчик.
        assert stats["window_observations_dropped"] == 6
        assert mgr._buffer.stats["total_enqueued"] == 20, "эмиссия состоялась для всех двадцати"

    def test_known_series_keeps_recording_after_the_live_layer_filled_up(self) -> None:
        """Уже наблюдаемая метрика не замолкает от переполнения справочника."""
        mgr = _manager(max_series=2)
        mgr.record_metric("kept", 1)
        mgr.record_metric("second", 1)
        for i in range(5):
            mgr.record_metric(f"junk{i}")
        mgr.record_metric("kept", 41)
        assert mgr.get_metric("kept")["count"] == 42

    def test_guard_survives_the_window_swap(self) -> None:
        """Смена темпа подменяет окно — страж обязан переехать, а не умереть.

        Опасность порядка: страж, созданный внутри окна, уехал бы вместе с
        ним, унеся потолок, счёт опущенных и право на голос. Проверяется
        ЛИЧНОСТЬ объекта, а не только работоспособность: новый страж с тем же
        потолком выглядел бы снаружи так же и потерял бы накопленное.
        """
        mgr = _manager(max_series=3, aggregation_interval=1.0, flush_interval=1.0)
        guard_before = mgr._buffer._guard
        for i in range(6):
            mgr.record_metric(f"m{i}")
        assert mgr.get_stats()["window_observations_dropped"] == 3

        mgr.reconfigure({"enable_logging": False, "max_series": 3, "aggregation_interval": 4.0, "flush_interval": 4.0})

        assert mgr._buffer.flush_interval == 4.0, "темп сменился — окно обязано быть новым"
        assert mgr._buffer._guard is guard_before, "страж переехал в новое окно тем же объектом"
        assert mgr.get_stats()["window_observations_dropped"] == 3, "счёт за срок процесса пережил подмену"

    def test_max_series_alone_reaches_the_window_without_a_tempo_change(self) -> None:
        """Ручка действует, даже когда окно НЕ подменяется.

        ``_swap_aggregation_window`` выходит рано при неизменном темпе. Пока
        потолок обновлялся только там, правка одного лишь ``max_series``
        выглядела бы применённой (она в конфиге и в readback'е) и не значила
        бы ничего — ровно тот дефект, которым уже болели темп и предел строки.
        """
        mgr = _manager(max_series=3)
        tempo_before = mgr._buffer.flush_interval

        mgr.reconfigure({"enable_logging": False, "max_series": 11})

        assert mgr._buffer.flush_interval == tempo_before, "темп не менялся — окно то же"
        assert mgr._buffer._guard.limit == 11
        assert mgr._live_guard.limit == 11
        assert mgr.observability_readback()["max_series"] == 11

    def test_both_guards_hold_the_same_limit(self) -> None:
        """Расхождение потолков двух позиций было бы дефектом одной ручки.

        Судим ПОВЕДЕНИЕМ, а не хранимым числом. Прежняя редакция сверяла
        ``limit == limit == 17`` и переживала инъекцию «потолок снят»
        (``allow`` пускает всех) полностью зелёной: сохранённое число оставалось
        на месте, держать перестал только сам потолок. Тест с именем
        «оба стража держат потолок» обязан умирать от того, что потолок
        перестал держать, — иначе он сторожит имя, а не свойство.
        """
        mgr = _manager(max_series=17)
        assert mgr._live_guard.limit == mgr._window_guard.limit == 17

        # 17 разрешено, 18-я серия отвергается на ОБЕИХ позициях.
        for i in range(25):
            mgr.record_metric("cap.probe", tags={"i": str(i)})
        assert len(mgr._metrics) == 17, "живой слой пустил больше потолка"
        stats = mgr.get_stats()
        assert stats["series_dropped"] == 8, "восемь РАЗЛИЧНЫХ серий не пущено в живой слой"
        assert stats["window_observations_dropped"] == 8, "окно отвергло столько же — потолок у него тот же"

    def test_readback_reads_the_live_guard_not_the_config(self) -> None:
        """Ручка, которую нельзя прочитать, неотличима от неприменённой.

        Пересчёт из конфига вернул бы запрошенное число даже при несработавшей
        пересборке — поэтому readback спрашивают у живого стража. Тест портит
        конфиг и проверяет, что readback идёт за стражем, а не за словарём.
        """
        mgr = _manager(max_series=9)
        mgr._config_dict["max_series"] = 999_999
        assert mgr.observability_readback()["max_series"] == 9

    def test_the_knob_travels_the_whole_three_point_road(self) -> None:
        """Ручка проходит ВСЮ дорогу: секция ``observability`` → фасад → менеджер → readback.

        **Добавлен по находке слом-инъекции.** Инъекция «ключ убран из
        ``expand_observability``» не покраснила НИ ОДНОГО теста во всём
        корпусе: мои проверки звали менеджер напрямую словарём, то есть В ОБХОД
        дороги, которой ходит процесс. Ровно этот класс уже стоил задаче 3.4
        живого ``failed`` на восьми процессах, а Ф6.х.8 — неработающего темпа:
        ключ есть в схеме, виден оператору и не доезжает до менеджера.

        Число 23 — вдали от дефолта 1000: совпади оно с дефолтом, тест был бы
        зелёным и при полностью оторванном фасаде.
        """
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        expanded = expand_observability({"stats": {"max_series": 23, "enabled": False}})
        assert expanded["stats"]["max_series"] == 23, "фасад обязан положить ключ в конфиг менеджера"

        mgr = StatsManager(config={**expanded["stats"], "channels": {"file_stats": {"enabled": False}}})
        try:
            assert mgr._live_guard.limit == 23
            assert mgr._window_guard.limit == 23
            assert mgr.observability_readback()["max_series"] == 23
        finally:
            mgr.shutdown()

    def test_default_comes_from_the_schema_not_a_second_literal(self) -> None:
        """Дефолт проверяется против ``model_fields``, а не второй копией числа."""
        assert StatsManagerConfig.model_fields["max_series"].default == DEFAULT_MAX_SERIES
        assert _manager()._live_guard.limit == StatsManagerConfig.model_fields["max_series"].default

    def test_two_positions_use_two_different_locks(self) -> None:
        """Эмиссия из чужого потока при закрытии окна не вешает менеджер.

        Живой слой и окно защищены РАЗНЫМИ локами
        (``_metrics_lock`` и ``AggregationWindow._lock``), и страж зовётся под
        каждым из них. Голос стража при этом уходит в логгер — то есть за
        пределы своего лока; сделай он это изнутри, tap логгера, эмитящий
        метрику, замкнул бы ``allow → warning → record_metric → enqueue`` на
        нереентерабельном локе. Тест гоняет обе позиции в упор с двух потоков
        и требует, чтобы всё закончилось за отведённое время.
        """
        mgr = _manager(max_series=6)
        stop = threading.Event()
        errors = []

        def hammer(prefix: str) -> None:
            try:
                i = 0
                while not stop.is_set():
                    mgr.record_timing(f"{prefix}{i % 40}", 0.002)
                    i += 1
            except Exception as exc:  # noqa: BLE001 — падение потока обязано быть видно
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(p,), daemon=True) for p in ("a", "b")]
        for t in threads:
            t.start()
        for _ in range(30):
            mgr.flush()
            time.sleep(0.001)
        stop.set()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive(), "поток не завершился — взаимная блокировка на локе стража"
        assert not errors, errors
