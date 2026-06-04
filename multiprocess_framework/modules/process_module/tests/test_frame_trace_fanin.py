# -*- coding: utf-8 -*-
"""Тесты fan-out/fan-in trace — Task 3.1 из plans/frame-trace-fanin.md.

Покрывает:
- fork_trace: независимость trace-копий при fan-out (ловит shared-list баг до b0f8bc14)
- merge_trace: critical-path выбор (max сумма ms, НЕ items[0])
- merge_trace: trace_branches сводка (N записей с total_ms/spans/branch)
- merge_trace: размер O(глубина одной ветви), не растёт от числа ветвей
- record_merge: дописывает merge-спан в конец trace
- no-op без флага: fork_trace/{}, merge_trace/([], [], ""), record_merge/no-op
- edge cases: пустая коллекция, items без trace, все ветви с пустым trace
"""

import pytest

from multiprocess_framework.modules.process_module.generic import frame_trace


# ---------------------------------------------------------------------------
# Фикстуры управления флагом (паттерн из test_frame_trace.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_on():
    """Включить трассировку на время теста; восстановить флаг в teardown."""
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = True
    yield
    frame_trace._ENABLED = prev


@pytest.fixture
def trace_off():
    """Выключить трассировку на время теста; восстановить флаг в teardown."""
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = False
    yield
    frame_trace._ENABLED = prev


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_item(spans: list[dict] | None = None, region_name: str | None = None) -> dict:
    """Создать item с trace и опциональным region_name."""
    item: dict = {}
    if spans is not None:
        item["trace"] = list(spans)
    if region_name is not None:
        item["region_name"] = region_name
    return item


def _span(ms: float) -> dict:
    """Простой process-спан с заданным ms."""
    return {"kind": "process", "node": "test_node", "plugin": "test_plugin", "ms": ms}


# ---------------------------------------------------------------------------
# 1. fork_trace — независимость trace-копий при fan-out
# ---------------------------------------------------------------------------


class TestForkTrace:
    """Тесты fork_trace (fan-out семантика)."""

    def test_two_fanout_items_have_independent_traces(self, trace_on) -> None:
        """Два out-item из одного item ДОЛЖНЫ иметь РАЗНЫЕ list-объекты trace.

        Этот тест падал на shared-ссылке ДО фикса b0f8bc14:
        {**item} копировал dict поверхностно → trace оставался ОДНОЙ ссылкой,
        мутация любого region загрязняла все остальные.
        """
        parent = _make_item(spans=[_span(5.0)], region_name="root")

        # Имитируем fan-out: два региона из одного родителя
        out_a = {**parent, "frame": "crop_a", **frame_trace.fork_trace(parent)}
        out_b = {**parent, "frame": "crop_b", **frame_trace.fork_trace(parent)}

        # Мутируем trace out_a — добавляем новый спан
        out_a["trace"].append(_span(10.0))

        # out_b НЕ должен видеть спан из out_a (разные list-объекты)
        assert out_a["trace"] is not out_b["trace"], "trace — разные list-объекты (не shared)"
        assert len(out_b["trace"]) == 1, "мутация out_a не должна затрагивать out_b"

    def test_fork_trace_returns_dict_with_trace_key(self, trace_on) -> None:
        """fork_trace возвращает dict с ключом 'trace' при включённом флаге."""
        parent = _make_item(spans=[_span(3.0)])
        result = frame_trace.fork_trace(parent)
        assert isinstance(result, dict)
        assert "trace" in result
        assert isinstance(result["trace"], list)

    def test_fork_trace_copy_is_independent_from_parent(self, trace_on) -> None:
        """fork_trace — копия, не ссылка на родительский trace."""
        parent = _make_item(spans=[_span(2.0)])
        result = frame_trace.fork_trace(parent)

        # Мутируем родительский trace после fork
        parent["trace"].append(_span(99.0))

        # Копия не должна отражать мутацию родителя
        assert len(result["trace"]) == 1, "fork — независимая копия, не ссылка на parent"

    def test_fork_trace_noop_without_flag(self, trace_off) -> None:
        """Без флага fork_trace возвращает {} (нет аллокаций)."""
        parent = _make_item(spans=[_span(5.0)])
        result = frame_trace.fork_trace(parent)
        assert result == {}, "no-op без флага: fork_trace -> {}"

    def test_fork_trace_item_without_trace_key(self, trace_on) -> None:
        """fork_trace на item без ключа 'trace' — graceful, возвращает пустой список."""
        parent = {"frame": "data", "seq_id": 42}  # нет trace
        result = frame_trace.fork_trace(parent)
        assert result == {"trace": []}

    def test_fork_trace_fanout_noop_flag_off(self, trace_off) -> None:
        """Без флага {**item, **fork_trace(item)} не добавляет 'trace'."""
        parent = {"frame": "data"}  # нет trace
        out = {**parent, **frame_trace.fork_trace(parent)}
        assert "trace" not in out, "без флага trace не появляется в out-item"


