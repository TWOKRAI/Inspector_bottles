# -*- coding: utf-8 -*-
"""R6 — switch рецепта обязан довезти живым процессам НОВЫЙ слой L2.

Живой прогон 2026-07-29 (dualcam_synth → g1_perf_probe через `topology.apply`)
показал три расхождения, каждое воспроизведено на реальной системе:

* переживший switch **protected**-процесс (`devices`) продолжал крутить секцию
  ПРЕЖНЕГО рецепта (`WARNING`), а пересозданный сосед — секцию текущего
  (`ERROR`): соседи расходились в ответе на «что говорит активный рецепт»;
* `recipe_source` у ВСЕХ процессов оставался адресом покинутого рецепта;
* как следствие — `observability.persist` после switch создавал спутник рядом
  со СТАРЫМ рецептом (файл `r6_a.observability.yaml` на диске при активном
  `r6_b.yaml`): «сохранить» молча правило конвейер, с которого ушли, а на
  текущем не сохраняло ничего.

Тесты гоняют РЕАЛЬНЫЙ ``LoggerManager`` и реальный обработчик ``config.reload``:
проверка на фейках доказала бы фейки.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    OVERRIDE_CONFIG_KEY,
    RECIPE_PATH_CONFIG_KEY,
    process_observability_layers,
    read_process_config,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
)

#: Сырая секция рецепта — ИМЕННО сырая, с `defaults`. Долька процесса резолвится
#: у получателя тем же кодом, что и на boot; подай мы сюда готовую дольку, тест
#: доказывал бы, что запись в слой работает, а не что switch и старт трактуют
#: один файл одинаково.
RECIPE_A = {"defaults": {"log_level": "WARNING"}}
RECIPE_B = {"defaults": {"log_level": "ERROR"}}


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _Svc:
    """Процесс с живым логгером и настоящим ``update_config``.

    ``update_config`` не декорация: адрес рецепта после switch читают ассемблер
    и ``observability.persist`` — оба через конфиг. Стаб без него молча съел бы
    запись адреса, и тест на persist остался бы зелёным при мёртвой правке.
    """

    def __init__(self, logger: LoggerManager, config: Dict[str, Any] | None = None) -> None:
        self.command_manager = _Cm()
        self.name = "seg"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self._config = dict(config or {})

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def update_config(self, key, value):
        self._config[key] = value

    def _log_debug(self, msg, **kw): ...

    def _log_info(self, msg, **kw): ...


@pytest.fixture
def child(tmp_path):
    """Процесс, поднятый на рецепте A: его L2 = долька, которую дал ассемблер."""
    logger = LoggerManager(
        config=LoggerManagerConfig(
            app_name="recipe_switch",
            log_directory=str(tmp_path),
            enable_batching=False,
        )
    )
    svc = _Svc(
        logger,
        {
            APP_CONFIG_KEY: {"log_level": "INFO"},
            OVERRIDE_CONFIG_KEY: {"log_level": "WARNING"},
            RECIPE_PATH_CONFIG_KEY: str(tmp_path / "recipe_a.yaml"),
        },
    )
    BuiltinCommands(svc)._register_observability_commands()
    handlers = svc.command_manager.handlers
    # «До» — состояние, в котором процесс живёт под рецептом A.
    handlers["config.reload"]({"observability": {}})
    assert _level(svc) == "WARNING"
    try:
        yield svc, handlers, tmp_path
    finally:
        logger.shutdown()


def _level(svc) -> str:
    return observability_effective(logger=svc.logger_manager)["logger"]["default_level"]


class TestSurvivorMovesToTheNewRecipe:
    """Пара «до/после»: под рецептом A — WARNING, после раздачи B — ERROR."""

    def test_new_section_replaces_the_previous_recipe_layer(self, child) -> None:
        svc, handlers, tmp_path = child

        res = handlers["config.reload"](
            {
                "observability_recipe": RECIPE_B,
                "observability_recipe_path": str(tmp_path / "recipe_b.yaml"),
            }
        )

        assert res["success"] is True
        assert res["recipe_layer"] == ["log_level"]
        assert _level(svc) == "ERROR", "переживший switch остался на секции покинутого рецепта"

    def test_silent_new_recipe_removes_the_previous_layer(self, child) -> None:
        """`{}` — не «нечего делать», а «новый рецепт про наблюдаемость молчит».

        Пропусти мы пустую секцию — покинутый рецепт продолжал бы действовать
        вечно, и это худший из исходов: значение есть, источника у него нет.
        """
        svc, handlers, tmp_path = child

        res = handlers["config.reload"](
            {"observability_recipe": {}, "observability_recipe_path": str(tmp_path / "recipe_b.yaml")}
        )

        assert res["success"] is True
        assert res["recipe_layer"] == []
        # Победитель — слой приложения (L1), а не остаток рецепта A.
        assert _level(svc) == "INFO"
        assert process_observability_layers(svc).recipe == {}

    def test_ordinary_reload_does_not_touch_the_recipe_layer(self, child) -> None:
        """Граница: обычный reload про L2 молчит и не имеет права его снимать."""
        svc, handlers, _ = child

        handlers["config.reload"]({"observability": {}})

        assert _level(svc) == "WARNING"
        assert process_observability_layers(svc).recipe == {"log_level": "WARNING"}


class TestAddressFollowsTheSwitch:
    """Адрес рецепта — отдельный факт от содержимого слоя, и его читает persist."""

    def test_delivery_updates_the_address_read_by_persist(self, child) -> None:
        svc, handlers, tmp_path = child
        new_recipe = tmp_path / "recipe_b.yaml"

        handlers["config.reload"]({"observability_recipe": RECIPE_B, "observability_recipe_path": str(new_recipe)})

        assert read_process_config(svc, RECIPE_PATH_CONFIG_KEY) == str(new_recipe)

    def test_persist_after_switch_writes_next_to_the_new_recipe(self, child) -> None:
        """Главная пара находки: спутник обязан лечь рядом с ДЕЙСТВУЮЩИМ рецептом.

        Живьём было наоборот — файл появлялся рядом с покинутым, то есть правка
        уходила в конвейер, которым уже никто не пользуется.
        """
        svc, handlers, tmp_path = child
        new_recipe = tmp_path / "recipe_b.yaml"
        new_recipe.write_text("name: b\n", encoding="utf-8")

        handlers["config.reload"]({"observability_recipe": RECIPE_B, "observability_recipe_path": str(new_recipe)})
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        res = handlers["observability.persist"]({})

        assert res["success"] is True
        assert "recipe_b" in res["path"], f"спутник лёг не туда: {res['path']}"
        assert not list(tmp_path.glob("recipe_a.observability.yaml")), "правка ушла в покинутый рецепт"


class TestMechanismHazards:
    """Опасности самой конструкции — то, что видно только автору механизма."""

    def test_operator_handle_survives_the_new_recipe(self, child) -> None:
        """Раздача L2 не имеет права быть побочным сбросом L3.

        Сброс сессии на switch делает ОТДЕЛЬНЫЙ флаг, и он приходит своим
        сообщением. Смешай их — и «поменяли рецепт» начало бы втихаря снимать
        ручки в сценариях, где рецепт меняют без switch (persist, watcher).
        """
        svc, handlers, tmp_path = child
        handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        assert _level(svc) == "DEBUG"

        handlers["config.reload"](
            {"observability_recipe": RECIPE_B, "observability_recipe_path": str(tmp_path / "b.yaml")}
        )

        # L3 победил L2 — ручка оператора на месте, слой под ней сменился.
        assert _level(svc) == "DEBUG"
        assert process_observability_layers(svc).recipe == {"log_level": "ERROR"}

    def test_address_without_section_still_moves_the_address(self, child) -> None:
        """Адрес и содержимое приезжают вместе, но приходят из разных источников.

        Ретаргет резолвит путь (в т.ч. из манифеста), секция берётся из
        топологии. Отсутствие одного не должно отменять другое — иначе switch
        без секции оставил бы persist целиться в покинутый файл.
        """
        svc, handlers, tmp_path = child
        new_recipe = tmp_path / "recipe_b.yaml"

        res = handlers["config.reload"]({"observability_recipe_path": str(new_recipe)})

        assert res["success"] is True
        assert read_process_config(svc, RECIPE_PATH_CONFIG_KEY) == str(new_recipe)
        # Ревью R6, находка 1: прежняя редакция звала `resolve_recipe_section(None)`
        # → `{}` и СНОСИЛА содержимое слоя. Тест этого не видел, потому что
        # проверял только адрес: «рецепт переехал» молча означало «рецепт опустел»
        # (живьём WARNING → INFO без единой команды об уровне).
        assert _level(svc) == "WARNING"
        assert process_observability_layers(svc).recipe == {"log_level": "WARNING"}

    def test_layer_change_is_recorded_in_the_audit(self, child) -> None:
        """Смена рецепта — такая же смена наблюдаемости, как команда (5.9)."""
        svc, handlers, tmp_path = child

        handlers["config.reload"](
            {"observability_recipe": RECIPE_B, "observability_recipe_path": str(tmp_path / "b.yaml")}
        )

        entries = process_observability_layers(svc).audit.entries(action="layer")
        assert entries, "смена слоя рецепта не оставила следа в аудите"
        assert entries[-1]["origin"].startswith("switch:")
        assert entries[-1]["keys"] == ["log_level"]


class TestSwitchMovesTheBaseNotOnlyTheAddress:
    """Находка 1 ревью 5.11: вместе с адресом обязана переехать БАЗА слоя.

    ``OVERRIDE_CONFIG_KEY`` — долька рецепта, принадлежащая ЭТОМУ процессу, и
    именно её берёт `compose_recipe_layer`, когда слой пересобирают с диска (R4).
    Пока switch правил только адрес, база оставалась долькой ПОКИНУТОГО рецепта —
    и первая же правка спутника нового воскрешала ключи старого. Путь стал
    достижим только в 5.11: до раздачи из watcher'а перечитывать было некому.
    """

    def test_survivor_does_not_resurrect_the_abandoned_recipe_on_refresh(self, child) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            write_companion,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )

        svc, handlers, tmp_path = child
        recipe_b = tmp_path / "recipe_b.yaml"
        recipe_b.write_text("name: b\n", encoding="utf-8")

        # Switch на рецепт B, который про наблюдаемость МОЛЧИТ: слой обязан сняться.
        handlers["config.reload"](
            {
                "observability_recipe": {},
                "observability_recipe_path": str(recipe_b),
                "observability_session_clear": True,
            }
        )
        layers = process_observability_layers(svc)
        assert layers.recipe == {}

        # Оператор правит спутник ДЕЙСТВУЮЩЕГО рецепта; watcher шлёт «перечитай».
        write_companion(recipe_b, {"processes": {"seg": {"enable_batching": False}}})
        handlers["config.reload"]({"observability_recipe_reload": True})

        # До правки здесь всплывал `log_level: WARNING` — из рецепта A, с которого ушли.
        assert layers.recipe == {"enable_batching": False}

    def test_switch_writes_the_new_slice_into_the_config(self, child) -> None:
        """Инвариант прямо: ключ описывает ДЕЙСТВУЮЩУЮ дольку, всегда."""
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            OVERRIDE_CONFIG_KEY as _KEY,
        )

        svc, handlers, tmp_path = child

        handlers["config.reload"](
            {
                "observability_recipe": RECIPE_B,
                "observability_recipe_path": str(tmp_path / "recipe_b.yaml"),
            }
        )

        assert svc.get_config(_KEY) == {"log_level": "ERROR"}

    def test_companion_never_leaks_into_the_base(self, child) -> None:
        """Спутник в базу не пишется: иначе снятый из него ключ не исчез бы никогда."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            write_companion,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            OVERRIDE_CONFIG_KEY as _KEY,
            process_observability_layers,
        )

        svc, handlers, tmp_path = child
        recipe_b = tmp_path / "recipe_b.yaml"
        recipe_b.write_text("name: b\n", encoding="utf-8")
        handlers["config.reload"]({"observability_recipe": {}, "observability_recipe_path": str(recipe_b)})

        write_companion(recipe_b, {"processes": {"seg": {"log_level": "DEBUG"}}})
        handlers["config.reload"]({"observability_recipe_reload": True})
        assert svc.get_config(_KEY) == {}  # база чиста — в ней только рецепт

        write_companion(recipe_b, {"processes": {"seg": {}}})  # оператор убрал ключ
        handlers["config.reload"]({"observability_recipe_reload": True})

        assert process_observability_layers(svc).recipe == {}
