# -*- coding: utf-8 -*-
"""Ф2.2 — резолв правила по иерархическому имени: контракт самого дерева.

Здесь проверяется ЧИСТАЯ функция «таблица правил + имя → уровень/приёмники»,
без логгера, каналов и файлов. Интеграция (гейт, маршрут, плоскость ошибок,
конфиг) живёт в ``test_name_routing.py`` — разделение не косметическое: дефект
резолва и дефект проводки лечатся в разных местах, и тест, падающий на обоих
сразу, не говорит, где чинить.

Заявленные свойства (каждое ломается отдельно — см. слом-инъекции в плане):

  A. подъём по точкам до первого правила, задавшего ось;
  B. совпадение ТОЛЬКО по границе точки (``vision.captureX`` — не ``vision.capture``);
  C. две оси (уровень / приёмники) резолвятся независимо;
  D. молчание (``None``) отличается от объявленной пустоты (``[]``);
  E. кэш отвечает то же, что прямой резолв, и стареет по команде;
  F. правило, вернувшее приёмники, отдаёт их неизменяемыми.
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerRuleSchema
from multiprocess_framework.modules.logger_module.core.name_hierarchy import (
    ROOT_NAME,
    NameHierarchy,
)


def _rule(level: Optional[str] = None, channels: Optional[List[str]] = None) -> LoggerRuleSchema:
    return LoggerRuleSchema(level=level, channels=channels)


class TestLongestPrefixWalk:
    """A — подъём по точкам. Тест на КАЖДЫЙ уровень, как требует acceptance."""

    @pytest.fixture()
    def tree(self) -> NameHierarchy:
        return NameHierarchy(
            {
                ROOT_NAME: _rule(level="WARNING"),
                "vision": _rule(level="INFO"),
                "vision.capture": _rule(level="DEBUG"),
                "vision.capture.hikvision": _rule(level="CRITICAL"),
            }
        )

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("vision.capture.hikvision", "CRITICAL"),  # точное совпадение листа
            ("vision.capture.hikvision.sdk", "CRITICAL"),  # потомок листа
            ("vision.capture", "DEBUG"),
            ("vision.capture.basler", "DEBUG"),  # брат листа → правило родителя
            ("vision", "INFO"),
            ("vision.detect", "INFO"),
            ("Plugins.roi", "WARNING"),  # чужая ветка → корень
            (ROOT_NAME, "WARNING"),
        ],
    )
    def test_each_level_of_the_tree_answers(self, tree: NameHierarchy, name: str, expected: str) -> None:
        assert tree.level(name) == expected

    def test_without_root_rule_unmatched_name_is_silence_not_a_default(self) -> None:
        """Нет правила — ``None``, а НЕ «самый низкий уровень».

        Разница принципиальная: ``None`` означает «решает скоуп, как до Ф2.2»,
        а любой подставленный уровень означал бы, что таблица правил молча
        перехватила решение у скоупа на ВСЕХ источниках сразу.
        """
        tree = NameHierarchy({"vision": _rule(level="DEBUG")})
        assert tree.level("Plugins.roi") is None
        assert tree.level(ROOT_NAME) is None

    def test_empty_table_is_falsy(self) -> None:
        """Пустая таблица должна быть отличима ОДНИМ дешёвым вопросом.

        На этом стоит гарантия «без правил поведение бит-в-бит прежнее»:
        вызывающий не заходит в ветку резолва вовсе.
        """
        assert not NameHierarchy()
        assert not NameHierarchy({})
        assert NameHierarchy({ROOT_NAME: _rule(level="INFO")})


class TestDotBoundary:
    """B — совпадение только по границе точки."""

    @pytest.fixture()
    def tree(self) -> NameHierarchy:
        return NameHierarchy({"vision.capture": _rule(level="DEBUG")})

    @pytest.mark.parametrize("name", ["vision.captureX", "vision.capture_extra", "vision.capturehik"])
    def test_prefix_by_characters_does_not_match(self, tree: NameHierarchy, name: str) -> None:
        """``startswith`` подхватил бы эти имена — и отдал бы им чужой уровень.

        Ошибка была бы молчаливой: источник получает не свой порог и никто не
        видит, почему. Поэтому проверка отдельным свойством, а не «заодно».
        """
        assert tree.level(name) is None

    def test_the_boundary_case_that_must_match_still_matches(self, tree: NameHierarchy) -> None:
        """Парный: сузить правило до бесполезности так же плохо, как расширить."""
        assert tree.level("vision.capture") == "DEBUG"
        assert tree.level("vision.capture.hikvision") == "DEBUG"


class TestAxesAreIndependent:
    """C — уровень и приёмники резолвятся ПО ОТДЕЛЬНОСТИ."""

    def test_leaf_sets_level_channels_come_from_the_ancestor(self) -> None:
        """Объявление ``{level: DEBUG}`` у листа не имеет права обнулить раскладку.

        Иначе настройка одной ручки ломала бы соседнюю: «сделал этот файл
        болтливым — и он перестал попадать в свой лог-файл».
        """
        tree = NameHierarchy(
            {
                "vision": _rule(channels=["vision_file"]),
                "vision.capture": _rule(level="DEBUG"),
            }
        )
        assert tree.level("vision.capture.hikvision") == "DEBUG"
        assert tree.channels("vision.capture.hikvision") == ("vision_file",)

    def test_ancestor_sets_level_channels_come_from_the_leaf(self) -> None:
        """Симметричный случай — иначе «независимость» проверена в одну сторону."""
        tree = NameHierarchy(
            {
                "vision": _rule(level="DEBUG"),
                "vision.capture": _rule(channels=["capture_file"]),
            }
        )
        assert tree.level("vision.capture.hikvision") == "DEBUG"
        assert tree.channels("vision.capture.hikvision") == ("capture_file",)


class TestSilenceIsNotEmptiness:
    """D — ``None`` («наследую») ≠ ``[]`` («приёмников нет, объявлено»)."""

    def test_declared_empty_stops_the_walk(self) -> None:
        tree = NameHierarchy(
            {
                "vision": _rule(channels=["vision_file"]),
                "vision.capture": _rule(channels=[]),
            }
        )
        assert tree.channels("vision.capture.hikvision") == ()

    def test_silence_continues_the_walk(self) -> None:
        tree = NameHierarchy(
            {
                "vision": _rule(channels=["vision_file"]),
                "vision.capture": _rule(level="DEBUG"),  # про приёмники молчит
            }
        )
        assert tree.channels("vision.capture.hikvision") == ("vision_file",)

    def test_the_two_answers_are_distinguishable_at_the_top(self) -> None:
        """Пара к обоим: пустой кортеж и ``None`` не должны сливаться у вызывающего."""
        declared = NameHierarchy({"vision": _rule(channels=[])})
        silent = NameHierarchy({"vision": _rule(level="INFO")})
        assert declared.channels("vision") == ()
        assert silent.channels("vision") is None
        assert declared.channels("vision") != silent.channels("vision")


class TestCache:
    """E/F — кэш отвечает то же, что резолв, стареет по команде и не течёт наружу."""

    def test_cached_answer_equals_the_first_one(self) -> None:
        tree = NameHierarchy({"vision": _rule(level="DEBUG", channels=["a"])})
        first_level, first_channels = tree.level("vision.capture"), tree.channels("vision.capture")
        assert (tree.level("vision.capture"), tree.channels("vision.capture")) == (first_level, first_channels)

    def test_silence_is_cached_too(self) -> None:
        """Молчание — самый частый ответ, и кэшироваться обязано именно оно.

        ``dict.get(name)`` не отличил бы закэшированный ``None`` от промаха, и
        молчащие имена пересчитывались бы на каждой записи — то есть кэш не
        работал бы ровно там, где он нужен. Свойство проверяется по внутренней
        карте, потому что снаружи промах и попадание неразличимы по значению.
        """
        tree = NameHierarchy({"vision": _rule(level="DEBUG")})
        assert tree.level("Plugins.roi") is None
        assert "Plugins.roi" in tree._level_cache  # noqa: SLF001 — предмет проверки
        assert tree._level_cache["Plugins.roi"] is None  # noqa: SLF001

    def test_clear_cache_forgets_both_maps(self) -> None:
        tree = NameHierarchy({"vision": _rule(level="DEBUG", channels=["a"])})
        tree.level("vision.capture")
        tree.channels("vision.capture")
        tree.clear_cache()
        assert not tree._level_cache  # noqa: SLF001
        assert not tree._channels_cache  # noqa: SLF001

    def test_returned_channels_cannot_be_mutated_by_the_caller(self) -> None:
        """F — маршрут уходит наружу и в кэш; изменяемый список испортил бы обоим."""
        tree = NameHierarchy({"vision": _rule(channels=["a", "b"])})
        got = tree.channels("vision")
        assert isinstance(got, tuple)
        with pytest.raises((AttributeError, TypeError)):
            got.append("c")  # type: ignore[attr-defined]

    def test_table_is_copied_not_referenced(self) -> None:
        """Правка исходного словаря после сборки дерева не должна менять ответы.

        Иначе «пересобрали конфиг» и «поправили словарь на месте» дали бы разные
        состояния кэша при одинаковом виде — класс дефекта, который на тестах не
        виден, а live проявляется устаревшим ответом.
        """
        source = {"vision": _rule(level="DEBUG")}
        tree = NameHierarchy(source)
        source["vision.capture"] = _rule(level="CRITICAL")
        assert tree.level("vision.capture") == "DEBUG"


class TestLevelNormalisation:
    """Канон уровня — на границе конфига, а не на горячем пути."""

    def test_lowercase_level_is_normalised_by_the_schema(self) -> None:
        assert LoggerRuleSchema(level="debug").level == "DEBUG"

    def test_none_stays_none(self) -> None:
        """``None`` — не строка и не имеет права стать ею: это «молчу»."""
        assert LoggerRuleSchema().level is None
        assert LoggerRuleSchema().channels is None


class TestResolveCachesAreBounded:
    """Ф2.х (Н5): кэши резолва не растут без предела по оси имён.

    Ключ кэша — имя источника с call-site, то есть потенциально динамическая
    строка (проба ревью Ф2: 3000 имён → 3000 записей, потолка не было).
    На переполнении карта чистится: резолв — чистая функция от таблицы, сброс
    мемо не меняет ни одного ответа — и это вторая половина пары.
    """

    def test_each_cache_holds_at_most_the_ceiling(self) -> None:
        from multiprocess_framework.modules.logger_module.core.name_hierarchy import (
            _RESOLVE_CACHE_CEILING,
        )

        tree = NameHierarchy({ROOT_NAME: LoggerRuleSchema(level="INFO", channels=["общий"], channels_extra=["хвост"])})
        for i in range(_RESOLVE_CACHE_CEILING + 50):
            имя = f"динамика.{i}"
            tree.level(имя)
            tree.channels(имя)
            tree.channels_extra(имя)

        assert len(tree._level_cache) <= _RESOLVE_CACHE_CEILING
        assert len(tree._channels_cache) <= _RESOLVE_CACHE_CEILING
        assert len(tree._extra_cache) <= _RESOLVE_CACHE_CEILING

    def test_the_answer_survives_the_overflow(self) -> None:
        """Пара: после сброса тот же вопрос получает тот же ответ."""
        from multiprocess_framework.modules.logger_module.core.name_hierarchy import (
            _RESOLVE_CACHE_CEILING,
        )

        tree = NameHierarchy({"пакет": LoggerRuleSchema(level="ERROR")})
        до = tree.level("пакет.якорь")
        for i in range(_RESOLVE_CACHE_CEILING + 1):
            tree.level(f"динамика.{i}")

        assert tree.level("пакет.якорь") == до == "ERROR"
