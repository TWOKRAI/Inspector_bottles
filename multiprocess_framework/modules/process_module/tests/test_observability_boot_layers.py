# -*- coding: utf-8 -*-
"""Пересборка наблюдаемости на boot — ветка ``boot:layers`` (ревью Task 5.13).

Почему отдельный файл. Механизм ``_apply_boot_observability_layers`` имеет две
ветки, и до этого ревью тестами была закрыта только одна:

* ``boot:companion`` — спутник рецепта говорит про этот процесс
  (``test_observability_companion.py``, четыре теста);
* ``boot:layers`` — **менеджеры не пришли готовыми**, и слои надо разложить
  здесь. Это КОРЕНЬ дефекта задачи 5.13 (оркестратор спавнится без ключа
  ``managers`` и поднимался на голых дефолтах L0), и он не был закрыт ничем,
  кроме живого зонда вне CI. Слом-инъекция ревьюера (``managers_ready = True``)
  оставляла весь набор из 6301 теста зелёным.

Здесь же — инвариант, который ревью нашло рядом: пустая секция менеджеров
разрешает пересборку ТОЛЬКО вместе с непустыми слоями. Иначе встройщик
фреймворка, собравший ``LoggerManager`` программно и не заводивший секцию,
молча получал бы дефолты L0 вместо своей настройки.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    ObservabilityLayers,
    apply_layers_to_proc_dict,
    layers_are_silent,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


class _ConfigHandler:
    """Секция менеджеров в том виде, в каком её отдаёт настоящий handler."""

    def __init__(self, managers: Optional[Dict[str, Any]], *, raises: bool = False) -> None:
        self._managers = managers
        self._raises = raises

    def get_managers_config(self) -> Dict[str, Any]:
        if self._raises:
            raise RuntimeError("конфиг нечитаем")
        return self._managers or {}


class _Proc:
    """Процесс в форме, в какой конфиг доезжает до ОРКЕСТРАТОРА — плоско.

    Оркестратору ``spawner`` мержит ``orchestrator_config`` в корень, поэтому
    ключи лежат без префикса ``config.``. Именно на этом адресате дефект и жил.
    """

    def __init__(self, name: str, logger: LoggerManager, flat_config: Dict[str, Any], handler) -> None:
        self.name = name
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.config_handler = handler
        self._flat = flat_config
        self.errors: List[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        node: Any = self._flat
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def _log_error(self, msg: str, **kw: Any) -> None:
        self.errors.append(msg)

    def _log_info(self, msg: str, **kw: Any) -> None:
        pass

    _apply_boot_observability_layers = ProcessModule._apply_boot_observability_layers


def _logger(tmp_path, **kw: Any) -> LoggerManager:
    cfg = LoggerManagerConfig(app_name="boot", log_directory=str(tmp_path), enable_batching=False, **kw)
    return LoggerManager(config=cfg)


class TestBootLayersAppliedWhenAssemblerDidNot:
    """Корень 5.13: менеджеров в bundle нет → слои раскладываются на старте.

    Приёмка A1/A6 доказывалась только живым зондом (вне CI). Здесь тот же факт
    закреплён на уровне механизма, без запуска системы.
    """

    def test_empty_managers_section_makes_layers_apply(self, tmp_path) -> None:
        """L1 говорит WARNING, секция менеджеров пуста → уровень применён."""
        logger = _logger(tmp_path)
        proc = _Proc(
            "ProcessManager",
            logger,
            {APP_CONFIG_KEY: {"log_level": "WARNING"}},
            _ConfigHandler({}),  # ассемблер этого процесса не касался
        )
        try:
            assert logger.config.default_level == "INFO", "предусловие: до пересборки — дефолт L0"
            proc._apply_boot_observability_layers()
            assert logger.config.default_level == "WARNING"
            assert proc.errors == []
        finally:
            logger.shutdown()

    def test_ready_managers_section_leaves_them_alone(self, tmp_path) -> None:
        """Ребёнку со свежим proc_dict пересборка не нужна — и не делается.

        Вторая половина пары: без неё тест выше был бы зелёным и у реализации
        «пересобирать ВСЕГДА», которая ломает ранний выход.
        """
        logger = _logger(tmp_path)
        proc = _Proc(
            "camera_0",
            logger,
            {APP_CONFIG_KEY: {"log_level": "WARNING"}},
            _ConfigHandler({"logger_manager": {"default_level": "ERROR"}}),
        )
        try:
            proc._apply_boot_observability_layers()
            assert logger.config.default_level == "INFO", "менеджеры пришли готовыми — слои их не трогают"
        finally:
            logger.shutdown()

    def test_silent_layers_do_not_reset_programmatic_config(self, tmp_path) -> None:
        """Инвариант ревью: молчащие слои не дают повода трогать менеджеры.

        Встройщик собрал логгер программно (уровень ERROR) и секции менеджеров
        не завёл. Пересборка «потому что секция пуста» вернула бы его к дефолту
        L0 — то есть тихо отменила бы его решение.
        """
        logger = _logger(tmp_path, default_level="ERROR")
        proc = _Proc("embedded", logger, {}, _ConfigHandler({}))
        try:
            proc._apply_boot_observability_layers()
            assert logger.config.default_level == "ERROR"
        finally:
            logger.shutdown()

    def test_unreadable_managers_section_is_loud(self, tmp_path) -> None:
        """Отказ чтения выбирает консервативную ветку — и обязан оставить след.

        Он ОТМЕНЯЕТ пересборку, то есть меняет поведение. Проглоченный молча, он
        оставил бы процесс на дефолтах L0 без причины в журнале.
        """
        logger = _logger(tmp_path)
        proc = _Proc(
            "ProcessManager",
            logger,
            {APP_CONFIG_KEY: {"log_level": "WARNING"}},
            _ConfigHandler(None, raises=True),
        )
        try:
            proc._apply_boot_observability_layers()
            assert proc.errors, "отказ чтения секции менеджеров проглочен молча"
            assert "менеджеров" in proc.errors[0]
        finally:
            logger.shutdown()


class TestLayersAreSilentRule:
    """Правило «слои молчат → накладывать нечего» — одно на три адресата."""

    def test_empty_layers_are_silent(self) -> None:
        assert layers_are_silent(ObservabilityLayers(app={}, recipe={})) is True

    def test_any_declared_key_breaks_silence(self) -> None:
        assert layers_are_silent(ObservabilityLayers(app={"log_level": "DEBUG"}, recipe={})) is False
        assert layers_are_silent(ObservabilityLayers(app={}, recipe={"log_level": "DEBUG"})) is False

    def test_silent_layers_do_not_create_managers_key(self) -> None:
        """Ключ не появляется — не «появляется пустым» и не «появляется с L0».

        Ровно этим две дороги сборки и расходились до ревью: прикладная
        накладывала безусловно, и у процесса с молчащими слоями возникала
        секция из голых дефолтов L0.
        """
        proc_dict: Dict[str, Any] = {"config": {}}
        apply_layers_to_proc_dict(proc_dict, ObservabilityLayers(app={}, recipe={}))
        assert "managers" not in proc_dict

    def test_declared_layers_expand_into_managers(self) -> None:
        proc_dict: Dict[str, Any] = {"config": {}}
        apply_layers_to_proc_dict(proc_dict, ObservabilityLayers(app={"log_level": "ERROR"}, recipe={}))
        assert proc_dict["managers"]["logger"]["default_level"] == "ERROR"

    def test_recipe_layer_wins_over_app_layer(self) -> None:
        """Порядок L1 → L2 виден в результате, а не только в докстринге."""
        proc_dict: Dict[str, Any] = {"config": {}}
        layers = ObservabilityLayers(app={"log_level": "ERROR"}, recipe={"log_level": "DEBUG"})
        apply_layers_to_proc_dict(proc_dict, layers)
        assert proc_dict["managers"]["logger"]["default_level"] == "DEBUG"


class TestCompanionOverlaySeam:
    """Общий шов ``compose_over_base`` — спутник ложится ПОВЕРХ дольки рецепта.

    Пришёл на смену ``TestCompanionMergeSeam`` вместе с ФР-3. Прежний шов
    (``merge_companion_over``) мержил спутник в СЕКЦИЮ рецепта — то есть в базу
    слоя, которую процесс кладёт себе в конфиг и переживает. Слой заменяется
    целиком, база — нет, поэтому снятый из спутника ключ жил вечно на прикладной
    дороге и честно исчезал на generic. Шов удалён вместе с дефектом; здесь
    стережётся то, что от него осталось верного: направление «спутник сверху» и
    сохранность ключей рецепта, о которых спутник молчит.
    """

    @pytest.fixture()
    def recipe(self, tmp_path):
        path = tmp_path / "demo.yaml"
        path.write_text("name: demo\n", encoding="utf-8")
        return path

    def test_companion_wins_over_the_recipe_slice(self, recipe) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            companion_path,
            compose_over_base,
            write_companion,
        )

        write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
        body, source = compose_over_base({"log_level": "INFO", "console": True}, recipe, "seg")
        assert body["log_level"] == "DEBUG", "спутник новее — он сверху"
        assert body["console"] is True, "ключи рецепта, о которых спутник молчит, живы"
        assert source == str(companion_path(recipe)), "источником обязан называться спутник"

    def test_companion_defaults_also_win_over_the_recipe_slice(self, recipe) -> None:
        """Ручная правка спутника (``defaults``) — тоже сверху.

        Вторая половина ФР-3: у прежнего секционного шва здесь побеждал
        ``processes[<имя>]`` рецепта, потому что мерж шёл ДО резолва. То есть
        направление «спутник сверху» на той дороге не держалось вовсе — и это
        было невидимо, пока спутник писала только машина (она пишет
        ``processes:``).
        """
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            compose_over_base,
            write_companion,
        )

        write_companion(recipe, {"defaults": {"log_level": "DEBUG"}})
        body, _ = compose_over_base({"log_level": "INFO"}, recipe, "seg")
        assert body["log_level"] == "DEBUG"

    def test_no_recipe_path_returns_the_base_unchanged(self) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            compose_over_base,
        )

        base = {"log_level": "INFO"}
        assert compose_over_base(base, "", "seg") == (base, "")

    def test_absent_companion_keeps_the_recipe_slice(self, recipe) -> None:
        """Спутника нет — штатное состояние, слой равен дольке рецепта."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            compose_over_base,
        )

        assert compose_over_base({"log_level": "INFO"}, recipe, "seg") == ({"log_level": "INFO"}, str(recipe))

    def test_broken_companion_raises_so_the_caller_picks_the_policy(self, recipe) -> None:
        """Шов не решает за вызывающего: на boot уместен отказ, на switch — жалоба."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            companion_path,
            compose_over_base,
        )

        companion_path(recipe).write_text("observability: [не словарь\n", encoding="utf-8")
        with pytest.raises(Exception):
            compose_over_base({}, recipe, "seg")
