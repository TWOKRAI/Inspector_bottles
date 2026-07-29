# -*- coding: utf-8 -*-
"""Task 5.12 (шаг 7) — спутник рецепта: «сохранить» не трогает файл человека.

Прежняя редакция приёмки («git diff рецепта чист») была ВАКУУМНОЙ при выборе
спутника: машина в рецепт не пишет, diff пуст при любой реализации, включая
сломанную. Поэтому здесь проверяется тройка:
  1. файл человека не изменён ни на байт;
  2. спутник содержит РОВНО изменённые ключи;
  3. пара «рецепт + спутник» после загрузки даёт то же действующее состояние.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import yaml

from multiprocess_framework.modules.data_schema_module import deep_merge
from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_companion import (
    COMPANION_SUFFIX,
    companion_path,
    load_companion,
    write_companion,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    RECIPE_PATH_CONFIG_KEY,
    ObservabilityLayers,
    process_observability_layers,
    resolve_recipe_section,
)

_RECIPE_TEXT = """# Рецепт, написанный человеком. Комментарии — часть файла.
name: demo
blueprint:
  processes: []
  wires: []
"""


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _Svc:
    def __init__(self, logger, config=None) -> None:
        self.command_manager = _Cm()
        self.name = "seg"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self._config = dict(config or {})
        self.log_calls: List[tuple] = []

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_debug(self, msg, **kw):
        self.log_calls.append(("DEBUG", msg, kw))

    def _log_info(self, msg, **kw):
        self.log_calls.append(("INFO", msg, kw))


@pytest.fixture
def recipe(tmp_path):
    path = tmp_path / "demo.yaml"
    path.write_text(_RECIPE_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def wired(tmp_path, recipe):
    logger = LoggerManager(
        config=LoggerManagerConfig(app_name="persist", log_directory=str(tmp_path), enable_batching=False)
    )
    svc = _Svc(logger, config={RECIPE_PATH_CONFIG_KEY: str(recipe)})
    BuiltinCommands(svc)._register_observability_commands()
    try:
        yield svc, svc.command_manager.handlers, recipe
    finally:
        logger.shutdown()


class TestCompanionFileContract:
    def test_path_sits_next_to_the_recipe(self, recipe) -> None:
        assert companion_path(recipe) == recipe.with_name("demo" + COMPANION_SUFFIX)

    def test_absent_companion_is_not_an_error(self, recipe) -> None:
        assert load_companion(recipe) == {}

    def test_write_is_idempotent_and_does_not_touch_mtime(self, recipe) -> None:
        """Повторная запись того же не будит watcher — иначе петля применений."""
        section = {"processes": {"seg": {"log_level": "DEBUG"}}}
        path, written = write_companion(recipe, section)
        assert written is True
        before = path.stat().st_mtime_ns

        path2, written2 = write_companion(recipe, section)
        assert written2 is False
        assert path2.stat().st_mtime_ns == before

    def test_file_declares_itself_machine_owned(self, recipe) -> None:
        """Предупреждение живёт В ФАЙЛЕ: документацию при отладке не открывают."""
        path, _ = write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
        assert "MACHINE-OWNED" in path.read_text(encoding="utf-8")

    def test_failed_replace_leaves_the_previous_content_intact(self, recipe, monkeypatch) -> None:
        """Атомарность — заявление, требующее воспроизведения (иначе это обещание).

        Сбой на подмене (на Windows ``os.replace`` уже давал ``WinError 5`` в этом
        проекте) не имеет права оставить полуфайл: читатель, увидевший обрезанный
        YAML, получит отказ старта вместо сохранённых настроек.
        """
        import os as _os

        write_companion(recipe, {"processes": {"seg": {"log_level": "INFO"}}})
        path = companion_path(recipe)
        before = path.read_text(encoding="utf-8")

        def _boom(src, dst):
            raise OSError("WinError 5 (симуляция)")

        monkeypatch.setattr(_os, "replace", _boom)
        with pytest.raises(OSError):
            write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})

        assert path.read_text(encoding="utf-8") == before, "прежнее содержимое повреждено"
        assert [p.name for p in recipe.parent.glob("*.tmp*")] == [], "остался мусорный tmp"

    def test_write_leaves_no_temporary_files_behind(self, recipe) -> None:
        write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
        assert [p.name for p in recipe.parent.glob("*.tmp*")] == []


class TestPersistCommand:
    def test_human_file_untouched_companion_holds_exactly_the_changes(self, wired) -> None:
        svc, handlers, recipe = wired
        before_bytes = recipe.read_bytes()

        handlers["logger.sink.disable"]({"sink": "messages_file"})
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        res = handlers["observability.persist"]({})

        assert res["success"] is True
        # 1. Файл человека — ни на байт.
        assert recipe.read_bytes() == before_bytes
        # 2. Спутник — РОВНО изменённые ключи, под именем своего процесса.
        section = load_companion(recipe)
        assert section == {
            "processes": {"seg": {"channels": {"messages_file": {"enabled": False}}, "log_level": "DEBUG"}}
        }
        assert sorted(res["keys"]) == ["channels.messages_file.enabled", "log_level"]

    def test_after_load_the_pair_gives_the_same_effective_state(self, wired) -> None:
        """3. Рецепт + спутник → то же действующее состояние, что было до сохранения."""
        svc, handlers, recipe = wired
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        applied_before = svc.logger_manager.config.default_level
        handlers["observability.persist"]({})

        # Свежая загрузка: L2 из спутника, сессии нет — как после рестарта.
        fresh = ObservabilityLayers(recipe=resolve_recipe_section(load_companion(recipe), "seg"))
        assert fresh.resolve()["log_level"] == applied_before

        # И сосед по рецепту получает только defaults, а не чужую per-process правку.
        neighbour = ObservabilityLayers(recipe=resolve_recipe_section(load_companion(recipe), "other"))
        assert "log_level" not in neighbour.resolve()

    def test_keys_move_from_session_to_recipe_layer(self, wired) -> None:
        """После сохранения provenance обязан говорить `recipe`, а не `session`.

        Иначе оператор видит «держится сессией» у уже сохранённого и сбросит это,
        думая, что возвращает наследование.
        """
        svc, handlers, recipe = wired
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        assert process_observability_layers(svc).session_keys() == ("log_level",)

        res = handlers["observability.persist"]({})
        layers = process_observability_layers(svc)
        assert res["session_keys"] == []
        assert layers.session == {}
        assert layers.recipe["log_level"] == "DEBUG"
        assert layers.recipe_source.endswith(COMPANION_SUFFIX)
        # Действующее состояние не изменилось — переехал только владелец ключа.
        assert svc.logger_manager.config.default_level == "DEBUG"

    def test_persist_without_a_recipe_path_is_a_loud_refusal(self, tmp_path) -> None:
        logger = LoggerManager(config=LoggerManagerConfig(app_name="nopath", log_directory=str(tmp_path)))
        svc = _Svc(logger)
        BuiltinCommands(svc)._register_observability_commands()
        try:
            svc.command_manager.handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
            res = svc.command_manager.handlers["observability.persist"]({})
            assert res["success"] is False
            assert "рецепт" in res["reason"]
        finally:
            logger.shutdown()

    def test_persist_with_empty_session_refuses_instead_of_writing_nothing(self, wired) -> None:
        svc, handlers, recipe = wired
        res = handlers["observability.persist"]({})
        assert res["success"] is False
        assert not companion_path(recipe).exists()

    def test_neighbour_process_keys_are_preserved(self, wired) -> None:
        """Сохранение одного процесса не имеет права снести настройку соседа."""
        svc, handlers, recipe = wired
        write_companion(recipe, {"processes": {"other": {"log_level": "ERROR"}}})

        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        handlers["observability.persist"]({})

        section = load_companion(recipe)
        assert section["processes"]["other"] == {"log_level": "ERROR"}
        assert section["processes"]["seg"]["log_level"] == "DEBUG"

    def test_companion_is_valid_yaml_with_an_observability_root(self, wired) -> None:
        svc, handlers, recipe = wired
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        handlers["observability.persist"]({})
        loaded = yaml.safe_load(companion_path(recipe).read_text(encoding="utf-8"))
        assert set(loaded) == {"observability"}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])


class TestWatcherOwnsExactlyOneLayer:
    """Файловый watcher обновляет СВОЙ слой и не имеет права трогать чужие."""

    @staticmethod
    def _stack():
        return ObservabilityLayers(
            app={"log_level": "INFO"},
            recipe={"console": False},
            session={"enable_batching": False},
        )

    def test_app_watcher_does_not_wipe_recipe_and_session(self, tmp_path) -> None:
        """Регресс: пересборка «из одной секции» сносила L2/L3 — то есть правка
        system.yaml становилась способом обойти слои, ради которых всё делалось."""
        from multiprocess_framework.modules.config_module.core.config import Config
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            make_observability_on_reload,
        )

        layers = self._stack()
        on_reload = make_observability_on_reload(layers=layers, layer="app")
        on_reload(Config(initial_data={"observability": {"log_level": "WARNING"}}))

        assert layers.app == {"log_level": "WARNING"}
        assert layers.recipe == {"console": False}, "watcher L1 снёс слой рецепта"
        assert layers.session == {"enable_batching": False}, "watcher L1 снёс ручку оператора"

    def test_recipe_watcher_resolves_per_process_and_keeps_the_rest(self, tmp_path) -> None:
        from multiprocess_framework.modules.config_module.core.config import Config
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            make_observability_on_reload,
        )

        layers = self._stack()
        on_reload = make_observability_on_reload(layers=layers, layer="recipe", process_name="seg")
        on_reload(
            Config(
                initial_data={
                    "observability": {
                        "defaults": {"console": True},
                        "processes": {"seg": {"log_level": "ERROR"}, "other": {"log_level": "DEBUG"}},
                    }
                }
            )
        )

        # Разрешено ДЛЯ СВОЕГО процесса: чужая per-process правка не подхвачена.
        assert layers.recipe == {"console": True, "log_level": "ERROR"}
        assert layers.app == {"log_level": "INFO"}
        assert layers.session == {"enable_batching": False}


class TestPersistedLayerSurvivesProcessRespawn:
    """Живая находка прогона 5.12: «сохранить» сохраняло на диск, но не в систему.

    Спутник записан командой ``observability.persist``, а пересозданный процесс
    стартовал из boot-``proc_dict`` и его не читал — уровень откатывался на первом
    же рестарте. Пара доказана живьём: до фикса ``seg`` после restart отвечал
    ``default_level=INFO``, после — ``DEBUG`` с provenance на спутник.
    """

    class _Proc:
        """Процесс в форме, в какой конфиг реально доезжает до ребёнка (весь proc_dict)."""

        def __init__(self, name, logger, proc_dict):
            self.name = name
            self.logger_manager = logger
            self.error_manager = None
            self.stats_manager = None
            self._d = proc_dict
            self.errors: List[str] = []

        def get_config(self, key, default=None):
            node = self._d
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

        def _log_error(self, msg, **kw):
            self.errors.append(msg)

        def _log_info(self, msg, **kw):
            pass

        _apply_persisted_observability_layer = __import__(
            "multiprocess_framework.modules.process_module.core.process_module",
            fromlist=["ProcessModule"],
        ).ProcessModule._apply_persisted_observability_layer

    def _proc(self, tmp_path, recipe):
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="respawn", log_directory=str(tmp_path), enable_batching=False)
        )
        return self._Proc("seg", logger, {"config": {RECIPE_PATH_CONFIG_KEY: str(recipe)}})

    def test_companion_written_after_boot_is_applied_on_start(self, tmp_path, recipe) -> None:
        write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
        proc = self._proc(tmp_path, recipe)
        try:
            assert proc.logger_manager.config.default_level != "DEBUG"
            proc._apply_persisted_observability_layer()
            assert proc.logger_manager.config.default_level == "DEBUG"
            assert proc.errors == []
        finally:
            proc.logger_manager.shutdown()

    def test_no_companion_leaves_boot_managers_untouched(self, tmp_path, recipe) -> None:
        """Пересборка на старте — только когда спутник реально что-то говорит."""
        proc = self._proc(tmp_path, recipe)
        try:
            before = proc.logger_manager.config.model_dump()
            proc._apply_persisted_observability_layer()
            assert proc.logger_manager.config.model_dump() == before
        finally:
            proc.logger_manager.shutdown()

    def test_companion_for_another_process_is_not_applied(self, tmp_path, recipe) -> None:
        write_companion(recipe, {"processes": {"other": {"log_level": "DEBUG"}}})
        proc = self._proc(tmp_path, recipe)
        try:
            proc._apply_persisted_observability_layer()
            assert proc.logger_manager.config.default_level != "DEBUG"
        finally:
            proc.logger_manager.shutdown()

    def test_broken_companion_does_not_kill_the_start(self, tmp_path, recipe) -> None:
        """Битый спутник — громкая запись в ошибки, но процесс стартует."""
        companion_path(recipe).write_text("observability: [не словарь\n", encoding="utf-8")
        proc = self._proc(tmp_path, recipe)
        try:
            proc._apply_persisted_observability_layer()
            assert proc.errors, "битый спутник проглочен молча"
        finally:
            proc.logger_manager.shutdown()


class TestShortFormRecipeSurvivesTheCompanion:
    """Блокер ревью 5.12: первое «сохранить» молча стирало настройки рецепта.

    Спутник ВСЕГДА пишется в форме ``processes:``. Пока `resolve_recipe_section`
    переключалась на структурную ветку по одному лишь наличию этого ключа,
    верхнеуровневые ключи рецепта короткой формы выбрасывались — у сохранившего
    процесса частично, у соседей полностью. Триггер несвязанный (сохранение
    ДРУГОЙ настройки), симптом нулевой.
    """

    def test_top_level_keys_survive_merge_with_a_companion(self) -> None:
        recipe_section = {"log_level": "DEBUG", "console": False}
        companion = {"processes": {"camera_0": {"channels": {"messages_file": {"enabled": False}}}}}
        merged = deep_merge(recipe_section, companion)

        camera = resolve_recipe_section(merged, "camera_0")
        assert camera["log_level"] == "DEBUG", "настройка рецепта исчезла у сохранившего процесса"
        assert camera["console"] is False
        assert camera["channels"] == {"messages_file": {"enabled": False}}

        # У соседа, которого спутник не называет, рецепт обязан остаться целым.
        neighbour = resolve_recipe_section(merged, "seg")
        assert neighbour == {"log_level": "DEBUG", "console": False}

    def test_explicit_defaults_beat_inline_keys_of_the_same_section(self) -> None:
        """Смешанная форма: явные defaults главнее верхнеуровневых остатков."""
        section = {"log_level": "INFO", "defaults": {"log_level": "WARNING"}}
        assert resolve_recipe_section(section, "any")["log_level"] == "WARNING"

    def test_end_to_end_persist_keeps_the_short_form_recipe_effective(self, wired, recipe) -> None:
        """Тот же путь целиком: рецепт короткой формы + реальный persist."""
        svc, handlers, _ = wired
        recipe_section = {"enable_batching": False}

        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        handlers["observability.persist"]({})

        merged = deep_merge(recipe_section, load_companion(recipe))
        resolved = resolve_recipe_section(merged, "seg")
        assert resolved["enable_batching"] is False, "рецепт короткой формы стёрт спутником"
        assert resolved["log_level"] == "DEBUG"


class TestLiveCompanionRefresh:
    """R4 (Task 5.11.f): правка спутника доезжает до ДЕТЕЙ, а не только до оркестратора.

    Watcher за спутником живёт только у оркестратора — своих watcher'ов детям не
    заводим. До 5.11 это означало, что правка файла применялась к менеджерам
    оркестратора, а дети узнавали о ней лишь на следующем рестарте: пульт
    показывал новое значение, писали процессы по-старому.
    """

    @staticmethod
    def _svc(tmp_path, recipe, *, boot_delta=None):
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            OVERRIDE_CONFIG_KEY,
        )

        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="refresh", log_directory=str(tmp_path), enable_batching=False)
        )
        svc = _Svc(
            logger,
            config={
                RECIPE_PATH_CONFIG_KEY: str(recipe),
                OVERRIDE_CONFIG_KEY: dict(boot_delta or {}),
            },
        )
        BuiltinCommands(svc)._register_observability_commands()
        return svc, logger

    def test_reload_flag_picks_up_the_edited_companion(self, tmp_path, recipe) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_effective,
        )

        svc, logger = self._svc(tmp_path, recipe, boot_delta={"log_level": "WARNING"})
        try:
            # Правка спутника «руками» (её и делает оператор через persist/редактор).
            write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})

            res = svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})

            assert res["success"] is True
            assert observability_effective(logger=logger)["logger"]["default_level"] == "DEBUG"
            assert res["recipe_layer"] == ["log_level"]
        finally:
            logger.shutdown()

    def test_reload_replaces_the_layer_so_a_removed_key_disappears(self, tmp_path, recipe) -> None:
        """Домержи мы слой к текущему — снятый из спутника ключ не исчез бы никогда."""
        svc, logger = self._svc(tmp_path, recipe)
        try:
            write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})
            svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})
            layers = process_observability_layers(svc)
            assert layers.recipe == {"log_level": "DEBUG"}

            # Оператор убрал ключ из спутника.
            write_companion(recipe, {"processes": {"seg": {}}})
            svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})

            assert layers.recipe == {}
        finally:
            logger.shutdown()

    def test_boot_and_live_refresh_compose_the_same_layer(self, tmp_path, recipe) -> None:
        """boot ≡ перечитка: одна функция на два пути, иначе старт и reload
        трактовали бы одну и ту же пару файлов по-разному."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            compose_recipe_layer,
        )

        svc, logger = self._svc(tmp_path, recipe, boot_delta={"log_level": "WARNING", "log_directory": "/machine"})
        try:
            write_companion(recipe, {"processes": {"seg": {"log_level": "DEBUG"}}})

            body, source = compose_recipe_layer(svc)
            svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})
            layers = process_observability_layers(svc)

            # Спутник поверх дельты рецепта, машинный ключ рецепта уцелел.
            assert body == {"log_level": "DEBUG", "log_directory": "/machine"}
            assert layers.recipe == body
            assert source == str(companion_path(recipe))
        finally:
            logger.shutdown()

    def test_refresh_without_a_companion_keeps_the_recipe_delta(self, tmp_path, recipe) -> None:
        """Спутника нет — это штатно (его создаёт первое «сохранить»), и слой
        обязан остаться дельтой рецепта, а не опустеть."""
        svc, logger = self._svc(tmp_path, recipe, boot_delta={"log_level": "WARNING"})
        try:
            res = svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})

            assert res["success"] is True
            assert process_observability_layers(svc).recipe == {"log_level": "WARNING"}
        finally:
            logger.shutdown()

    def test_broken_companion_is_a_loud_refusal_not_a_silent_empty_layer(self, tmp_path, recipe) -> None:
        companion_path(recipe).write_text("observability: [не словарь, а список\n", encoding="utf-8")
        svc, logger = self._svc(tmp_path, recipe, boot_delta={"log_level": "WARNING"})
        try:
            res = svc.command_manager.handlers["config.reload"]({"observability_recipe_reload": True})

            assert res["success"] is False
            assert "не перечитан" in res["reason"]
            # Слой не тронут: полуприменённое состояние хуже отказа.
            assert process_observability_layers(svc).recipe == {"log_level": "WARNING"}
        finally:
            logger.shutdown()


