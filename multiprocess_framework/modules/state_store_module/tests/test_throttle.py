"""test_throttle.py — Тесты для ThrottleMiddleware (Task 4b+.2).

Проверяет:
- Путь без правила → всегда пропускать
- Путь с interval=0 → всегда блокировать
- Первый вызов для нового пути → всегда пропускать
- Второй вызов слишком рано → блокировать, значение в _pending
- После ожидания interval → снова пропускать
- Промежуточные значения сохраняются в _pending (только последнее)
- flush() возвращает все pending значения
- flush() очищает _pending
- Glob-паттерн "**.state.actual_fps" матчит "cameras.0.state.actual_fps"
- Несколько правил: первое матчащее применяется
- context содержит rejection_reason при throttle
- before_merge троттлит поддерево per-leaf (PC 0.1, новый контракт)
- рантайм-мутаторы правил set_rules/update_rule/remove_rule (PC 0.1)
- MiddlewarePipeline.get / StateStoreManager.get_middleware (PC 0.1)
"""

from __future__ import annotations

from unittest.mock import patch


from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware


# ---------------------------------------------------------------------------
# Вспомогательные константы
# ---------------------------------------------------------------------------

SOURCE = "camera_process"


# ---------------------------------------------------------------------------
# Тест 1: путь без правила → всегда пропускать
# ---------------------------------------------------------------------------


class TestNoRule:
    def test_no_matching_rule_always_passes(self):
        """Путь, не покрытый ни одним правилом, пропускается всегда."""
        mw = ThrottleMiddleware({"**.state.fps": 1.0})
        context: dict = {}

        proceed, value = mw.before_set("cameras.0.config.resolution", 1080, SOURCE, context)

        assert proceed is True
        assert value == 1080
        assert "rejection_reason" not in context

    def test_no_rule_multiple_calls_always_pass(self):
        """Без правила каждый вызов проходит."""
        mw = ThrottleMiddleware({"**.state.fps": 1.0})

        for i in range(5):
            context: dict = {}
            proceed, _ = mw.before_set("some.other.path", i, SOURCE, context)
            assert proceed is True


# ---------------------------------------------------------------------------
# Тест 2: interval=0 → полная блокировка
# ---------------------------------------------------------------------------


class TestBlockedPath:
    def test_interval_zero_always_blocked(self):
        """interval=0 означает полную блокировку пути."""
        mw = ThrottleMiddleware({"**.state.last_frame_seq": 0})
        context: dict = {}

        proceed, value = mw.before_set("cameras.0.state.last_frame_seq", 42, SOURCE, context)

        assert proceed is False
        assert value == 42
        assert context.get("rejection_reason") == "throttled"

    def test_interval_zero_blocks_every_call(self):
        """interval=0 блокирует все последующие вызовы."""
        mw = ThrottleMiddleware({"**.state.last_frame_seq": 0})

        for i in range(10):
            context: dict = {}
            proceed, _ = mw.before_set("cameras.0.state.last_frame_seq", i, SOURCE, context)
            assert proceed is False


# ---------------------------------------------------------------------------
# Тест 3 и 4: первый вызов проходит, второй сразу — нет
# ---------------------------------------------------------------------------


class TestThrottleInterval:
    def test_first_call_passes(self):
        """Первый вызов для нового пути всегда проходит."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        context: dict = {}

        proceed, _ = mw.before_set("cameras.0.state.actual_fps", 25.0, SOURCE, context)

        assert proceed is True
        assert "rejection_reason" not in context

    def test_second_call_immediately_blocked(self):
        """Второй вызов подряд (без паузы) блокируется."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})

        with patch("time.monotonic", return_value=100.0):
            mw.before_set("cameras.0.state.actual_fps", 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.1):
            context: dict = {}
            proceed, _ = mw.before_set("cameras.0.state.actual_fps", 26.0, SOURCE, context)

        assert proceed is False
        assert context.get("rejection_reason") == "throttled"

    def test_passes_after_interval_elapsed(self):
        """После истечения interval вызов снова пропускается."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})

        with patch("time.monotonic", return_value=100.0):
            mw.before_set("cameras.0.state.actual_fps", 25.0, SOURCE, {})

        # Прошло ровно 1.0 сек — должно пропустить
        with patch("time.monotonic", return_value=101.0):
            context: dict = {}
            proceed, value = mw.before_set("cameras.0.state.actual_fps", 27.0, SOURCE, context)

        assert proceed is True
        assert value == 27.0
        assert "rejection_reason" not in context

    def test_blocked_just_before_interval(self):
        """Вызов непосредственно до истечения interval блокируется."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 2.0})

        with patch("time.monotonic", return_value=200.0):
            mw.before_set("cameras.0.state.actual_fps", 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=201.99):
            context: dict = {}
            proceed, _ = mw.before_set("cameras.0.state.actual_fps", 30.0, SOURCE, context)

        assert proceed is False


