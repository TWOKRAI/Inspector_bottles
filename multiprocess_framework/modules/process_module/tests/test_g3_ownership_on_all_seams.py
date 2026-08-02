# -*- coding: utf-8 -*-
"""Корзина 2.1: правило Г3 (`{}` = владение) держится на ВСЕХ швах, а не на одном.

Ревью корзины 2 нашло главный пробел: решение владельца Г3 («нет ключа или `null`
→ наследую; ключ есть, что бы в нём ни лежало → владею») было реализовано только в
`layer_merge` — то есть между слоями стека. Но «новее поверх старше» в этой системе
собирается ещё в пяти местах, и все пять остались на каноническом `deep_merge`, где
`{}` — пустое место:

  1. переезд L3 → L2 командой `observability.persist` (в памяти);
  2. запись дельты в спутник поверх уже сохранённого (`build_companion_section`);
  3. спутник поверх базы слоя при загрузке (`compose_over_base`);
  4. `defaults` → per-process внутри одной секции рецепта;
  5. inline-дельта `config.reload` в слой сессии;
  6. слои поверх загрузочной секции телеметрии — шов, которого в ревью НЕ БЫЛО;
     нашёлся сверкой всех call-site'ов канонического мержа. Там правило Г3 уже было
     объявлено в комментарии (различение `publish: null` ↔ «ключа нет», A-A1-1) —
     и исполнялось наполовину: `{}` уходил в ветку «слои промолчали».

Практическое следствие, воспроизведённое ревьюером: оператор владеет `scopes: {}`,
жмёт `persist` — команда отвечает **success**, а ключи рецепта ВОСКРЕСАЮТ. Ложный
сигнал плюс тихая потеря — ровно тот класс, ради которого затевалась фаза.

Плюс отдельная находка того же ревью: `layer_merge` не знал про
`OPAQUE_LAYER_PATHS`, хотя два других обхода дерева (`flatten_section`,
`_overlay_owner`) знают. Из-за этого resolve сливал непрозрачный лист по ключам, а
provenance называл владельцем листа целиком — прямое расхождение двух ответов об
одном ключе.

**Тесты идут через продакшн-вызовы, а не через `layer_merge` руками.** Первая
редакция этого файла звала примитив напрямую в трёх местах из шести — и была бы
зелёной при полностью несделанной работе: примитив-то уже правильный, дефект жил
у ВЫЗЫВАЮЩИХ. Поэтому швы 1-3 и 5 проверяются реальными обработчиками команд
(`config.reload`, `observability.persist`) поверх настоящего файла-спутника, шов 4
— через `resolve_recipe_section`, шов 6 — через `apply_telemetry_layers` с
перехватом того, что уехало получателю.

Тесты авторские (внутренняя механика слоёв), независимый tester не звался:
контракт наружу здесь не читается без кода.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_companion import (
    compose_over_base,
    load_companion,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    OVERRIDE_CONFIG_KEY,
    RECIPE_PATH_CONFIG_KEY,
    TELEMETRY_KEY,
    TELEMETRY_THROTTLE_PATH,
    ObservabilityLayers,
    layer_merge,
    process_observability_layers,
    resolve_recipe_section,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_telemetry_layers,
)

#: Ветка, которой оператор владеет пустотой. `scopes` выбран потому, что это
#: законная настройка «в этом рецепте адресных охватов нет», а не искусственный ключ.
SCOPES = {"SYSTEM": {"min_level": "DEBUG"}}

_RECIPE_TEXT = """# Рецепт человека — сюда машина не пишет.
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

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_debug(self, msg, **kw) -> None:
        pass

    def _log_info(self, msg, **kw) -> None:
        pass

    def _log_error(self, msg, **kw) -> None:
        pass


