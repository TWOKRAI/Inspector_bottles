# -*- coding: utf-8 -*-
"""Ф3.5 — ``Resource`` процесса: собран один раз, есть в каждой записи.

Понятие из словаря OTel — набор атрибутов того, кто породил телеметрию. Каркас
был с Ф0.5 (база контекста логгера), содержимого в нём было одно поле.

Свойства, которые здесь стерегутся:

1. набор собирается ОДИН раз (база процесса), а не на запись;
2. недостающее поле **пропускается**, а не заполняется словом «unknown»:
   отсутствие ключа честно значит «не знаем», заглушка выглядела бы знанием;
3. ни одна ветка сборки не вправе уронить процесс — Resource это украшение
   записи, а не работа;
4. инкарнация действительно берётся из реестра, а не выдумывается: без неё
   записи процесса ДО и ПОСЛЕ перезапуска неотличимы.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


class _FakeProcessData:
    def __init__(self, metadata: Dict[str, Any]) -> None:
        self.metadata = metadata


class _FakePSR:
    def __init__(self, metadata: Dict[str, Any] | None) -> None:
        self._metadata = metadata

    def get_process_data(self, name: str) -> Any:
        return _FakeProcessData(self._metadata) if self._metadata is not None else None


class _FakeShared:
    def __init__(self, psr: Any) -> None:
        self.process_state_registry = psr


def _process(*, metadata: Dict[str, Any] | None = None, config: Dict[str, Any] | None = None) -> ProcessModule:
    """Процесс без initialize(): ``_build_resource`` трогает только имя, PSR и конфиг.

    ``config_handler = None`` выставляется ЯВНО, и это не формальность:
    ``get_config`` смотрит на него первым, а у объекта, собранного через
    ``__new__``, атрибута нет вовсе — вызов падал бы ``AttributeError`` внутри
    защитного ``except`` и тихо давал набор без рецепта. Тест бы «прошёл», ничего
    не проверив. Тот же класс харнесного дефекта уже описан в докстринге
    ``ProcessModule.update_config`` (R6, 2026-07-29) — и повторился здесь.
    """
    proc = ProcessModule.__new__(ProcessModule)
    proc.name = "camera_0"
    proc.shared_resources = _FakeShared(_FakePSR(metadata))
    proc.config = dict(config or {})
    proc.config_handler = None
    return proc


class TestResourceContent:
    def test_full_set_is_collected(self) -> None:
        proc = _process(
            metadata={"routing_incarnation": 3},
            config={"observability_recipe_path": "d:/proj/recipes/dualcam_synth.yaml"},
        )
        resource = proc._build_resource()

        assert resource["proc_name"] == "camera_0"
        assert resource["incarnation"] == 3
        assert resource["recipe"] == "dualcam_synth", "в записи должно ехать имя рецепта, а не путь"
        assert resource["fw_version"], "версия фреймворка не собрана"

    def test_incarnation_comes_from_the_registry_not_from_thin_air(self) -> None:
        """Без инкарнации записи ДО и ПОСЛЕ перезапуска неотличимы — вот её цена."""
        before = _process(metadata={"routing_incarnation": 0})._build_resource()
        after = _process(metadata={"routing_incarnation": 1})._build_resource()

        assert before["incarnation"] == 0
        assert after["incarnation"] == 1
        assert before["incarnation"] != after["incarnation"]

    def test_version_is_the_framework_one(self) -> None:
        """Версий в проекте две и они расходятся; в записи — версия КОДА.

        ``pyproject`` описывает дистрибутив (0.1.0), ``__version__`` — фреймворк
        (2.0.0). Выбор сделан один раз здесь; тест сторожит, что он не съедет
        молча на другую.
        """
        from multiprocess_framework import __version__

        assert _process()._build_resource()["fw_version"] == __version__


class TestMissingPiecesAreOmittedNotFaked:
    def test_no_registry_no_incarnation_key(self) -> None:
        proc = _process(metadata=None)
        assert "incarnation" not in proc._build_resource()

    def test_no_recipe_no_recipe_key(self) -> None:
        assert "recipe" not in _process(metadata={"routing_incarnation": 1})._build_resource()

    def test_empty_recipe_path_is_not_an_empty_name(self) -> None:
        """Пустой путь — это «не знаем», а не рецепт с пустым именем."""
        proc = _process(config={"observability_recipe_path": ""})
        assert "recipe" not in proc._build_resource()

    def test_process_name_is_always_there(self) -> None:
        """Минимум набора не зависит ни от чего внешнего."""
        proc = ProcessModule.__new__(ProcessModule)
        proc.name = "lonely"
        proc.shared_resources = None
        proc.config = {}
        proc.config_handler = None
        assert proc._build_resource()["proc_name"] == "lonely"


class TestCollectionNeverBreaksTheProcess:
    """Resource — украшение записи; уронить им инициализацию нельзя."""

    def test_exploding_registry_does_not_raise(self) -> None:
        class _Boom:
            def get_process_data(self, name: str) -> Any:
                raise RuntimeError("реестр развалился")

        proc = _process()
        proc.shared_resources = _FakeShared(_Boom())
        resource = proc._build_resource()
        assert resource["proc_name"] == "camera_0"
        assert "incarnation" not in resource

    def test_exploding_config_does_not_raise(self) -> None:
        class _BoomConfig(ProcessModule):
            def get_config(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
                raise RuntimeError("конфиг развалился")

        proc = _BoomConfig.__new__(_BoomConfig)
        proc.name = "camera_0"
        proc.shared_resources = _FakeShared(_FakePSR({"routing_incarnation": 2}))
        proc.config = {}
        proc.config_handler = None
        resource = proc._build_resource()
        assert resource["incarnation"] == 2, "падение одной ветки не должно уносить остальные"
        assert "recipe" not in resource


class TestResourceIsCollectedOnceAndReachesRecords:
    def test_real_initialize_puts_the_whole_set_into_the_base(self) -> None:
        """ПРОВОДКА: настоящий ``initialize()``, а не повтор его строки.

        Первая редакция этого теста сама звала
        ``set_base_context(**proc._build_resource())`` — то есть повторяла строку
        шага 9 вместо того, чтобы её проверить. Слом-инъекция это и показала:
        откат шага 9 к прежнему ``proc_name=self.name`` не убивал НИ ОДНОГО
        теста. Собрать набор верно и не поставить его — то же самое, что не
        собрать.

        Свидетель — ``fw_version``: в прежней строке его не было, поэтому его
        присутствие в базе доказывает, что зовётся именно ``_build_resource``.
        """
        process = ProcessModule("resource_wiring_probe")
        try:
            assert process.initialize() is True, "initialize() не прошёл на пустом конфиге"

            logger = process.get_manager("logger")
            assert logger is not None, "логгера нет — проверять проводку не на чем"
            base = logger._get_base_context()

            assert base.get("proc_name") == "resource_wiring_probe"
            assert base.get("fw_version"), "в базе процесса нет fw_version — шаг 9 кладёт не Resource, а одно имя"
        finally:
            process.shutdown()

    def test_every_record_carries_the_resource(self, tmp_path: Any) -> None:
        """Сквозная пара на НАСТОЯЩЕМ логгере: набор виден в записи."""
        from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        class _Sink:
            name = "collect"

            def __init__(self) -> None:
                self.records: list = []

            def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
                self.records.append(data)
                return {"status": "success"}

            def close(self) -> None: ...

        logger = LoggerManager(
            manager_name="ResourceProbe",
            config={
                "app_name": "res",
                "log_directory": str(tmp_path),
                "enable_batching": False,
                "modules": {},
                "channels": {"f": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
                "scopes": {"SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["f"]}},
            },
        )
        logger.initialize()
        try:
            sink = _Sink()
            logger.add_tap(sink, min_level="DEBUG", name="collect")
            logger.set_base_context(**_process(metadata={"routing_incarnation": 5})._build_resource())

            logger.log(LogScope.SYSTEM, LogLevel.INFO, "любая запись", module="m")

            extra = sink.records[0]["extra"]
            assert extra["proc_name"] == "camera_0"
            assert extra["incarnation"] == 5
            assert extra["fw_version"]
        finally:
            logger.shutdown()


@pytest.mark.parametrize("field", ["proc_name", "fw_version", "incarnation", "recipe"])
def test_resource_field_names_are_stable(field: str) -> None:
    """Имена полей — контракт наружу (стор, GUI, будущий экспортёр OTLP).

    Литералами, а не производной от кода: тест, берущий имена из проверяемого
    места, согласится с любым переименованием.
    """
    resource = _process(
        metadata={"routing_incarnation": 1},
        config={"observability_recipe_path": "r/x.yaml"},
    )._build_resource()
    assert field in resource


class TestConfigDeliveryShapes:
    """Ключ рецепта обязан находиться в ОБЕИХ формах доставки конфига.

    Live-прогон webcam_sketch (ревью Ф3, 2026-08-05): ассемблер кладёт
    ``observability_recipe_path`` ВНУТРЬ ``proc_dict["config"]``, а ребёнок
    получает конфигом весь proc_dict — прикладные ключи у него лежат под
    ``config.<ключ>``. Плоскую форму видят PM-оркестратор и тестовый харнес;
    код, читавший только её, на живом стенде молча терял поле ``recipe`` во
    всех записях. Класс уже записан в памяти проекта после 5.12 («форма
    доставки конфига различается», хелпер ``read_process_config``) — и
    повторился здесь, потому что харнес Ф3.5 пинил только плоскую форму.

    Вложенная форма проверяется на НАСТОЯЩЕМ ``Config`` в роли
    ``config_handler`` (dot-notation — его свойство): фейковый словарь с
    самодельной точечной адресацией доказывал бы фейк, а не проводку.
    """

    def test_recipe_is_found_in_the_nested_live_shape(self) -> None:
        from multiprocess_framework.modules.config_module import Config

        proc = _process()
        proc.config_handler = Config(
            initial_data={"config": {"observability_recipe_path": "recipes/webcam_sketch.yaml"}}
        )
        assert proc._build_resource().get("recipe") == "webcam_sketch", (
            "живая форма доставки (ключ внутри proc_dict['config']) осталась без имени рецепта"
        )

    def test_flat_shape_still_wins_when_both_present(self) -> None:
        from multiprocess_framework.modules.config_module import Config

        proc = _process()
        proc.config_handler = Config(
            initial_data={
                "observability_recipe_path": "recipes/flat.yaml",
                "config": {"observability_recipe_path": "recipes/nested.yaml"},
            }
        )
        assert proc._build_resource().get("recipe") == "flat"
