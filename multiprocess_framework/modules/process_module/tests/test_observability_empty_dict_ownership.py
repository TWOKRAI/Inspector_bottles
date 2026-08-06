# -*- coding: utf-8 -*-
"""A-A4-1 (ревью Ф5) + решение владельца Г3: ``{}`` в слое = ВЛАДЕНИЕ.

Дефект: ``flatten_section`` считал ``{"loggers": {}}`` листом (слой владеет), а
``deep_merge`` в ``resolve`` считал ``{}`` no-op (нижний побеждает). Итог: resolve
отдавал ``scopes`` из нижнего слоя, а provenance называл верхний — оператор правил
не тот файл.

Решение владельца (2026-08-02): **нет ключа или ``null`` → наследую; ключ есть,
что бы в нём ни лежало → владею.** ``{}`` = «здесь пусто, и это моё решение».
Применено в ОБОИХ местах одним примитивом: resolve через :func:`layer_merge`,
provenance через тот же обход (:meth:`ObservabilityLayers._provenance_leaves`).

Ключевая пара — не «resolve даёт X», а «resolve и provenance СОГЛАСНЫ»: раньше
починка одного лишь resolve создала бы НОВОЕ расхождение (provenance продолжал бы
приписывать затенённый ключ нижнему слою).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.configs.observability_config import (
    expand_observability,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    LAYER_RECIPE,
    ObservabilityLayers,
    layer_merge,
)


class TestEmptyDictOwnsInResolve:
    def test_upper_empty_dict_replaces_lower_branch(self) -> None:
        """``scopes: {}`` наверху ЗАМЕНЯЕТ ветку нижнего слоя на пустую (владение)."""
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}},
            recipe={"loggers": {}},
        )
        assert layers.resolve()["loggers"] == {}, "пустой словарь верхнего слоя не перекрыл нижний"

    def test_absent_key_still_inherits(self) -> None:
        """Контраст: ОТСУТСТВИЕ ключа (а не ``{}``) — по-прежнему наследование."""
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}},
            recipe={"log_level": "WARNING"},  # scopes НЕ упомянут
        )
        assert layers.resolve()["loggers"] == {"камера": {"level": "DEBUG"}}

    def test_non_empty_dict_still_merges_per_key(self) -> None:
        """Регресс-страж: непустой словарь мержится по-ключевому, а не заменяет ветку."""
        layers = ObservabilityLayers(
            app={"errors": {"level": "WARNING", "include_stacktrace": True}},
            recipe={"errors": {"level": "ERROR"}},
        )
        assert layers.resolve()["errors"] == {"level": "ERROR", "include_stacktrace": True}

    def test_layer_merge_primitive_directly(self) -> None:
        """Сам примитив: ``{}`` владеет, отсутствие наследует, непустой мержит."""
        base = {"a": {"x": 1}, "b": {"y": 2}, "c": 3}
        assert layer_merge(base, {"a": {}}) == {"a": {}, "b": {"y": 2}, "c": 3}
        assert layer_merge(base, {"b": {"z": 9}}) == {"a": {"x": 1}, "b": {"y": 2, "z": 9}, "c": 3}
        assert layer_merge(base, {}) == base  # весь слой пуст = молчит, наследует всё


class TestResolveAndProvenanceAgree:
    def test_provenance_names_the_owner_of_the_empty_branch(self) -> None:
        """Ветку, объявленную ``{}`` наверху, provenance отдаёт ВЕРХНЕМУ слою."""
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}},
            recipe={"loggers": {}},
            app_source="system.yaml",
            recipe_source="recipe.yaml",
        )
        assert layers.provenance()["loggers"] == {"layer": LAYER_RECIPE, "source": "recipe.yaml"}

    def test_shadowed_lower_key_is_not_attributed_to_lower_layer(self) -> None:
        """Затенённый ``{}``-ом ключ нижнего слоя provenance НЕ приписывает нижнему.

        Это ядро A-A4-1: resolve уронил ``loggers.камера.level`` из app, и
        provenance обязан назвать действующий источник (материализованный дефолт
        фреймворка), а не мёртвый app.
        """
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}},
            recipe={"loggers": {}},
            app_source="system.yaml",
            recipe_source="recipe.yaml",
        )
        expanded = expand_observability(layers.resolve())
        prov = layers.provenance(expanded["logger"])
        owner = prov.get("loggers.камера.level")
        assert owner is None or owner["layer"] != LAYER_APP, f"затенённый ключ всё ещё за app: {owner}"

    def test_resolve_and_provenance_do_not_contradict(self) -> None:
        """Инвариант: слой, названный provenance, действительно побеждает в resolve.

        Проверяем каждый ЯВНЫЙ ключ, а не только сценарный: любой ключ, чей слой
        provenance объявил app/recipe/session, должен присутствовать в сырой
        секции этого слоя и не быть затенён выше.
        """
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}, "log_level": "INFO"},
            recipe={"loggers": {}, "log_level": "WARNING"},
            session={"channels": {"messages_file": {"enabled": False}}},
        )
        resolved = layers.resolve()
        prov = layers.provenance()
        # scopes стал {} (recipe владеет) → в resolved нет ни одного scopes.* листа
        assert resolved["loggers"] == {}
        # provenance для scopes указывает recipe, и НЕ содержит app-претензии на SYSTEM
        assert prov["loggers"]["layer"] == LAYER_RECIPE
        assert "loggers.камера.level" not in prov
        # log_level: recipe перекрыл app
        assert resolved["log_level"] == "WARNING"
        assert prov["log_level"]["layer"] == LAYER_RECIPE


class TestUnchangedNonEmptyProvenance:
    def test_non_empty_scopes_keep_per_key_ownership(self) -> None:
        """Регресс: непустой ``scopes`` наверху не затеняет соседние ключи снизу."""
        layers = ObservabilityLayers(
            app={"loggers": {"камера": {"level": "DEBUG"}}},
            recipe={"loggers": {"гуй": {"level": "INFO"}}},
            app_source="system.yaml",
            recipe_source="recipe.yaml",
        )
        prov = layers.provenance()
        assert prov["loggers.камера.level"] == {"layer": LAYER_APP, "source": "system.yaml"}
        assert prov["loggers.гуй.level"] == {"layer": LAYER_RECIPE, "source": "recipe.yaml"}
        assert layers.resolve()["loggers"] == {
            "камера": {"level": "DEBUG"},
            "гуй": {"level": "INFO"},
        }


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