class _SvcRW(_Svc):
    """Сервис, умеющий ПИСАТЬ конфиг — switch-ветка адрес и базу записывает."""

    def update_config(self, key, value) -> None:
        self._config[key] = value

    def _log_error(self, msg, **kw):
        self.log_calls.append(("ERROR", msg, kw))


class TestSwitchReadsCompanionOfTheNewRecipe:
    """Резидуал 5.11-R2: switch обязан собрать слой ИЗ ОБОИХ источников.

    До фикса переживший switch процесс получал только дельту нового рецепта, а
    спутник этого рецепта видел лишь после рестарта. То есть два процесса одного
    конвейера — переживший и пересозданный — читали одну и ту же пару файлов
    по-разному, пока кто-нибудь не перезапустится. Инвариант плана прямо это
    запрещает: «boot ≡ reload», одна функция на оба пути.
    """

    @staticmethod
    def _wire(tmp_path, recipe_name: str, section, companion_section=None):
        recipe = tmp_path / recipe_name
        recipe.write_text(_RECIPE_TEXT, encoding="utf-8")
        if companion_section is not None:
            write_companion(recipe, companion_section)
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="switch", log_directory=str(tmp_path), enable_batching=False)
        )
        svc = _SvcRW(logger, config={RECIPE_PATH_CONFIG_KEY: str(tmp_path / "old.yaml")})
        BuiltinCommands(svc)._register_observability_commands()
        return svc, svc.command_manager.handlers, recipe, logger, section

    def test_companion_of_the_new_recipe_is_applied_on_switch(self, tmp_path) -> None:
        """Пара: ключ есть только в спутнике нового рецепта → после switch он действует."""
        svc, handlers, recipe, logger, section = self._wire(
            tmp_path,
            "new.yaml",
            {"processes": {"seg": {"log_level": "WARNING"}}},
            companion_section={"processes": {"seg": {"log_level": "DEBUG"}}},
        )
        try:
            handlers["config.reload"]({"observability_recipe": section, "observability_recipe_path": str(recipe)})
            layers = process_observability_layers(svc)
            assert layers.recipe.get("log_level") == "DEBUG", (
                f"спутник нового рецепта не применён на switch: {layers.recipe}"
            )
            assert layers.recipe_source == str(companion_path(recipe)), (
                f"источник слоя обязан называть спутник: {layers.recipe_source}"
            )
        finally:
            logger.shutdown()

    def test_without_companion_switch_behaves_as_before(self, tmp_path) -> None:
        """Спутника нет → слой ровно из дельты рецепта, источник — сам рецепт."""
        svc, handlers, recipe, logger, section = self._wire(
            tmp_path, "plain.yaml", {"processes": {"seg": {"log_level": "WARNING"}}}
        )
        try:
            handlers["config.reload"]({"observability_recipe": section, "observability_recipe_path": str(recipe)})
            layers = process_observability_layers(svc)
            assert layers.recipe.get("log_level") == "WARNING"
            assert layers.recipe_source == str(recipe)
        finally:
            logger.shutdown()

    def test_companion_of_the_ABANDONED_recipe_does_not_leak(self, tmp_path) -> None:
        """Спутник ПОКИНУТОГО рецепта не имеет права въехать в новый слой.

        Соседняя развилка того же дефекта: собирать слой «из спутника» бесполезно,
        если адрес к моменту сборки ещё указывает на прежний рецепт.
        """
        old = tmp_path / "old.yaml"
        old.write_text(_RECIPE_TEXT, encoding="utf-8")
        write_companion(old, {"processes": {"seg": {"log_level": "ERROR"}}})

        svc, handlers, recipe, logger, section = self._wire(
            tmp_path, "fresh.yaml", {"processes": {"seg": {"log_level": "WARNING"}}}
        )
        try:
            handlers["config.reload"]({"observability_recipe": section, "observability_recipe_path": str(recipe)})
            layers = process_observability_layers(svc)
            assert layers.recipe.get("log_level") == "WARNING", (
                f"ключ спутника ПОКИНУТОГО рецепта воскрес: {layers.recipe}"
            )
        finally:
            logger.shutdown()

    def test_broken_companion_does_not_break_the_switch(self, tmp_path) -> None:
        """Битый спутник — громкая жалоба и слой без него, а не отказ switch'а."""
        svc, handlers, recipe, logger, section = self._wire(
            tmp_path, "broken.yaml", {"processes": {"seg": {"log_level": "WARNING"}}}
        )
        companion_path(recipe).write_text("{{{ не yaml", encoding="utf-8")
        try:
            res = handlers["config.reload"]({"observability_recipe": section, "observability_recipe_path": str(recipe)})
            assert res.get("success") is not False, f"switch отказал из-за спутника: {res}"
            assert any(lvl == "ERROR" for lvl, _m, _k in svc.log_calls), "битый спутник прошёл молча"
        finally:
            logger.shutdown()