# ---------------------------------------------------------------------------
# 2. merge_trace — critical-path (max сумма ms)
# ---------------------------------------------------------------------------


class TestMergeTraceCriticalPath:
    """Тесты merge_trace: выбор ветви-победителя по критическому пути."""

    def test_winner_is_max_sum_not_items0(self, trace_on) -> None:
        """Победитель — ветвь с MAX суммой ms, НЕ items[0].

        Специально ставим победителя на items[1], чтобы тест не прошёл
        случайно на реализации 'всегда items[0]'.
        """
        item0 = _make_item(spans=[_span(3.0), _span(2.0)], region_name="region_0")  # total=5
        item1 = _make_item(spans=[_span(8.0), _span(5.0)], region_name="region_1")  # total=13 ← победитель
        item2 = _make_item(spans=[_span(1.0)], region_name="region_2")  # total=1

        trace, branches, chosen = frame_trace.merge_trace([item0, item1, item2])

        assert chosen == "region_1", f"ожидали region_1 (max ms=13), получили {chosen}"
        # trace должен быть копией trace item1
        assert trace == item1["trace"]
        assert trace is not item1["trace"], "trace — копия, не shared-ссылка"

    def test_winner_trace_is_copy_not_reference(self, trace_on) -> None:
        """merge_trace возвращает КОПИЮ trace победителя (не ссылку)."""
        item0 = _make_item(spans=[_span(10.0)], region_name="slow")
        item1 = _make_item(spans=[_span(1.0)], region_name="fast")

        trace, _, _ = frame_trace.merge_trace([item0, item1])

        # Мутируем оригинальный trace победителя
        item0["trace"].append(_span(999.0))
        # Возвращённый trace не должен меняться
        assert len(trace) == 1, "merge_trace вернул независимую копию"

    def test_chosen_name_from_region_name(self, trace_on) -> None:
        """chosen берётся из 'region_name' item'а."""
        item0 = _make_item(spans=[_span(5.0)], region_name="my_region")
        item1 = _make_item(spans=[_span(1.0)], region_name="other")

        _, _, chosen = frame_trace.merge_trace([item0, item1])
        assert chosen == "my_region"

    def test_chosen_fallback_name_when_no_region_name(self, trace_on) -> None:
        """Если region_name отсутствует — fallback 'branch_<idx>'."""
        item0 = _make_item(spans=[_span(1.0)])  # нет region_name → branch_0
        item1 = _make_item(spans=[_span(9.0)])  # нет region_name → branch_1

        _, _, chosen = frame_trace.merge_trace([item0, item1])
        assert chosen == "branch_1", f"fallback имя должно быть branch_1, получили {chosen}"

    def test_single_item_wins(self, trace_on) -> None:
        """Один item — он же победитель, chosen = его имя."""
        item = _make_item(spans=[_span(5.0)], region_name="only")
        trace, branches, chosen = frame_trace.merge_trace([item])
        assert chosen == "only"
        assert len(branches) == 1

    def test_merge_trace_noop_without_flag(self, trace_off) -> None:
        """Без флага merge_trace возвращает ([], [], '') — нулевой overhead."""
        items = [_make_item(spans=[_span(5.0)]) for _ in range(3)]
        result = frame_trace.merge_trace(items)
        assert result == ([], [], ""), f"no-op без флага: {result}"


# ---------------------------------------------------------------------------
# 3. merge_trace — trace_branches сводка
# ---------------------------------------------------------------------------