# ---------------------------------------------------------------------------
# Тест 5: промежуточные значения сохраняются в _pending (только последнее)
# ---------------------------------------------------------------------------


class TestPending:
    def test_blocked_value_saved_to_pending(self):
        """Заблокированное значение сохраняется в _pending."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        path = "cameras.0.state.actual_fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.3):
            mw.before_set(path, 26.0, SOURCE, {})

        assert path in mw._pending
        assert mw._pending[path] == (26.0, SOURCE)

    def test_only_last_pending_value_stored(self):
        """В _pending хранится только последнее заблокированное значение."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        path = "cameras.0.state.actual_fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.2):
            mw.before_set(path, 26.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.4):
            mw.before_set(path, 27.0, SOURCE, {})

        # Только последнее значение
        assert mw._pending[path][0] == 27.0

    def test_pending_cleared_after_pass(self):
        """После пропуска _pending для пути очищается."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        path = "cameras.0.state.actual_fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.3):
            mw.before_set(path, 26.0, SOURCE, {})

        # Убеждаемся, что pending есть
        assert path in mw._pending

        # Ждём interval
        with patch("time.monotonic", return_value=101.5):
            mw.before_set(path, 28.0, SOURCE, {})

        # После пропуска pending должен очиститься
        assert path not in mw._pending


# ---------------------------------------------------------------------------
# Тест 6 и 7: flush()
# ---------------------------------------------------------------------------


class TestFlush:
    def test_flush_returns_pending_values(self):
        """flush() возвращает все накопленные pending значения."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        path = "cameras.0.state.actual_fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.3):
            mw.before_set(path, 26.0, SOURCE, {})

        result = mw.flush()

        assert len(result) == 1
        assert result[0] == (path, 26.0, SOURCE)

    def test_flush_clears_pending(self):
        """После flush() _pending пуст."""
        mw = ThrottleMiddleware({"**.state.drops_count": 0.5})
        path = "cameras.1.state.drops_count"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 5, SOURCE, {})

        with patch("time.monotonic", return_value=100.1):
            mw.before_set(path, 6, SOURCE, {})

        mw.flush()

        assert mw._pending == {}

    def test_flush_empty_returns_empty_list(self):
        """flush() на пустом _pending возвращает []."""
        mw = ThrottleMiddleware({"**.state.fps": 1.0})
        result = mw.flush()
        assert result == []

    def test_flush_blocked_path_returns_value(self):
        """flush() возвращает значения даже для заблокированных (interval=0) путей."""
        mw = ThrottleMiddleware({"**.state.last_frame_seq": 0})
        path = "cameras.0.state.last_frame_seq"

        mw.before_set(path, 100, SOURCE, {})
        mw.before_set(path, 101, SOURCE, {})
        mw.before_set(path, 102, SOURCE, {})

        result = mw.flush()
        # Только последнее pending значение
        assert len(result) == 1
        assert result[0] == (path, 102, SOURCE)


# ---------------------------------------------------------------------------
# Тест 8: glob-паттерн "**.state.actual_fps" матчит длинные пути
# ---------------------------------------------------------------------------


class TestGlobMatching:
    def test_double_star_matches_deep_path(self):
        """Паттерн '**.state.actual_fps' матчит 'cameras.0.state.actual_fps'."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        context: dict = {}

        with patch("time.monotonic", return_value=100.0):
            proceed, _ = mw.before_set("cameras.0.state.actual_fps", 30.0, SOURCE, context)

        assert proceed is True

    def test_double_star_does_not_match_unrelated_path(self):
        """Паттерн не матчит путь с другим суффиксом."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        context: dict = {}

        proceed, _ = mw.before_set("cameras.0.state.drops_count", 5, SOURCE, context)

        assert proceed is True  # Нет правила → пропускаем


# ---------------------------------------------------------------------------
# Тест 9: несколько правил — применяется первое матчащее
# ---------------------------------------------------------------------------


