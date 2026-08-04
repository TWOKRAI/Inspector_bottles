# -*- coding: utf-8 -*-
"""Ф2.6 — разбор имени для пульта: что действует и какое правило победило.

План: plans/observability-unified-routing.md, задача 2.6, шаг 6 (резидуал 2.2 №4).

Зачем. ``effective_level``/``effective_channels`` существовали в коде с 2.2, а ручки
посмотреть на них не было: живой прогон проверялся размерами файлов на глаз — тем же
способом, которым 288 нулевых файлов не замечали три месяца. Образец ответа —
``GET /actuator/loggers/{name}`` в Spring Boot: он отвечает на ЛЮБОЕ введённое имя,
в том числе на то, под которым ещё никто не писал, и потому отвечает на вопрос-гипотезу
(«если я напишу правило так — что получится?»), а не только на разбор случившегося.

**Главная опасность этого файла — не то, что readback врёт, а то, что он разошёлся с
гейтом.** ``resolve`` идёт своим проходом (диагностический путь, без кэша), и его
согласие с горячими ``level``/``channels``/``channels_extra`` — не «на всякий случай»,
а несущее свойство: по readback принимают решения, и расходящийся readback хуже
отсутствующего. Согласие проверяется на таблице случаев, а не на одном.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.logger_module.core.name_hierarchy import NameHierarchy


class _Rule:
    def __init__(self, level=None, channels=None, channels_extra=None) -> None:
        self.level = level
        self.channels = channels
        self.channels_extra = channels_extra


_TABLE = {
    "": _Rule(level="WARNING", channels=["system_file"], channels_extra=["audit"]),
    "a": _Rule(channels=["a_file"]),
    "a.b": _Rule(level="DEBUG", channels_extra=["b_file"]),
    "a.b.c": _Rule(channels=[]),
    "solo": _Rule(),
}


@pytest.fixture()
def tree() -> NameHierarchy:
    return NameHierarchy(_TABLE)


class TestWhichRuleWon:
    def test_axes_can_win_from_different_keys(self, tree: NameHierarchy) -> None:
        """Уровень и приёмники резолвятся независимо — значит и происхождение разное."""
        got = tree.resolve("a.b.z")

        assert got["level"] == "DEBUG"
        assert got["level_from"] == "a.b"
        assert got["channels"] == ["a_file"]
        assert got["channels_from"] == "a"

    def test_root_origin_is_the_empty_string_not_none(self, tree: NameHierarchy) -> None:
        """Три разных «ничего» не смешиваются.

        ``None`` — «никто не настраивал», ``""`` — «настроено глобально, правилом
        корня». Значение одно и то же, а чинятся они по-разному, и readback обязан
        их различать.
        """
        got = tree.resolve("нет.такого.имени")

        assert got["level"] == "WARNING"
        assert got["level_from"] == ""
        assert got["channels_from"] == ""

    def test_absent_axis_reports_none_origin(self) -> None:
        got = NameHierarchy({"a": _Rule(channels=["x"])}).resolve("a.b")

        assert got["level"] is None
        assert got["level_from"] is None

    def test_declared_emptiness_is_a_win_not_a_silence(self, tree: NameHierarchy) -> None:
        """``channels: []`` — «приёмников нет, это решение», и оно ПОБЕДИЛО.

        Без этой пары пустой список в readback читался бы как «никто не сказал», и
        оператор искал бы отсутствующее правило вместо того, чтобы найти своё.
        """
        got = tree.resolve("a.b.c")

        assert got["channels"] == []
        assert got["channels_from"] == "a.b.c"

    def test_extra_origins_are_listed_root_to_leaf(self, tree: NameHierarchy) -> None:
        """Добавки копятся, значит вкладчиков может быть несколько — перечисляются все."""
        got = tree.resolve("a.b.z")

        assert got["extra_from"] == ["", "a.b"]
        assert got["channels_extra"] == ["audit", "b_file"]

    def test_chain_lists_every_rule_considered(self, tree: NameHierarchy) -> None:
        """Вся рассмотренная ветка, лист→корень — видно, что вообще участвовало."""
        assert tree.resolve("a.b.c.d")["matched_rules"] == ["a.b.c", "a.b", "a", ""]

    def test_answers_for_a_name_nobody_wrote_under(self, tree: NameHierarchy) -> None:
        """Вопрос-гипотеза: имя ещё не существует, ответ всё равно есть."""
        got = tree.resolve("Plugins.будущий.плагин")

        assert got["name"] == "Plugins.будущий.плагин"
        assert got["level"] == "WARNING"


class TestReadbackAgreesWithTheGate:
    """Несущее свойство: разбор не расходится с тем, что действует на записи."""

    @pytest.mark.parametrize(
        "name",
        ["a.b.z", "a.b.c", "a.b.c.d", "a", "a.zzz", "solo", "нет.такого.имени", "", "aX", "a.bX"],
    )
    def test_resolve_agrees_with_hot_path(self, tree: NameHierarchy, name: str) -> None:
        got = tree.resolve(name)
        hot_channels = tree.channels(name)

        assert got["level"] == tree.level(name)
        assert got["channels"] == (list(hot_channels) if hot_channels is not None else None)
        assert got["channels_extra"] == list(tree.channels_extra(name))

    def test_boundary_is_the_dot_here_too(self, tree: NameHierarchy) -> None:
        """``aX`` не подхватывает правило ``a`` — в разборе так же, как в гейте.

        Отдельно от таблицы согласия: там сравниваются два наших же ответа, и оба
        могли бы ошибаться одинаково. Здесь ожидание записано литералом.
        """
        assert tree.resolve("aX")["channels"] == ["system_file"]
        assert tree.resolve("aX")["channels_from"] == ""


class TestOutputCrossesTheProcessBoundary:
    def test_result_is_plain_dict_of_plain_types(self, tree: NameHierarchy) -> None:
        """Ответ уходит на пульт через IPC — только dict/list/str/None (Dict at Boundary)."""
        got = tree.resolve("a.b.z")

        assert isinstance(got, dict)
        for key, value in got.items():
            assert isinstance(key, str)
            assert value is None or isinstance(value, (str, list)), f"{key}={value!r}"
            if isinstance(value, list):
                assert all(isinstance(item, str) for item in value), key