class TestMergeTraceBranches:
    """Тесты корректности trace_branches (сводка по всем ветвям)."""

    def test_trace_branches_count(self, trace_on) -> None:
        """trace_branches содержит запись для КАЖДОЙ входной ветви."""
        items = [_make_item(spans=[_span(5.0)], region_name=f"region_{i}") for i in range(3)]
        _, branches, _ = frame_trace.merge_trace(items)
        assert len(branches) == 3, "по одной записи на каждую входную ветвь"

    def test_trace_branches_correct_total_ms(self, trace_on) -> None:
        """trace_branches содержит корректный total_ms (сумма ms спанов ветви)."""
        item0 = _make_item(spans=[_span(3.0), _span(2.0)], region_name="region_0")  # total=5
        item1 = _make_item(spans=[_span(8.0)], region_name="region_1")  # total=8
        item2 = _make_item(spans=[_span(1.5), _span(1.5)], region_name="region_2")  # total=3

        _, branches, _ = frame_trace.merge_trace([item0, item1, item2])

        totals = {b["branch"]: b["total_ms"] for b in branches}
        assert totals["region_0"] == pytest.approx(5.0)
        assert totals["region_1"] == pytest.approx(8.0)
        assert totals["region_2"] == pytest.approx(3.0)

    def test_trace_branches_correct_spans_count(self, trace_on) -> None:
        """trace_branches содержит корректный spans (число спанов в ветви)."""
        item0 = _make_item(spans=[_span(1.0), _span(2.0)], region_name="region_0")  # 2 спана
        item1 = _make_item(spans=[_span(5.0)], region_name="region_1")  # 1 спан

        _, branches, _ = frame_trace.merge_trace([item0, item1])

        spans_map = {b["branch"]: b["spans"] for b in branches}
        assert spans_map["region_0"] == 2
        assert spans_map["region_1"] == 1

    def test_trace_branches_has_branch_field(self, trace_on) -> None:
        """Каждая запись trace_branches содержит поля branch/total_ms/spans."""
        item0 = _make_item(spans=[_span(3.0)], region_name="r0")
        item1 = _make_item(spans=[_span(7.0)], region_name="r1")

        _, branches, _ = frame_trace.merge_trace([item0, item1])

        for b in branches:
            assert "branch" in b, "поле 'branch' обязательно"
            assert "total_ms" in b, "поле 'total_ms' обязательно"
            assert "spans" in b, "поле 'spans' обязательно"


# ---------------------------------------------------------------------------
# 4. merge_trace — размер O(глубина одной ветви)
# ---------------------------------------------------------------------------


class TestMergeTraceSize:
    """trace не должен расти от числа ветвей (не union, а critical path)."""

    def test_trace_size_equals_winner_depth_not_sum(self, trace_on) -> None:
        """Размер trace = len(trace победителя), НЕ сумма по всем ветвям."""
        winner_spans = [_span(10.0), _span(5.0), _span(8.0)]  # 3 спана, total=23
        loser_spans = [_span(1.0)] * 10  # 10 спанов, total=10

        item_winner = _make_item(spans=winner_spans, region_name="slow")
        item_loser = _make_item(spans=loser_spans, region_name="fast")

        trace, _, _ = frame_trace.merge_trace([item_winner, item_loser])

        assert len(trace) == 3, (
            f"trace должен содержать {len(winner_spans)} спана (только победитель), "
            f"получили {len(trace)} (возможно union всех ветвей)"
        )

    def test_trace_size_not_affected_by_fanout_width(self, trace_on) -> None:
        """Ширина fan-out (число ветвей) не влияет на размер trace merged-кадра."""
        winner_depth = 4
        winner = _make_item(
            spans=[_span(10.0)] * winner_depth,
            region_name="slow_branch",
        )
        # 9 быстрых ветвей с длинными trace
        losers = [_make_item(spans=[_span(0.1)] * 20, region_name=f"fast_{i}") for i in range(9)]

        trace, _, _ = frame_trace.merge_trace([winner] + losers)

        assert len(trace) == winner_depth, (
            f"trace размер = глубина победителя ({winner_depth}), "
            f"не растёт от ширины fan-out (10 ветвей); получили {len(trace)}"
        )


# ---------------------------------------------------------------------------
# 5. record_merge — добавляет merge-спан
# ---------------------------------------------------------------------------