class TestFirstMatchingRule:
    def test_first_rule_wins(self):
        """Первое матчащее правило имеет приоритет над остальными."""
        # Оба правила матчат путь, но первое имеет интервал 5.0
        mw = ThrottleMiddleware(
            {
                "cameras.0.state.actual_fps": 5.0,
                "**.state.actual_fps": 1.0,
            }
        )
        path = "cameras.0.state.actual_fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        # Прошло 2 сек — достаточно для правила 1.0, но мало для 5.0
        with patch("time.monotonic", return_value=102.0):
            context: dict = {}
            proceed, _ = mw.before_set(path, 26.0, SOURCE, context)

        assert proceed is False

    def test_blocked_rule_before_interval_rule(self):
        """Правило с interval=0 перед правилом с interval>0: блокирует."""
        mw = ThrottleMiddleware(
            {
                "cameras.**.state.actual_fps": 0,
                "**.state.actual_fps": 1.0,
            }
        )
        path = "cameras.0.state.actual_fps"
        context: dict = {}

        proceed, _ = mw.before_set(path, 25.0, SOURCE, context)

        assert proceed is False
        assert context.get("rejection_reason") == "throttled"


# ---------------------------------------------------------------------------
# Тест 10: context содержит rejection_reason при throttle
# ---------------------------------------------------------------------------


class TestRejectionContext:
    def test_rejection_reason_set_for_interval_throttle(self):
        """context['rejection_reason'] == 'throttled' при блокировке по интервалу."""
        mw = ThrottleMiddleware({"**.state.fps": 1.0})
        path = "cameras.0.state.fps"

        with patch("time.monotonic", return_value=100.0):
            mw.before_set(path, 25.0, SOURCE, {})

        with patch("time.monotonic", return_value=100.1):
            context: dict = {}
            proceed, _ = mw.before_set(path, 26.0, SOURCE, context)

        assert proceed is False
        assert context["rejection_reason"] == "throttled"

    def test_rejection_reason_set_for_zero_interval(self):
        """context['rejection_reason'] == 'throttled' при полной блокировке."""
        mw = ThrottleMiddleware({"**.state.seq": 0})
        context: dict = {}

        mw.before_set("cameras.0.state.seq", 1, SOURCE, context)

        assert context["rejection_reason"] == "throttled"

    def test_no_rejection_reason_when_passed(self):
        """context не содержит rejection_reason, если вызов прошёл."""
        mw = ThrottleMiddleware({"**.state.fps": 1.0})
        context: dict = {}

        with patch("time.monotonic", return_value=100.0):
            proceed, _ = mw.before_set("cameras.0.state.fps", 25.0, SOURCE, context)

        assert proceed is True
        assert "rejection_reason" not in context


# ---------------------------------------------------------------------------
# Тест 11: before_merge троттлит поддерево per-leaf (PC 0.1, новый контракт)
# ---------------------------------------------------------------------------


