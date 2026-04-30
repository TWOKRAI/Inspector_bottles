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
- before_merge не затрагивается (базовый класс пропускает)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_prototype.state_store.middleware.throttle import ThrottleMiddleware


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

        proceed, value = mw.before_set(
            "cameras.0.state.last_frame_seq", 42, SOURCE, context
        )

        assert proceed is False
        assert value == 42
        assert context.get("rejection_reason") == "throttled"

    def test_interval_zero_blocks_every_call(self):
        """interval=0 блокирует все последующие вызовы."""
        mw = ThrottleMiddleware({"**.state.last_frame_seq": 0})

        for i in range(10):
            context: dict = {}
            proceed, _ = mw.before_set(
                "cameras.0.state.last_frame_seq", i, SOURCE, context
            )
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
            proceed, _ = mw.before_set(
                "cameras.0.state.actual_fps", 26.0, SOURCE, context
            )

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
            proceed, value = mw.before_set(
                "cameras.0.state.actual_fps", 27.0, SOURCE, context
            )

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
            proceed, _ = mw.before_set(
                "cameras.0.state.actual_fps", 30.0, SOURCE, context
            )

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
            proceed, _ = mw.before_set(
                "cameras.0.state.actual_fps", 30.0, SOURCE, context
            )

        assert proceed is True

    def test_double_star_does_not_match_unrelated_path(self):
        """Паттерн не матчит путь с другим суффиксом."""
        mw = ThrottleMiddleware({"**.state.actual_fps": 1.0})
        context: dict = {}

        proceed, _ = mw.before_set(
            "cameras.0.state.drops_count", 5, SOURCE, context
        )

        assert proceed is True  # Нет правила → пропускаем


# ---------------------------------------------------------------------------
# Тест 9: несколько правил — применяется первое матчащее
# ---------------------------------------------------------------------------


class TestFirstMatchingRule:
    def test_first_rule_wins(self):
        """Первое матчащее правило имеет приоритет над остальными."""
        # Оба правила матчат путь, но первое имеет интервал 5.0
        mw = ThrottleMiddleware({
            "cameras.0.state.actual_fps": 5.0,
            "**.state.actual_fps": 1.0,
        })
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
        mw = ThrottleMiddleware({
            "cameras.**.state.actual_fps": 0,
            "**.state.actual_fps": 1.0,
        })
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
# Тест 11: before_merge не затрагивается (базовый класс пропускает)
# ---------------------------------------------------------------------------


class TestBeforeMergeNotAffected:
    def test_before_merge_always_passes(self):
        """ThrottleMiddleware не переопределяет before_merge — всегда пропускает."""
        mw = ThrottleMiddleware({
            "cameras.0.state.actual_fps": 0,  # полная блокировка для set
        })
        context: dict = {}

        proceed, data = mw.before_merge(
            "cameras.0.state", {"actual_fps": 25.0}, SOURCE, context
        )

        assert proceed is True
        assert data == {"actual_fps": 25.0}
        assert "rejection_reason" not in context
