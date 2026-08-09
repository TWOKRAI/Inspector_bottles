# -*- coding: utf-8 -*-
"""Task 5.12 — резолвер слоёв наблюдаемости и provenance.

Проверяется СЛОЙ ИСТОЧНИКОВ, а не применение к менеджерам: резолв L1→L2→L3,
per-process форма рецепта, запись/сброс L3 и ответ «кто победил по этому ключу».
Применение (пересборка вместо дельты) — отдельными тестами reload-пути.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.configs.observability_config import (
    expand_observability,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    LAYER_FRAMEWORK,
    LAYER_RECIPE,
    LAYER_SESSION,
    ObservabilityLayers,
    flatten_section,
    process_observability_layers,
    read_process_config,
    resolve_recipe_section,
)


class TestResolveRecipeSection:
    """L2 рецепта: defaults всем, per-process поверх, сосед не задет."""

    def test_defaults_apply_to_every_process(self) -> None:
        section = {"defaults": {"log_level": "DEBUG"}}
        assert resolve_recipe_section(section, "camera_0") == {"log_level": "DEBUG"}
        assert resolve_recipe_section(section, "renderer") == {"log_level": "DEBUG"}

    def test_per_process_beats_defaults_and_leaves_neighbour_alone(self) -> None:
        section = {
            "defaults": {"log_level": "INFO", "console": True},
            "processes": {"camera_0": {"log_level": "DEBUG"}},
        }
        assert resolve_recipe_section(section, "camera_0") == {"log_level": "DEBUG", "console": True}
        # Пара: правка camera_0 не протекла в соседа.
        assert resolve_recipe_section(section, "renderer") == {"log_level": "INFO", "console": True}

    def test_short_form_without_defaults_is_treated_as_defaults(self) -> None:
        assert resolve_recipe_section({"log_level": "WARNING"}, "any") == {"log_level": "WARNING"}

    def test_empty_and_garbage_sections_give_empty_delta(self) -> None:
        assert resolve_recipe_section(None, "x") == {}
        assert resolve_recipe_section({}, "x") == {}
        assert resolve_recipe_section({"defaults": "не-словарь"}, "x") == {}


class TestResolveLayers:
    """L1 → L2 → L3: каждый следующий побеждает, отсутствие = наследование."""

    def test_session_beats_recipe_beats_app(self) -> None:
        layers = ObservabilityLayers(
            app={"log_level": "INFO", "enable_batching": True},
            recipe={"log_level": "WARNING"},
            session={"log_level": "DEBUG"},
        )
        resolved = layers.resolve()
        assert resolved["log_level"] == "DEBUG"
        # Ключ, которого нет выше, наследуется снизу.
        assert resolved["enable_batching"] is True

    def test_missing_key_inherits_from_below(self) -> None:
        layers = ObservabilityLayers(app={"log_level": "WARNING"}, recipe={"console": False})
        assert layers.resolve() == {"log_level": "WARNING", "console": False}

    def test_nested_sections_merge_per_key_not_wholesale(self) -> None:
        layers = ObservabilityLayers(
            app={"errors": {"level": "WARNING", "include_stacktrace": True}},
            recipe={"errors": {"level": "ERROR"}},
        )
        # include_stacktrace НЕ должен пропасть: слой заменяет ключ, а не ветку.
        assert layers.resolve()["errors"] == {"level": "ERROR", "include_stacktrace": True}

    def test_resolve_does_not_mutate_source_layers(self) -> None:
        app = {"errors": {"level": "WARNING"}}
        layers = ObservabilityLayers(app=app, recipe={"errors": {"level": "ERROR"}})
        layers.resolve()
        assert app == {"errors": {"level": "WARNING"}}


class TestSessionLayer:
    """L3 — точечная запись и сброс, который пишет ОТСУТСТВИЕ."""

    def test_session_set_creates_nested_path(self) -> None:
        layers = ObservabilityLayers()
        layers.session_set("channels.messages_file.enabled", False, origin="test")
        assert layers.session == {"channels": {"messages_file": {"enabled": False}}}

    def test_reset_removes_key_so_lower_layer_wins_again(self) -> None:
        layers = ObservabilityLayers(app={"log_level": "INFO"}, session={"log_level": "DEBUG"})
        assert layers.resolve()["log_level"] == "DEBUG"

        assert layers.session_reset("log_level", origin="test") is True

        # Ключ УДАЛЁН, а не переписан значением дефолта: меняем L1 —
        # действующее значение едет за ним. Присвоение «как было» дало бы INFO
        # навсегда и порвало связь с нижним слоем.
        assert layers.resolve()["log_level"] == "INFO"
        layers.app["log_level"] = "ERROR"
        assert layers.resolve()["log_level"] == "ERROR"

    def test_reset_prunes_emptied_branches(self) -> None:
        layers = ObservabilityLayers()
        layers.session_set("channels.messages_file.enabled", False, origin="test")
        assert layers.session_reset("channels.messages_file.enabled", origin="test") is True
        # Пустая ветка читалась бы как «каналом что-то управляется».
        assert layers.session == {}

    def test_reset_keeps_siblings(self) -> None:
        layers = ObservabilityLayers()
        layers.session_set("channels.a.enabled", False, origin="test")
        layers.session_set("channels.b.enabled", False, origin="test")
        layers.session_reset("channels.a.enabled", origin="test")
        assert layers.session == {"channels": {"b": {"enabled": False}}}

    def test_reset_of_absent_key_reports_false(self) -> None:
        layers = ObservabilityLayers()
        assert layers.session_reset("log_level", origin="test") is False
        assert layers.session_reset("channels.nope.enabled", origin="test") is False

    def test_session_keys_and_clear_report_what_was_held(self) -> None:
        layers = ObservabilityLayers()
        layers.session_set("log_level", "DEBUG", origin="test")
        layers.session_set("channels.messages_file.enabled", False, origin="test")
        assert layers.session_keys() == ("channels.messages_file.enabled", "log_level")

        dropped = layers.session_clear(origin="test")
        assert dropped == ("channels.messages_file.enabled", "log_level")
        assert layers.session == {}


class TestFlattenSection:
    def test_leaves_become_dotted_paths(self) -> None:
        assert flatten_section({"a": {"b": 1}, "c": 2}) == {"a.b": 1, "c": 2}

    def test_empty_dict_is_a_leaf(self) -> None:
        # «Слой задал пустую карту» ≠ «слой не сказал ничего».
        assert flatten_section({"loggers": {}}) == {"loggers": {}}


class TestProvenance:
    """У каждого действующего ключа назван слой-победитель."""

    def test_four_layers_each_own_their_key(self) -> None:
        layers = ObservabilityLayers(
            app={"enable_batching": False},
            recipe={"log_level": "WARNING"},
            session={"console": False},
            app_source="system.yaml",
            recipe_source="recipes/demo.yaml",
        )
        prov = layers.provenance()

        assert prov["enable_batching"] == {"layer": LAYER_APP, "source": "system.yaml"}
        assert prov["log_level"] == {"layer": LAYER_RECIPE, "source": "recipes/demo.yaml"}
        assert prov["console"] == {"layer": LAYER_SESSION, "source": LAYER_SESSION}
        # Никем не тронутый ключ — дефолт фреймворка.
        assert prov["file"] == {"layer": LAYER_FRAMEWORK, "source": LAYER_FRAMEWORK}

    def test_upper_layer_wins_provenance(self) -> None:
        layers = ObservabilityLayers(
            app={"log_level": "INFO"},
            recipe={"log_level": "WARNING"},
            session={"log_level": "DEBUG"},
        )
        assert layers.provenance()["log_level"]["layer"] == LAYER_SESSION

    def test_every_schema_key_is_explained(self) -> None:
        """Ключ без объяснения = «почему у меня INFO» без ответа."""
        prov = ObservabilityLayers().provenance()
        for key in ("log_level", "log_directory", "console", "file", "errors.level", "stats.enabled"):
            assert prov[key]["layer"] == LAYER_FRAMEWORK, key

    def test_materialized_channels_name_the_toggle_owner(self) -> None:
        """Имя канала рождается после expand — слой всё равно обязан назваться."""
        layers = ObservabilityLayers(app={"file": False}, app_source="system.yaml")
        expanded = expand_observability(layers.resolve())
        prov = layers.provenance(expanded["logger"])

        file_channels = [name for name, body in expanded["logger"]["channels"].items() if body.get("type") == "file"]
        assert file_channels, "ожидались файловые каналы в раскладке"
        for name in file_channels:
            assert prov[f"channels.{name}.enabled"] == {"layer": LAYER_APP, "source": "system.yaml"}

        console_channels = [
            name for name, body in expanded["logger"]["channels"].items() if body.get("type") == "console"
        ]
        for name in console_channels:
            # console никто не трогал — значение из дефолта фреймворка.
            assert prov[f"channels.{name}.enabled"]["layer"] == LAYER_FRAMEWORK

    def test_explicit_channel_override_beats_wholesale_toggle(self) -> None:
        layers = ObservabilityLayers(
            app={"file": False},
            session={"channels": {"messages_file": {"enabled": True}}},
        )
        expanded = expand_observability(layers.resolve())
        prov = layers.provenance(expanded["logger"])
        assert prov["channels.messages_file.enabled"]["layer"] == LAYER_SESSION

    def test_materialized_scopes_name_the_level_owner(self) -> None:
        layers = ObservabilityLayers(recipe={"loggers": {"шумный": {"level": "DEBUG"}}}, recipe_source="r.yaml")
        expanded = expand_observability(layers.resolve())
        prov = layers.provenance(expanded["logger"])
        assert prov["loggers.шумный.level"] == {"layer": LAYER_RECIPE, "source": "r.yaml"}


class TestExpandHonoursPartialOverrides:
    """Частичные channels/scopes едут ЧАСТИЧНЫМ словарём — их домерживает вызывающий."""

    def test_channel_override_does_not_wipe_other_channels(self) -> None:
        expanded = expand_observability({"channels": {"messages_file": {"enabled": False}}})
        assert expanded["logger"]["channels"] == {"messages_file": {"enabled": False}}

    def test_channel_override_merges_over_wholesale_toggle(self) -> None:
        expanded = expand_observability({"file": False, "channels": {"messages_file": {"enabled": True}}})
        channels = expanded["logger"]["channels"]
        # Тоггл раскрыл ВЕСЬ набор, адресная правка победила только у своего имени.
        assert len(channels) > 1
        assert channels["messages_file"]["enabled"] is True
        other_file = [n for n, b in channels.items() if b.get("type") == "file" and n != "messages_file"]
        assert other_file, "ожидался хотя бы ещё один файловый канал"
        assert all(channels[n]["enabled"] is False for n in other_file)

    def test_no_overrides_emit_no_keys(self) -> None:
        expanded = expand_observability({})
        assert "channels" not in expanded["logger"]
        assert "loggers" not in expanded["logger"]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])


class TestConfigReadSurvivesBothDeliveryShapes:
    """Живая находка 5.12: конфиг доезжает ДВУМЯ формами, и чтение обязано знать обе.

    Оркестратор получает ключи ПЛОСКО (spawner мержит orchestrator_config в корень),
    дочерний процесс — ВЕСЬ proc_dict (process_runner отдаёт custom['process_config']),
    и там те же ключи лежат под ``config.``. Тесты подавали только плоскую форму —
    то есть доказывали фейк: на живом ребёнке `observability.persist` ответил
    «путь к рецепту неизвестен», хотя ключ лежал в его proc_dict.
    """

    class _FlatSvc:
        def __init__(self, data):
            self._d = data

        def get_config(self, key, default=None):
            node = self._d
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def test_flat_shape_orchestrator(self) -> None:
        svc = self._FlatSvc({"observability_recipe_path": "recipes/demo.yaml"})
        assert read_process_config(svc, "observability_recipe_path") == "recipes/demo.yaml"

    def test_nested_shape_child_process(self) -> None:
        svc = self._FlatSvc(
            {
                "class": "m.Seg",
                "queues": {},
                "managers": {},
                "config": {"observability_recipe_path": "recipes/demo.yaml"},
            }
        )
        assert read_process_config(svc, "observability_recipe_path") == "recipes/demo.yaml"

    def test_missing_key_gives_the_default_in_both_shapes(self) -> None:
        assert read_process_config(self._FlatSvc({}), "nope", "d") == "d"
        assert read_process_config(self._FlatSvc({"config": {}}), "nope", "d") == "d"

    def test_layers_are_seeded_from_the_nested_shape(self) -> None:
        svc = self._FlatSvc(
            {
                "config": {
                    "observability_app": {"log_level": "WARNING"},
                    "observability_override": {"console": False},
                    "observability_recipe_path": "recipes/demo.yaml",
                }
            }
        )
        layers = process_observability_layers(svc)
        assert layers.app == {"log_level": "WARNING"}
        assert layers.recipe == {"console": False}
        assert layers.recipe_source == "recipes/demo.yaml"