class TestRecordMerge:
    """Тесты record_merge."""

    def test_record_merge_appends_span(self, trace_on) -> None:
        """record_merge дописывает merge-спан в конец trace item'а."""
        item = _make_item(spans=[_span(5.0)])
        initial_len = len(item["trace"])

        frame_trace.record_merge(item, node="stitcher", branches=3, chosen="region_0", ms=1.5)

        assert len(item["trace"]) == initial_len + 1, "merge-спан должен дописаться"
        span = item["trace"][-1]
        assert span["kind"] == "merge"
        assert span["node"] == "stitcher"
        assert span["branches"] == 3
        assert span["chosen"] == "region_0"
        assert span["ms"] == pytest.approx(1.5)

    def test_record_merge_span_at_the_end(self, trace_on) -> None:
        """merge-спан добавляется ПОСЛЕДНИМ (не в начало, не в середину)."""
        item = _make_item(spans=[_span(2.0), _span(3.0)])
        frame_trace.record_merge(item, node="stitcher", branches=2, chosen="r0")

        last_span = item["trace"][-1]
        assert last_span["kind"] == "merge", "merge-спан — последний в trace"

    def test_record_merge_ms_none_becomes_zero(self, trace_on) -> None:
        """При ms=None merge-спан получает ms=0."""
        item: dict = {}
        frame_trace.record_merge(item, node="stitcher", branches=2, chosen="r0", ms=None)

        span = item["trace"][-1]
        assert span["ms"] == 0

    def test_record_merge_creates_trace_if_missing(self, trace_on) -> None:
        """record_merge создаёт item['trace'] если ключа нет."""
        item: dict = {}
        frame_trace.record_merge(item, node="stitcher", branches=1, chosen="r0")

        assert "trace" in item
        assert len(item["trace"]) == 1

    def test_record_merge_noop_without_flag(self, trace_off) -> None:
        """Без флага record_merge — no-op, trace не меняется."""
        item = _make_item(spans=[_span(5.0)])
        original_trace = list(item["trace"])

        frame_trace.record_merge(item, node="stitcher", branches=3, chosen="r0", ms=2.0)

        assert item["trace"] == original_trace, "no-op без флага: trace не изменён"

    def test_record_merge_noop_on_item_without_trace(self, trace_off) -> None:
        """Без флага record_merge не создаёт ключ trace."""
        item: dict = {}
        frame_trace.record_merge(item, node="stitcher", branches=2, chosen="r0")
        assert "trace" not in item, "no-op без флага: trace не создаётся"


# ---------------------------------------------------------------------------
# 6. No-op без флага (сводные тесты)
# ---------------------------------------------------------------------------


