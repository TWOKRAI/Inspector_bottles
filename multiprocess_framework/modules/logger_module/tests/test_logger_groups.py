# -*- coding: utf-8 -*-
"""Ф2.5 — ярлык набора источников: «этим трём тише» одной правкой.

План: plans/observability-unified-routing.md, задача 2.5.

Живой повод не выдуман: в `system.yaml` прототипа после 2.6 стояли ДВЕ правки с
одинаковым телом (`command_module` и `dispatch_module` → `busy_file`), потому что
набор «служебная болтовня» существовал в голове оператора, а в конфиге его не было.

Модель — `logging.group.*` Spring Boot: ярлык это алиас набора префиксов, а не новый
уровень дерева. Раскрытие происходит ОДИН раз, при сборке дерева, поэтому резолв о
группах не знает и на горячем пути они не стоят ничего.

Независимый `tester` не вызывался — инструментальный запрет на субагентов в сессии
(долг общий с 2.2, 2.4 и 2.6); названо вслух, потому что контракт наблюдаем снаружи.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerRuleSchema,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.name_hierarchy import NameHierarchy


class _Rule:
    """Правило без Pydantic — резолв на схему не завязан (как в тестах 2.2)."""

    def __init__(self, level: Optional[str] = None, channels: Optional[list] = None) -> None:
        self.level = level
        self.channels = channels
        self.channels_extra = None


ЧЛЕНЫ = ("пакет.один", "пакет.два", "совсем.другой")


class TestOneEditThreeChanges:
    """Главное свойство: правка на ярлык меняет всех членов сразу."""

    def test_rule_on_a_label_reaches_every_member(self) -> None:
        tree = NameHierarchy({"шумные": _Rule(level="ERROR")}, {"шумные": ЧЛЕНЫ})

        assert [tree.level(name) for name in ЧЛЕНЫ] == ["ERROR", "ERROR", "ERROR"]

    def test_without_the_label_the_same_edit_reaches_one(self) -> None:
        """Вторая половина пары: без группы та же правка — про один источник.

        Без неё «три ERROR» согласовалось бы и с реализацией, где ERROR приезжает
        откуда-то ещё (например, с корневого правила).
        """
        tree = NameHierarchy({"пакет.один": _Rule(level="ERROR")})

        assert [tree.level(name) for name in ЧЛЕНЫ] == ["ERROR", None, None]

    def test_the_label_itself_is_not_a_prefix(self) -> None:
        """Ярлык не становится узлом дерева — иначе он ловил бы одноимённый источник.

        Ровно эта коллизия уже стреляла в 2.6: ключ `gui` ловил записи, помеченные
        `gui`, из любого источника. Ярлык, оставленный в таблице, воспроизвёл бы её.
        """
        tree = NameHierarchy({"шумные": _Rule(level="ERROR")}, {"шумные": ЧЛЕНЫ})

        assert tree.level("шумные") is None
        assert tree.level("шумные.подпакет") is None

    def test_members_subtree_inherits_like_any_prefix(self) -> None:
        """Член группы остаётся обычным префиксом: поддерево наследует без правок конфига."""
        tree = NameHierarchy({"шумные": _Rule(level="ERROR")}, {"шумные": ЧЛЕНЫ})

        assert tree.level("пакет.один.глубже.ещё") == "ERROR"


class TestAddressedBeatsWholesale:
    """Р-2.5-Б: собственное правило члена сильнее ярлыка."""

    def test_own_rule_wins(self) -> None:
        tree = NameHierarchy(
            {"шумные": _Rule(level="ERROR"), "пакет.один": _Rule(level="DEBUG")},
            {"шумные": ЧЛЕНЫ},
        )

        assert tree.level("пакет.один") == "DEBUG"
        assert tree.level("пакет.два") == "ERROR", "сосед по группе обязан остаться под ярлыком"

    def test_readback_shows_the_member_is_not_covered(self) -> None:
        """Пара к приоритету: «ярлык написан, а на этом члене не действует» — видно.

        Объявление отдаёт `groups`, действующее — `rules`; расхождение между ними
        и есть ответ. Без него оператор видел бы имя в группе и считал, что правило
        группы на нём работает.
        """
        tree = NameHierarchy(
            {"шумные": _Rule(level="ERROR"), "пакет.один": _Rule(level="DEBUG")},
            {"шумные": ЧЛЕНЫ},
        )

        assert tree.groups["шумные"] == ЧЛЕНЫ
        assert tree.group_of("пакет.один") is None, "член со своим правилом не помечен ярлыком"
        assert tree.group_of("пакет.два") == "шумные"


class TestConflictIsLoudAndDeterministic:
    """Р-2.5-В: два ярлыка на один префикс."""

    def test_both_labels_are_named_and_the_winner_is_sorted_first(self) -> None:
        heard: list = []
        tree = NameHierarchy(
            {"альфа": _Rule(level="DEBUG"), "бета": _Rule(level="ERROR")},
            {"альфа": ("общий",), "бета": ("общий",)},
            complain=heard.append,
        )

        assert len(heard) == 1, heard
        assert "альфа" in heard[0] and "бета" in heard[0], "жалоба обязана назвать ОБЕ группы"
        assert tree.level("общий") == "DEBUG", "побеждает первая по сортировке, не по порядку в словаре"

    def test_the_winner_does_not_depend_on_insertion_order(self) -> None:
        """Детерминизм — суть решения: иначе смысл конфига зависит от порядка строк YAML.

        Проверяется ЗАПУСКОМ на обоих порядках вставки, а не чтением кода: словарь
        сохраняет порядок вставки, и реализация «первый попавшийся» прошла бы
        одиночную проверку.
        """
        rules = {"альфа": _Rule(level="DEBUG"), "бета": _Rule(level="ERROR")}
        прямой = NameHierarchy(rules, {"альфа": ("общий",), "бета": ("общий",)}, complain=lambda _m: None)
        обратный = NameHierarchy(rules, {"бета": ("общий",), "альфа": ("общий",)}, complain=lambda _m: None)

        assert прямой.level("общий") == обратный.level("общий") == "DEBUG"

    def test_disjoint_labels_stay_silent(self) -> None:
        """Пара: молчащий детектор, не показанный красным, ничего не доказывает."""
        heard: list = []
        NameHierarchy(
            {"альфа": _Rule(level="DEBUG"), "бета": _Rule(level="ERROR")},
            {"альфа": ("один",), "бета": ("два",)},
            complain=heard.append,
        )

        assert heard == []


class TestLabelShadowingASubtreeIsAudible:
    """Ф2.х (Н4): ярлык, совпавший с началом другого правила, — громко.

    Находка ревью Ф2: `rules={"camera": …}` + `groups={"camera": [...]}` молча
    превращали правило поддерева в правило группы — `camera.driver` переставал
    наследовать, жалоб ноль. Р-2.5-Г запретил точку В ярлыке; одно-сегментная
    коллизия статически не запрещаема (ярлык и префикс живут в разных секциях),
    поэтому она хотя бы слышна. Поведение прежнее: побеждает трактовка «ярлык».
    """

    def test_the_shadow_is_named_with_the_shadowed_rules(self) -> None:
        heard: list = []
        tree = NameHierarchy(
            {"камера": _Rule(level="DEBUG"), "камера.драйвер": _Rule(level="INFO")},
            {"камера": ("другой.модуль",)},
            complain=heard.append,
        )

        assert len(heard) == 1, heard
        assert "камера.драйвер" in heard[0], "жалоба обязана назвать затенённое правило"
        assert tree.level("камера.прочее") is None, "поведение не меняется: ярлык не префикс"
        assert tree.level("другой.модуль") == "DEBUG", "раскрытие группы живо"

    def test_a_label_without_a_subtree_stays_silent(self) -> None:
        """Пара: обычное употребление ярлыка (правило на ярлык) не шумит."""
        heard: list = []
        NameHierarchy(
            {"камера": _Rule(level="DEBUG")},
            {"камера": ("другой.модуль",)},
            complain=heard.append,
        )

        assert heard == []


class TestDottedLabelIsRefused:
    """Р-2.5-Г: отказ на границе конфига, а не предупреждение."""

    def test_a_dotted_label_does_not_pass_validation(self) -> None:
        with pytest.raises(ValidationError, match="точку"):
            LoggerManagerConfig(logger_groups={"мой.ярлык": ["a"]})

    def test_a_plain_label_passes(self) -> None:
        cfg = LoggerManagerConfig(logger_groups={"мой_ярлык": ["a"]})

        assert cfg.logger_groups == {"мой_ярлык": ["a"]}


class TestProvenanceNamesTheLabel:
    """Шаг 4: readback обязан назвать ярлык, а не только члена."""

    def test_resolve_reports_the_label_the_rule_came_through(self) -> None:
        tree = NameHierarchy(
            {"шумные": _Rule(level="ERROR", channels=["цех"])},
            {"шумные": ЧЛЕНЫ},
        )

        got = tree.resolve("пакет.один.глубже")

        assert got["level"] == "ERROR"
        assert got["level_from"] == "пакет.один"
        assert got["level_via_group"] == "шумные", "иначе оператор ищет в конфиге строку, которой нет"
        assert got["channels_via_group"] == "шумные"

    def test_a_rule_written_directly_has_no_label(self) -> None:
        """Пара: не всякое правило приезжает через ярлык, и врать об этом нельзя."""
        tree = NameHierarchy({"пакет.один": _Rule(level="ERROR")}, {"шумные": ЧЛЕНЫ})

        got = tree.resolve("пакет.один")

        assert got["level_from"] == "пакет.один"
        assert got["level_via_group"] is None


class TestGroupsWorkThroughTheRealManager:
    """Фейковая обвязка доказала бы обвязку — здесь настоящий менеджер и диск."""

    @pytest.fixture()
    def logger(self, tmp_path) -> Any:
        manager = LoggerManager(
            config=LoggerManagerConfig(
                app_name="groups25",
                log_directory=str(tmp_path),
                enable_batching=False,
                channels={
                    "общий": LoggerChannelSchema(type="file", enabled=True, file_path="общий.log", rotate=False),
                    "цех": LoggerChannelSchema(type="file", enabled=True, file_path="цех.log", rotate=False),
                },
                default_level="DEBUG",
                scopes={"SYSTEM": LoggerScopeSchema(channels=["общий"])},
                logger_groups={"шумные": list(ЧЛЕНЫ)},
                loggers={"шумные": LoggerRuleSchema(channels=["цех"])},
            )
        )
        yield manager
        manager.shutdown()

    def test_all_three_members_land_in_the_group_channel(self, logger: Any, tmp_path) -> None:
        for i, name in enumerate(ЧЛЕНЫ):
            logger.log(LogScope.SYSTEM, LogLevel.INFO, f"запись-{i}", name)
        logger.flush()

        цех = (tmp_path / "цех.log").read_text(encoding="utf-8")
        общий = (tmp_path / "общий.log").read_text(encoding="utf-8")

        assert [f"запись-{i}" in цех for i in range(3)] == [True, True, True]
        assert [f"запись-{i}" in общий for i in range(3)] == [False, False, False]

    def test_a_non_member_is_untouched(self, logger: Any, tmp_path) -> None:
        """Пара: ярлык адресует НАБОР, а не всё подряд."""
        logger.log(LogScope.SYSTEM, LogLevel.INFO, "посторонний", "чужой.источник")
        logger.flush()

        assert "посторонний" in (tmp_path / "общий.log").read_text(encoding="utf-8")
        assert "посторонний" not in (tmp_path / "цех.log").read_text(encoding="utf-8")

    def test_groups_survive_reconfigure(self, logger: Any, tmp_path) -> None:
        """Пересборка обязана раскрывать ярлыки так же, как старт.

        Точек сборки дерева две, и разъехавшись, они дали бы «работало до
        reload» — тот же класс, что дважды стоил фазе профиля уровня (2.3a).
        """
        logger.reconfigure(
            {
                "app_name": "groups25",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "channels": {"цех": {"type": "file", "enabled": True, "file_path": "цех.log", "rotate": False}},
                "default_level": "DEBUG",
                "scopes": {"SYSTEM": {"channels": ["цех"]}},
                "logger_groups": {"шумные": list(ЧЛЕНЫ)},
                "loggers": {"шумные": {"level": "ERROR"}},
            }
        )

        assert [logger.effective_level(name) for name in ЧЛЕНЫ] == ["ERROR", "ERROR", "ERROR"]

    def test_conflict_is_heard_through_the_emergency_exit(self, tmp_path, caplog) -> None:
        """Жалоба идёт stdlib-выходом: на старте дерево собирается ДО каналов."""
        with caplog.at_level(logging.WARNING):
            manager = LoggerManager(
                config=LoggerManagerConfig(
                    app_name="groups25c",
                    log_directory=str(tmp_path),
                    enable_batching=False,
                    channels={"общий": LoggerChannelSchema(type="file", enabled=True, file_path="о.log")},
                    logger_groups={"альфа": ["общий.источник"], "бета": ["общий.источник"]},
                    loggers={"альфа": LoggerRuleSchema(level="DEBUG"), "бета": LoggerRuleSchema(level="ERROR")},
                )
            )
            manager.shutdown()

        жалобы = [r.getMessage() for r in caplog.records if "группы" in r.getMessage()]
        assert len(жалобы) == 1, жалобы
        assert "альфа" in жалобы[0] and "бета" in жалобы[0]


class TestGroupsTravelFromTheApplicationLayer:
    """Ярлык объявляют в `system.yaml`, а действует он в конфиге менеджера.

    Без этой проверки инъекция в раскладку слоя дала бы ноль красных — и это
    была бы дыра покрытия, а не зелень: механизм работал бы только там, где
    конфиг менеджера собирают руками (то есть в тестах).
    """

    def test_observability_section_reaches_the_manager_config(self) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        expanded = expand_observability({"logger_groups": {"шумные": list(ЧЛЕНЫ)}})

        assert expanded["logger"]["logger_groups"] == {"шумные": list(ЧЛЕНЫ)}

    def test_absent_section_does_not_invent_groups(self) -> None:
        """Пара: пустой дефолт — часть контракта, а не «ещё не заполнили»."""
        from multiprocess_framework.modules.process_module.configs.observability_config import (
            expand_observability,
        )

        assert "logger_groups" not in expand_observability({})["logger"]
