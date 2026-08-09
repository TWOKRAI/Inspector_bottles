# -*- coding: utf-8 -*-
"""Ф2.6 — «свой файл И общий»: добавка приёмников поверх унаследованных.

План: plans/observability-unified-routing.md, задача 2.6, решение Р-2.6-Ж.

Зачем понадобилось. Ф2.2 сделала правило по имени ЗАМЕЩАЮЩИМ, и слова «additivity»
не было ни в одной врезке — это упущение, а не решение. Снесённый ``modules`` при
этом был АДДИТИВНЫМ: ``_route`` добавлял ``module_<имя>`` к каналам скоупа, и дефолт
фиксировал прямо — «логи с ``module="trace"`` уходят сюда ПЛЮС в scope-каналы».
Перенос таких маршрутов на замещающее правило был бы тихой сменой поведения: файл
остался бы непустым, а из ``system.log`` записи исчезли, и приёмка «маршрут жив»
этого не заметила бы — она проверяет только новый файл.

Выразить «и свой, и общий» через ``channels`` нельзя в принципе: правило про скоуп
не знает, а наборы у скоупов разные. Пришлось бы скопировать список, живущий в другом
месте, — та самая вторая копия строки, ради устранения которой заведено объявление
имени.
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.logger_module.configs import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.log_config import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.name_hierarchy import NameHierarchy


class _Rule:
    """Правило чем угодно — резолв на Pydantic-схему не завязан (контракт 2.2)."""

    def __init__(self, level=None, channels=None, channels_extra=None) -> None:
        self.level = level
        self.channels = channels
        self.channels_extra = channels_extra


class TestAccumulationAlongTheBranch:
    """Добавки копятся по ВСЕЙ ветке — в отличие от ``channels``."""

    def test_all_ancestors_contribute(self) -> None:
        hierarchy = NameHierarchy(
            {
                "": _Rule(channels_extra=["root_f"]),
                "a": _Rule(channels_extra=["a_f"]),
                "a.b": _Rule(channels_extra=["leaf_f"]),
            }
        )
        assert hierarchy.channels_extra("a.b.c") == ("root_f", "a_f", "leaf_f")

    def test_leaf_does_not_cancel_the_package(self) -> None:
        """Главный инвариант операции — против «побеждает длиннейший префикс».

        Если бы добавка резолвилась как ``channels``, объявление у листа молча
        отменило бы добавку у пакета: маршрут потерял бы приёмник, и узнать об
        этом можно было бы только по пустому файлу — через недели.
        """
        hierarchy = NameHierarchy({"a": _Rule(channels_extra=["a_f"]), "a.b": _Rule(channels_extra=["leaf_f"])})
        assert "a_f" in hierarchy.channels_extra("a.b")

    def test_order_is_root_to_leaf(self) -> None:
        """Общие приёмники раньше частных, порядок устойчив между запусками."""
        hierarchy = NameHierarchy({"": _Rule(channels_extra=["z"]), "a.b": _Rule(channels_extra=["y"])})
        assert hierarchy.channels_extra("a.b") == ("z", "y")

    def test_duplicates_are_dropped(self) -> None:
        """Один приёмник, названный дважды на ветке, не удваивает запись (Ф0.9)."""
        hierarchy = NameHierarchy({"a": _Rule(channels_extra=["same"]), "a.b": _Rule(channels_extra=["same"])})
        assert hierarchy.channels_extra("a.b") == ("same",)

    def test_empty_list_adds_nothing_and_cancels_nothing(self) -> None:
        """``[]`` — «ничего не добавляю», НЕ отмена добавок предков.

        Отмена была бы третьей операцией на оси, и её никто не просил. Здесь
        молчание и объявленная пустота совпадают по смыслу — в отличие от
        ``channels``, где различие несущее.
        """
        hierarchy = NameHierarchy({"a": _Rule(channels_extra=["a_f"]), "a.b": _Rule(channels_extra=[])})
        assert hierarchy.channels_extra("a.b") == ("a_f",)

    def test_absent_key_gives_empty_tuple(self) -> None:
        assert NameHierarchy({"a": _Rule(channels=["x"])}).channels_extra("a.b") == ()

    def test_cache_is_forgotten_with_the_rest(self) -> None:
        """Третий кэш обязан стареть вместе с двумя — иначе «сменил, а не сменилось».

        Проверяется САМА карта, а не значение после сброса. Первая редакция этого
        теста сравнивала значения — и пережила собственный слом: таблица правил
        неизменна, поэтому пересчёт даёт то же самое, и тест был зелёным с
        полностью снятым ``_extra_cache.clear()``. Через значение свойство не
        наблюдаемо в принципе, и код это признаёт прямо (``logger_core``: «сегодня
        этот вызов избыточен, и это сказано прямо, а не выдано за защиту»).
        Образец — соседний ``test_clear_cache_forgets_both_maps`` из тестов 2.2.
        """
        hierarchy = NameHierarchy({"a": _Rule(channels_extra=["a_f"])})
        hierarchy.channels_extra("a.b")
        assert hierarchy._extra_cache  # noqa: SLF001 — предмет проверки
        hierarchy.clear_cache()
        assert not hierarchy._extra_cache  # noqa: SLF001


def _read(tmp_path, name: str) -> str:
    path = tmp_path / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _manager(tmp_path, loggers: Dict[str, Any]) -> Any:
    return LoggerManager(
        config=LoggerManagerConfig(
            app_name="extra26",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={
                "common": LoggerChannelSchema(type="file", enabled=True, file_path="common.log", rotate=False),
                "own": LoggerChannelSchema(type="file", enabled=True, file_path="own.log", rotate=False),
            },
            default_level="DEBUG",
            scopes={"SYSTEM": LoggerScopeSchema(channels=["common"])},
            loggers=loggers,
        )
    )


class TestRouteWritesToBoth:
    """Проводка целиком: запись реально ложится в оба файла, а не в один."""

    def test_extra_is_added_to_the_scope_set(self, tmp_path) -> None:
        """Случай ради которого операция заведена: правило про приёмники МОЛЧИТ.

        Здесь база берётся у скоупа, и добавка обязана сложиться именно с ней —
        иначе «свой файл и общий» выражалось бы только там, где правило приёмники
        уже задало, то есть ровно не там, где нужно.
        """
        manager = _manager(tmp_path, {"src": {"channels_extra": ["own"]}})
        try:
            manager.system(LogLevel.INFO, "в оба", module="src")
            manager.flush()
        finally:
            manager.shutdown()

        assert "в оба" in _read(tmp_path, "own.log")
        assert "в оба" in _read(tmp_path, "common.log")

    def test_extra_is_added_to_a_rule_set(self, tmp_path) -> None:
        """Вторая база — набор самого правила. Складывается так же."""
        manager = _manager(tmp_path, {"src": {"channels": ["common"], "channels_extra": ["own"]}})
        try:
            manager.system(LogLevel.INFO, "тоже в оба", module="src")
            manager.flush()
        finally:
            manager.shutdown()

        assert "тоже в оба" in _read(tmp_path, "own.log")
        assert "тоже в оба" in _read(tmp_path, "common.log")

    def test_channel_named_twice_receives_the_record_once(self, tmp_path) -> None:
        """Приёмник и в базе, и в добавке — запись одна, не две (инвариант Ф0.9).

        Считается ВХОЖДЕНИЯМИ в файле, а не полем маршрута: дедупликация в резолве
        не спасла бы, если бы сложение в ``_route`` добавляло повторно.
        """
        manager = _manager(tmp_path, {"src": {"channels": ["own"], "channels_extra": ["own"]}})
        try:
            manager.system(LogLevel.INFO, "ровно один раз", module="src")
            manager.flush()
        finally:
            manager.shutdown()

        assert _read(tmp_path, "own.log").count("ровно один раз") == 1

    def test_without_extra_behaviour_is_unchanged(self, tmp_path) -> None:
        """Пара: без добавки запись идёт только в набор скоупа, как до Ф2.6."""
        manager = _manager(tmp_path, {})
        try:
            manager.system(LogLevel.INFO, "только общий", module="src")
            manager.flush()
        finally:
            manager.shutdown()

        assert "только общий" in _read(tmp_path, "common.log")
        assert "только общий" not in _read(tmp_path, "own.log")


class TestSchemaAcceptsIt:
    def test_dict_rule_is_validated_into_the_schema(self, tmp_path) -> None:
        """Правило-словарь приводится к схеме, а не резолвится в «молчу».

        Этот капкан уже стрелял в фазе дважды (2.2 и 2.3a): сырой ``dict`` не
        имеет атрибута, ``getattr`` возвращает ``None``, и правило молча не
        действует. Третий путь обязан пройти ту же проверку.
        """
        manager = _manager(tmp_path, {"src": {"channels_extra": ["own"]}})
        try:
            rule = manager.config.loggers["src"]
            assert rule.channels_extra == ["own"]
        finally:
            manager.shutdown()