class TestNoopWithoutFlag:
    """Полная no-op семантика без флага."""

    def test_fork_trace_returns_empty_dict(self, trace_off) -> None:
        """fork_trace без флага → {}."""
        item = _make_item(spans=[_span(5.0)])
        assert frame_trace.fork_trace(item) == {}

    def test_merge_trace_returns_empty_tuple(self, trace_off) -> None:
        """merge_trace без флага → ([], [], '')."""
        items = [_make_item(spans=[_span(i)]) for i in range(3)]
        assert frame_trace.merge_trace(items) == ([], [], "")

    def test_merge_trace_empty_collection_without_flag(self, trace_off) -> None:
        """merge_trace([]) без флага → ([], [], '')."""
        assert frame_trace.merge_trace([]) == ([], [], "")


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Граничные случаи."""

    def test_merge_trace_empty_collection(self, trace_on) -> None:
        """merge_trace([]) с флагом не падает → ([], [], '')."""
        result = frame_trace.merge_trace([])
        assert result == ([], [], ""), f"пустая коллекция → ([], [], ''), получили {result}"

    def test_merge_trace_items_without_trace(self, trace_on) -> None:
        """Все items без ключа 'trace' (флаг включён) — graceful, total_ms=0."""
        items = [{"frame": "data", "region_name": f"region_{i}"} for i in range(3)]
        trace, branches, chosen = frame_trace.merge_trace(items)

        # Не должно быть исключения; chosen — первый (все ms=0, winner=items[0])
        assert isinstance(trace, list)
        assert isinstance(branches, list)
        assert len(branches) == 3
        for b in branches:
            assert b["total_ms"] == pytest.approx(0.0)
            assert b["spans"] == 0

    def test_merge_trace_all_empty_traces_winner_is_first(self, trace_on) -> None:
        """Все ветви с пустым trace → chosen = items[0] (все ms=0, max → первый)."""
        item0 = _make_item(spans=[], region_name="first")
        item1 = _make_item(spans=[], region_name="second")
        item2 = _make_item(spans=[], region_name="third")

        trace, branches, chosen = frame_trace.merge_trace([item0, item1, item2])

        # При одинаковых ms=0 max() берёт первый встреченный (stable)
        assert chosen == "first", f"все ms=0 → winner=items[0] ('first'), получили {chosen}"
        assert trace == []
        assert all(b["total_ms"] == pytest.approx(0.0) for b in branches)

    def test_fork_trace_preserves_existing_spans(self, trace_on) -> None:
        """fork_trace копирует все существующие спаны родителя."""
        spans = [_span(1.0), _span(2.0), _span(3.0)]
        parent = _make_item(spans=spans)
        result = frame_trace.fork_trace(parent)

        assert result["trace"] == spans, "все родительские спаны копируются"
        assert result["trace"] is not parent["trace"], "копия, не ссылка"

    def test_record_merge_with_zero_branches(self, trace_on) -> None:
        """record_merge с branches=0 не падает (деградированный случай)."""
        item: dict = {}
        frame_trace.record_merge(item, node="stitcher", branches=0, chosen="", ms=0)
        span = item["trace"][-1]
        assert span["branches"] == 0

    def test_merge_trace_flag_isolation(self) -> None:
        """Флаг _ENABLED не вытекает между тестами — проверка изоляции.

        Этот тест намеренно НЕ использует фикстуры trace_on/trace_off —
        он проверяет, что предыдущие тесты корректно восстановили флаг.
        """
        # Запоминаем текущее состояние флага
        current_state = frame_trace._ENABLED

        # Создаём item и делаем операцию — результат зависит от текущего флага
        parent = _make_item(spans=[_span(1.0)])
        result = frame_trace.fork_trace(parent)

        if current_state:
            assert "trace" in result
        else:
            assert result == {}

        # Флаг не должен быть изменён этим тестом
        assert frame_trace._ENABLED == current_state, "тест не должен менять _ENABLED"

    def test_full_fanin_workflow(self, trace_on) -> None:
        """Интеграционный тест: полный fan-out → mutate → fan-in → record_merge."""
        # Fan-out: три региона из одного родителя
        parent = _make_item(spans=[_span(2.0)], region_name="root")
        out_a = {**parent, "frame": "crop_a", "region_name": "region_a", **frame_trace.fork_trace(parent)}
        out_b = {**parent, "frame": "crop_b", "region_name": "region_b", **frame_trace.fork_trace(parent)}
        out_c = {**parent, "frame": "crop_c", "region_name": "region_c", **frame_trace.fork_trace(parent)}

        # Симулируем обработку ветвей (разное время)
        out_a["trace"].append(_span(3.0))  # total: 2+3=5
        out_b["trace"].append(_span(15.0))  # total: 2+15=17 ← победитель
        out_c["trace"].append(_span(7.0))  # total: 2+7=9

        # Fan-in: merge_trace
        trace, branches, chosen = frame_trace.merge_trace([out_a, out_b, out_c])
        merged: dict = {"frame": "canvas", "trace": trace, "trace_branches": branches}

        # record_merge дописывает merge-спан
        frame_trace.record_merge(merged, node="stitcher", branches=3, chosen=chosen, ms=0.5)

        # Проверки
        assert chosen == "region_b", f"region_b медленнее (ms=17), получили {chosen}"
        assert len(branches) == 3
        assert merged["trace"][-1]["kind"] == "merge"
        assert merged["trace"][-1]["chosen"] == "region_b"
        # Размер trace = len(winner.trace) + 1 merge-спан
        assert len(merged["trace"]) == len(out_b["trace"]) + 1
        # Независимость: out_a и out_c не пострадали
        assert len(out_a["trace"]) == 2
        assert len(out_c["trace"]) == 2