@pytest.fixture
def recipe(tmp_path):
    path = tmp_path / "demo.yaml"
    path.write_text(_RECIPE_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def wired(tmp_path, recipe):
    """Живой процесс с непустым слоем L2: рецепт объявил охваты, оператор их снимает."""
    logger = LoggerManager(
        config=LoggerManagerConfig(app_name="g3", log_directory=str(tmp_path), enable_batching=False)
    )
    svc = _Svc(
        logger,
        config={
            RECIPE_PATH_CONFIG_KEY: str(recipe),
            OVERRIDE_CONFIG_KEY: {"scopes": dict(SCOPES)},
        },
    )
    BuiltinCommands(svc)._register_observability_commands()
    try:
        yield svc, svc.command_manager.handlers, recipe
    finally:
        logger.shutdown()


class TestLayerMergeKnowsOpaquePaths:
    """Находка Ф-3: непрозрачный лист заменяется целиком, а не сливается по ключам."""

    def test_upper_layer_replaces_the_opaque_leaf(self) -> None:
        base = {"telemetry": {"throttle": {"processes.a.state.fps": 1.0}}}
        upper = {"telemetry": {"throttle": {"processes.b.state.fps": 2.0}}}
        merged = layer_merge(base, upper)
        assert merged["telemetry"]["throttle"] == {"processes.b.state.fps": 2.0}, (
            "лист слит по ключам — снятое оператором правило выжило"
        )

    def test_non_opaque_branch_still_merges_key_by_key(self) -> None:
        """Контроль: обычная ветка сливается как раньше — правило узкое, не тотальное."""
        merged = layer_merge({"channels": {"a": {"enabled": True}}}, {"channels": {"b": {"enabled": False}}})
        assert set(merged["channels"]) == {"a", "b"}

    def test_resolve_and_provenance_agree_on_the_opaque_leaf(self) -> None:
        """Два ответа об одном ключе не имеют права расходиться (ядро находки)."""
        layers = ObservabilityLayers(app={"telemetry": {"throttle": {"processes.a.state.fps": 1.0}}})
        layers.session_set(TELEMETRY_THROTTLE_PATH, {"processes.b.state.fps": 2.0}, 0, origin="op")
        resolved = layers.resolve()["telemetry"]["throttle"]
        owner = layers.provenance().get(TELEMETRY_THROTTLE_PATH)
        assert resolved == {"processes.b.state.fps": 2.0}, f"resolve слил лист по ключам: {resolved}"
        assert owner and owner["layer"] == "session", f"provenance назвал не того владельца: {owner}"


class TestOwnershipSurvivesPersist:
    """Швы 1-3: `observability.persist` — от памяти до файла и обратно."""

    def test_persist_does_not_change_the_effective_state(self, wired) -> None:
        """Обещание команды: «переезжает владелец, состояние не меняется». Шов 1.

        До фикса переезд L3→L2 звал `deep_merge(layers.recipe, session)`, и ключи
        рецепта воскресали ПРЯМО В ПАМЯТИ: `resolve()` до и после сохранения давал
        разное, а команда отвечала success.
        """
        svc, handlers, _recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {}}})
        layers = process_observability_layers(svc)
        before = layers.resolve()["scopes"]
        assert before == {}, "контроль: до persist владение действует"

        res = handlers["observability.persist"]({})
        assert res["success"] is True
        assert layers.resolve()["scopes"] == before, (
            f"persist изменил действующее состояние: было {before}, стало {layers.resolve()['scopes']}"
        )

    def test_ownership_survives_a_restart(self, wired) -> None:
        """Шов 3: перезагрузка «рецепт + спутник» даёт то же, что было до сохранения.

        Настоящий продакшн-вызов `compose_over_base(база, путь_рецепта, имя)` поверх
        файла, записанного настоящей командой.
        """
        svc, handlers, recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {}}})
        handlers["observability.persist"]({})

        body, source = compose_over_base({"scopes": dict(SCOPES)}, recipe, "seg")
        assert body["scopes"] == {}, f"после рестарта ветка рецепта воскресла: {body['scopes']}"
        assert source.endswith(".observability.yaml")

    def test_second_persist_does_not_resurrect_the_first(self, wired) -> None:
        """Шов 2: «поставил → сохранил → снял → сохранил» не возвращает первое.

        `build_companion_section` мержил дельту поверх уже записанного каноном, и
        снятие не доезжало до файла: спутник хранил ключи первого сохранения.
        """
        svc, handlers, recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {"BUSINESS": {"min_level": "INFO"}}}})
        handlers["observability.persist"]({})
        assert load_companion(recipe)["processes"]["seg"]["scopes"] == {"BUSINESS": {"min_level": "INFO"}}

        handlers["config.reload"]({"observability": {"scopes": {}}})
        handlers["observability.persist"]({})
        assert load_companion(recipe)["processes"]["seg"]["scopes"] == {}, (
            "в спутнике остались ключи прошлого сохранения — снятие не доехало до файла"
        )

    def test_neighbour_process_is_untouched(self, wired) -> None:
        """Контроль: владение пустотой у одного процесса не трогает соседа в том же файле."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            write_companion,
        )

        svc, handlers, recipe = wired
        write_companion(recipe, {"processes": {"other": {"scopes": dict(SCOPES)}}})
        handlers["config.reload"]({"observability": {"scopes": {}}})
        handlers["observability.persist"]({})

        section = load_companion(recipe)
        assert section["processes"]["other"]["scopes"] == SCOPES
        assert section["processes"]["seg"]["scopes"] == {}


class TestOwnershipInsideOneRecipeSection:
    """Шов 4: `defaults` → per-process. «Заглушить у одного процесса» обязано работать."""

    def test_per_process_empty_dict_beats_defaults(self) -> None:
        section = {"defaults": {"scopes": dict(SCOPES)}, "processes": {"p1": {"scopes": {}}}}
        assert resolve_recipe_section(section, "p1")["scopes"] == {}, "per-process владение потеряно"

    def test_other_processes_still_inherit_defaults(self) -> None:
        """Контроль: сосед, который молчит, наследует defaults как раньше."""
        section = {"defaults": {"scopes": dict(SCOPES)}, "processes": {"p1": {"scopes": {}}}}
        assert resolve_recipe_section(section, "p2")["scopes"] == SCOPES

    def test_per_process_partial_delta_still_merges(self) -> None:
        """Контроль: непустая per-process правка домерживается к defaults, а не заменяет их."""
        section = {
            "defaults": {"scopes": dict(SCOPES), "log_level": "WARNING"},
            "processes": {"p1": {"scopes": {"BUSINESS": {"min_level": "INFO"}}}},
        }
        resolved = resolve_recipe_section(section, "p1")
        assert set(resolved["scopes"]) == {"SYSTEM", "BUSINESS"}
        assert resolved["log_level"] == "WARNING"


class TestOwnershipOfTheInlineDelta:
    """Шов 5: inline-дельта `config.reload` в слой сессии."""

    def test_operator_can_take_back_his_own_edit(self, wired) -> None:
        """Снять то, что сам поставил минуту назад, — двумя командами подряд.

        До фикса вторая команда (`scopes: {}`) мержилась каноном в сессию и молча
        наследовала первую: оператор видел success и прежние охваты.
        """
        svc, handlers, _recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {"BUSINESS": {"min_level": "INFO"}}}})
        layers = process_observability_layers(svc)
        assert "BUSINESS" in layers.resolve()["scopes"]

        handlers["config.reload"]({"observability": {"scopes": {}}})
        assert layers.resolve()["scopes"] == {}, f"вторая правка не сняла первую: {layers.resolve()['scopes']}"

    def test_shadowed_key_loses_its_deadline_with_its_value(self, wired) -> None:
        """Побочный путь, открытый самим Г3: владение пустотой РОНЯЕТ листья сессии.

        Канонический мерж только добавлял, поэтому ключ не мог исчезнуть из L3 при
        мерже — и сроки за ним никто не убирал. С Г3 может: `{"scopes": {}}` сносит
        `scopes.DEBUG.enabled`, а его дедлайн оставался висеть в readback'е, обещая
        оператору возврат правки, которой уже нет («следствие без причины»).
        Найдено полным гейтом корзины 2.1, воспроизведено до фикса.
        """
        svc, handlers, _recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {"DEBUG": {"enabled": True}}}, "ttl": 600})
        layers = process_observability_layers(svc)
        assert layers.session_ttl_view() == {"scopes.DEBUG.enabled": 600.0}

        handlers["config.reload"]({"observability": {"scopes": {}}, "ttl": 10})
        assert "scopes.DEBUG.enabled" not in layers.session_ttl_view(), (
            f"срок пережил свой ключ: {layers.session_ttl_view()}"
        )
        assert layers.session_ttl_view() == {"scopes": 10.0}

    def test_shadowed_key_is_named_in_the_audit(self, wired) -> None:
        """Снятое той же командой обязано быть НАЗВАНО, а не исчезнуть молча.

        Иначе ручка оператора пропадает из действующей наблюдаемости, а журнал
        показывает только новые ключи — путь, меняющий состояние без следа
        (замечание 2 ревью 5.9, здесь тот же класс на новом пути).
        """
        svc, handlers, _recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {"DEBUG": {"enabled": True}}}, "ttl": 600})
        handlers["config.reload"]({"observability": {"scopes": {}}, "ttl": 10})

        layers = process_observability_layers(svc)
        touches = [e for e in layers.audit.entries() if e.get("action") == "touch"]
        assert touches, "правка не записана в аудит вовсе"
        assert touches[-1].get("removed") == ["scopes.DEBUG.enabled"], f"снятый ключ не назван в записи: {touches[-1]}"

    def test_partial_delta_still_accumulates(self, wired) -> None:
        """Контроль: непустые дельты по-прежнему НАКАПЛИВАЮТСЯ, а не заменяют друг друга."""
        svc, handlers, _recipe = wired
        handlers["config.reload"]({"observability": {"scopes": {"BUSINESS": {"min_level": "INFO"}}}})
        handlers["config.reload"]({"observability": {"log_level": "ERROR"}})
        layers = process_observability_layers(svc)
        assert "BUSINESS" in layers.resolve()["scopes"], "вторая правка снесла первую"
        assert layers.resolve()["log_level"] == "ERROR"


class _CaptureHeartbeat:
    """Ловит `reconfigure_telemetry(section, mode=...)` — что уехало получателю."""

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, Optional[str]]] = []

    def reconfigure_telemetry(self, section: Any, mode: Optional[str] = None) -> None:
        self.calls.append((section, mode))


def _publish_sent(hb: _CaptureHeartbeat) -> Any:
    assert hb.calls, "получатель не был вызван вовсе"
    return hb.calls[-1][0]


class TestOwnershipOverTelemetryBoot:
    """Шов 6 (не назван ревью): слои поверх загрузочной секции телеметрии."""

    BOOT = {"metrics": {"fps": {"interval_sec": 1.0}}}

    def _apply(self, layers: ObservabilityLayers, hb: _CaptureHeartbeat) -> None:
        apply_telemetry_layers(layers, heartbeat=hb, telemetry_boot={"publish": self.BOOT}, origin="test")

    def test_empty_publish_owns_and_does_not_revive_boot(self) -> None:
        """`publish: {}` = «считать нечего, и это моё решение», а не «слои промолчали»."""
        layers = ObservabilityLayers()
        layers.session[TELEMETRY_KEY] = {"publish": {}}
        hb = _CaptureHeartbeat()
        self._apply(layers, hb)
        assert _publish_sent(hb) == {}, f"загрузочный набор метрик ожил: {_publish_sent(hb)}"

    def test_empty_nested_branch_owns_too(self) -> None:
        """Вложенное `{"metrics": {}}` владеет по той же причине, что и верхнее."""
        layers = ObservabilityLayers()
        layers.session[TELEMETRY_KEY] = {"publish": {"metrics": {}}}
        hb = _CaptureHeartbeat()
        self._apply(layers, hb)
        assert _publish_sent(hb)["metrics"] == {}, f"метрика boot выжила: {_publish_sent(hb)}"

    def test_non_empty_publish_still_merges_over_boot(self) -> None:
        """Контроль: непустая правка по-прежнему ложится ПОВЕРХ boot, не заменяя его."""
        layers = ObservabilityLayers()
        layers.session[TELEMETRY_KEY] = {"publish": {"metrics": {"latency_ms": {"interval_sec": 0.2}}}}
        hb = _CaptureHeartbeat()
        self._apply(layers, hb)
        sent = _publish_sent(hb)
        assert sent["metrics"]["fps"]["interval_sec"] == 1.0, "метрика boot исчезла"
        assert sent["metrics"]["latency_ms"]["interval_sec"] == 0.2, "правка слоя не легла"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