class TestBeforeMergeThrottle:
    """Новый контракт (PC 0.1): before_merge разворачивает поддерево в листовые
    полные пути и троттлит каждый лист той же логикой, что before_set."""

    def test_leaf_without_rule_passes_unchanged(self):
        """Лист без матчащего правила пропускается как есть (identity сохранён)."""
        mw = ThrottleMiddleware({"processes.**.state.fps": 1.0})
        context: dict = {}
        data = {"actual_fps": 25.0}  # ключ не матчит правило fps

        proceed, out = mw.before_merge("cameras.0.state", data, SOURCE, context)

        assert proceed is True
        assert out is data  # без копии, если ни один лист не покрыт правилом
        assert "rejection_reason" not in context

    def test_no_rules_at_all_passes_unchanged(self):
        """Пустой набор правил → merge проходит без изменений."""
        mw = ThrottleMiddleware({})
        data = {"state": {"fps": 25.0}}

        proceed, out = mw.before_merge("processes.cam", data, SOURCE, {})

        assert proceed is True
        assert out is data

    def test_leaf_interval_zero_pruned_and_rejected(self):
        """Единственный лист под правилом interval=0 → merge отклонён целиком."""
        mw = ThrottleMiddleware({"processes.**.state.fps": 0})
        context: dict = {}

        proceed, _ = mw.before_merge("processes.cam", {"state": {"fps": 25.0}}, SOURCE, context)

        assert proceed is False
        assert context.get("rejection_reason") == "throttled"
        # Значение придержано в _pending по ПОЛНОМУ пути листа
        assert mw._pending["processes.cam.state.fps"] == (25.0, SOURCE)

    def test_merge_leaf_throttled_by_interval(self):
        """2 быстрых merge по правилу interval>0: первый проходит, второй придержан."""
        mw = ThrottleMiddleware({"processes.**.state.fps": 1.0})
        full = "processes.cam.state.fps"

        with patch("time.monotonic", return_value=100.0):
            proceed1, out1 = mw.before_merge("processes.cam", {"state": {"fps": 25.0}}, SOURCE, {})

        with patch("time.monotonic", return_value=100.1):
            context: dict = {}
            proceed2, _ = mw.before_merge("processes.cam", {"state": {"fps": 26.0}}, SOURCE, context)

        # Первый прошёл целиком
        assert proceed1 is True
        assert out1 == {"state": {"fps": 25.0}}
        # Второй придержан (единственный листа под правилом) → отклонён, значение в _pending
        assert proceed2 is False
        assert context.get("rejection_reason") == "throttled"
        assert mw._pending[full] == (26.0, SOURCE)

    def test_merge_passes_after_interval_elapsed(self):
        """После истечения interval merge-лист снова проходит."""
        mw = ThrottleMiddleware({"processes.**.state.fps": 1.0})

        with patch("time.monotonic", return_value=100.0):
            mw.before_merge("processes.cam", {"state": {"fps": 25.0}}, SOURCE, {})

        with patch("time.monotonic", return_value=101.0):
            proceed, out = mw.before_merge("processes.cam", {"state": {"fps": 27.0}}, SOURCE, {})

        assert proceed is True
        assert out == {"state": {"fps": 27.0}}

    def test_partial_prune_keeps_leaf_without_rule(self):
        """Поддерево: троттлящийся лист (fps) вырезан, лист без правила (status) сохранён."""
        mw = ThrottleMiddleware({"processes.**.state.fps": 0})
        context: dict = {}
        data = {
            "state": {"fps": 25.0},
            "workers": {"loop": {"status": "running"}},  # без правила — проходит
        }

        proceed, out = mw.before_merge("processes.cam", data, SOURCE, context)

        assert proceed is True
        # fps вырезан, status сохранён
        assert out == {"workers": {"loop": {"status": "running"}}}
        assert "state" not in out
        assert "rejection_reason" not in context
        assert mw._pending["processes.cam.state.fps"] == (25.0, SOURCE)

    def test_partial_prune_keeps_passing_ruled_leaf(self):
        """Смешанное поддерево: fps (throttled, interval=0) вырезан, hz (interval>0, первый вызов) проходит."""
        mw = ThrottleMiddleware(
            {
                "processes.**.state.fps": 0,
                "processes.**.workers.*.effective_hz": 1.0,
            }
        )

        with patch("time.monotonic", return_value=100.0):
            proceed, out = mw.before_merge(
                "processes.cam",
                {
                    "state": {"fps": 25.0},
                    "workers": {"loop": {"effective_hz": 30.0}},
                },
                SOURCE,
                {},
            )

        assert proceed is True
        assert out == {"workers": {"loop": {"effective_hz": 30.0}}}

    def test_double_star_matches_full_leaf_path(self):
        """Правило processes.**.workers.*.effective_hz матчит полный путь листа merge."""
        mw = ThrottleMiddleware({"processes.**.workers.*.effective_hz": 0})
        context: dict = {}

        proceed, _ = mw.before_merge(
            "processes.cam",
            {"workers": {"loop": {"effective_hz": 30.0}}},
            SOURCE,
            context,
        )

        assert proceed is False
        assert mw._pending["processes.cam.workers.loop.effective_hz"] == (30.0, SOURCE)

    def test_before_set_unaffected_by_merge(self):
        """Регресс: before_set продолжает троттлить по своему пути независимо от merge."""
        mw = ThrottleMiddleware({"cameras.0.state.fps": 0})
        context: dict = {}

        proceed, _ = mw.before_set("cameras.0.state.fps", 25.0, SOURCE, context)

        assert proceed is False
        assert context.get("rejection_reason") == "throttled"


# ---------------------------------------------------------------------------
# Тест 12: рантайм-мутаторы правил (PC 0.1)
# ---------------------------------------------------------------------------


