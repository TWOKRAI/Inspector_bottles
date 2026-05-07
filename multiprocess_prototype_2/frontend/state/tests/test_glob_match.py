"""Тесты для frontend/state/glob_match.py.

Проверяют все ветви алгоритма: точное совпадение, одиночный '*',
двойной '**', несовпадение, нормализацию точек.
"""
import pytest

from multiprocess_prototype_2.frontend.state.glob_match import match_glob


class TestExactMatch:
    """Точное совпадение паттерна и пути."""

    def test_exact_match(self):
        """Идентичные паттерн и путь должны совпадать."""
        assert match_glob(
            "processes.cam.state.fps",
            "processes.cam.state.fps",
        ) is True

    def test_exact_no_match_last_segment(self):
        """Отличие в последнем сегменте — нет совпадения."""
        assert match_glob(
            "processes.cam.state.fps",
            "processes.cam.state.latency",
        ) is False


class TestSingleStar:
    """Одиночная '*' совпадает ровно с одним сегментом."""

    def test_single_star_matches_one_segment(self):
        """'*' в середине паттерна заменяет любой один сегмент."""
        assert match_glob(
            "processes.*.state.fps",
            "processes.cam.state.fps",
        ) is True

    def test_single_star_does_not_match_multiple_segments(self):
        """'*' не должна совпасть с двумя сегментами сразу."""
        assert match_glob(
            "processes.*.fps",
            "processes.cam.state.fps",
        ) is False

    def test_single_star_at_end_matches_any_leaf(self):
        """'*' в конце паттерна совпадает с любым листовым сегментом."""
        assert match_glob(
            "processes.cam.state.*",
            "processes.cam.state.fps",
        ) is True


class TestDoubleStar:
    """Двойная '**' совпадает с 0 или более сегментами."""

    def test_double_star_matches_any_depth(self):
        """'**' в конце покрывает любое число сегментов."""
        assert match_glob("processes.**", "processes.x.y.z") is True

    def test_double_star_at_start(self):
        """'**' в начале охватывает любой префикс."""
        assert match_glob("**.fps", "processes.cam.state.fps") is True

    def test_double_star_in_middle(self):
        """'**' в середине покрывает произвольное число сегментов."""
        assert match_glob(
            "processes.**.fps",
            "processes.cam.state.fps",
        ) is True

    def test_double_star_matches_zero_segments(self):
        """'**' может совпасть с 0 сегментами (между двумя конкретными)."""
        assert match_glob("processes.**.cam", "processes.cam") is True


class TestNoMatch:
    """Паттерн явно не совпадает с путём."""

    def test_no_match_when_segment_differs(self):
        """Отличие сегмента между паттерном и путём — нет совпадения."""
        assert match_glob(
            "processes.cam.config.fps",
            "processes.cam.state.fps",
        ) is False

    def test_no_match_extra_segment_in_path(self):
        """В пути больше сегментов, чем охватывает паттерн без '**'."""
        assert match_glob(
            "processes.cam",
            "processes.cam.state.fps",
        ) is False


class TestNormalization:
    """Нормализация ведущих и завершающих точек."""

    def test_pattern_with_leading_trailing_dots_normalized(self):
        """Ведущие/завершающие точки обрезаются перед матчингом."""
        assert match_glob(
            ".processes.cam.state.fps.",
            ".processes.cam.state.fps.",
        ) is True

    def test_mixed_dots_normalized(self):
        """Точки только у паттерна — нормализация обоих."""
        assert match_glob(
            ".processes.*.state.fps.",
            "processes.cam.state.fps",
        ) is True