class TestRuntimeRuleMutation:
    def test_update_rule_adds_new_rule_live(self):
        """update_rule добавляет правило, которое сразу начинает троттлить."""
        mw = ThrottleMiddleware({})
        # Пока правила нет — set проходит.
        assert mw.before_set("processes.cam.state.fps", 1.0, SOURCE, {})[0] is True

        mw.update_rule("processes.**.state.fps", 0)  # полная блокировка

        proceed, _ = mw.before_set("processes.cam.state.fps", 2.0, SOURCE, {})
        assert proceed is False

    def test_update_rule_changes_interval_live(self):
        """update_rule меняет интервал живьём: было большим (держит) → стало 0.1 (пропускает)."""
        mw = ThrottleMiddleware({"**.state.fps": 100.0})
        path = "cameras.0.state.fps"

        with patch("time.monotonic", return_value=100.0):
            assert mw.before_set(path, 25.0, SOURCE, {})[0] is True  # первый проход

        # При интервале 100с второй вызов через 1с был бы придержан.
        with patch("time.monotonic", return_value=101.0):
            assert mw.before_set(path, 26.0, SOURCE, {})[0] is False

        # Живьём уменьшаем интервал → тот же тайминг теперь достаточен.
        mw.update_rule("**.state.fps", 0.1)
        with patch("time.monotonic", return_value=101.0):
            assert mw.before_set(path, 27.0, SOURCE, {})[0] is True

    def test_set_rules_replaces_whole_set(self):
        """set_rules заменяет весь набор правил."""
        mw = ThrottleMiddleware({"a.*": 0})
        # Старое правило блокирует.
        assert mw.before_set("a.x", 1, SOURCE, {})[0] is False

        mw.set_rules({"b.*": 0})
        # Старое правило исчезло → путь 'a.x' теперь свободен.
        assert mw.before_set("a.x", 1, SOURCE, {})[0] is True
        # Новое правило действует.
        assert mw.before_set("b.y", 1, SOURCE, {})[0] is False

    def test_remove_rule(self):
        """remove_rule снимает правило; повторное удаление → False."""
        mw = ThrottleMiddleware({"a.*": 0})

        assert mw.remove_rule("a.*") is True
        assert mw.before_set("a.x", 1, SOURCE, {})[0] is True  # правила больше нет
        assert mw.remove_rule("a.*") is False  # уже удалено

    def test_rules_property_returns_copy(self):
        """rules возвращает КОПИЮ — мутация наружу не влияет на middleware."""
        mw = ThrottleMiddleware({"a.*": 1.0})
        snapshot = mw.rules
        snapshot["a.*"] = 999.0
        assert mw.rules["a.*"] == 1.0

    def test_update_rule_affects_merge_path(self):
        """update_rule влияет и на merge-путь (единый набор правил)."""
        mw = ThrottleMiddleware({})
        # Без правила merge проходит.
        assert mw.before_merge("processes.cam", {"state": {"fps": 25.0}}, SOURCE, {})[0] is True

        mw.update_rule("processes.**.state.fps", 0)

        proceed, _ = mw.before_merge("processes.cam", {"state": {"fps": 26.0}}, SOURCE, {})
        assert proceed is False


# ---------------------------------------------------------------------------
# Тест 13: доступ к живому middleware по имени (PC 0.1)
# ---------------------------------------------------------------------------


class TestMiddlewareLookup:
    def test_pipeline_get_returns_same_instance(self):
        """MiddlewarePipeline.get(name) возвращает тот же зарегистрированный инстанс."""
        from multiprocess_framework.modules.state_store_module.middleware.base import (
            MiddlewarePipeline,
        )

        pipeline = MiddlewarePipeline()
        mw = ThrottleMiddleware({"a.*": 1.0})
        pipeline.use(mw)

        assert pipeline.get("throttle") is mw
        assert pipeline.get("nonexistent") is None

    def test_manager_get_middleware_returns_same_instance(self):
        """StateStoreManager.get_middleware('throttle') возвращает тот же инстанс."""
        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        manager = StateStoreManager(router=None, auto_register_ipc=False)
        mw = ThrottleMiddleware({"a.*": 1.0})
        manager.use(mw)

        assert manager.get_middleware("throttle") is mw
        assert manager.get_middleware("nonexistent") is None

    def test_get_middleware_enables_runtime_update(self):
        """Через get_middleware можно достать троттл и поменять правило живьём."""
        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        manager = StateStoreManager(router=None, auto_register_ipc=False)
        manager.use(ThrottleMiddleware({}))

        throttle = manager.get_middleware("throttle")
        assert throttle is not None
        throttle.update_rule("processes.**.state.fps", 0)

        assert throttle.rules["processes.**.state.fps"] == 0
