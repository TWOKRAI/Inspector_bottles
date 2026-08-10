# -*- coding: utf-8 -*-
"""Легаси-ключ ``inspector`` читается как ``collector`` (D4, совместимость рецептов).

Переименование поля — единственная часть D4, которая ломает ДАННЫЕ, а не код:
записи ``inspector:`` живут в yaml-рецептах пользователя. Без алиаса они перестали
бы находиться **молча** (``extra=ignore`` выбрасывает неизвестный ключ, join не
активируется, симптом «линия не сольётся» к ключу не отсылает).

Каждое утверждение здесь названо поимённо, а не через суммарный признак: тест
«хотя бы где-то видно collector» пережил бы потерю любой отдельной дороги.

Дороги, по которым ключ доезжает до движка (все четыре проверяются):
  1. прямой typed-ключ ``ProcessConfig``;
  2. ``extras`` (domain-opaque мешок — его никто не канонизирует);
  3. ``metadata`` (легаси GUI-save путь, тонкая настройка поверх вывода из wires);
  4. ``GenericProcessConfig`` — proc_dict, собранный сборкой до D4.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    ProcessConfig,
    SystemBlueprint,
)
from multiprocess_framework.modules.process_module.generic.collector_registry import (
    COLLECTOR_CONFIG_KEY,
    LEGACY_COLLECTOR_CONFIG_KEY,
    collector_config,
)
from multiprocess_framework.modules.process_module.generic.generic_process_config import (
    GenericProcessConfig,
)
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

_JOIN = {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}


class TestKeyConstants:
    def test_canonical_and_legacy_are_the_expected_literals(self):
        """Константы — литералы, а не производные от кода, который они описывают."""
        assert COLLECTOR_CONFIG_KEY == "collector"
        assert LEGACY_COLLECTOR_CONFIG_KEY == "inspector"


class TestCollectorConfigReader:
    def test_canonical_key_read(self):
        assert collector_config({"collector": _JOIN}) == _JOIN

    def test_legacy_key_read(self):
        assert collector_config({"inspector": _JOIN}) == _JOIN

    def test_canonical_wins_when_both_present(self):
        """Иначе легаси-ключ молча перекрывал бы новый."""
        assert collector_config({"collector": _JOIN, "inspector": {"mode": "fanin"}}) == _JOIN

    def test_absent_section_is_empty_dict(self):
        assert collector_config({}) == {}
        assert collector_config({"collector": None}) == {}


class TestProcessConfigAlias:
    def test_legacy_key_lands_in_typed_field(self):
        """Рецепт до D4: ``inspector:`` поднимается в ``collector``, а не теряется."""
        cfg = ProcessConfig.model_validate({"process_name": "draw", "inspector": _JOIN, "plugins": []})
        assert cfg.collector == _JOIN

    def test_canonical_key_lands_in_typed_field(self):
        cfg = ProcessConfig.model_validate({"process_name": "draw", "collector": _JOIN, "plugins": []})
        assert cfg.collector == _JOIN

    def test_canonical_wins_when_both_keys_present(self):
        cfg = ProcessConfig.model_validate(
            {
                "process_name": "draw",
                "collector": _JOIN,
                "inspector": {"mode": "fanin"},
                "plugins": [],
            }
        )
        assert cfg.collector == _JOIN

    def test_legacy_key_marks_the_field_as_explicitly_set(self):
        """Легаси-ключ должен считаться ЗАДАННЫМ, а не совпасть с дефолтом.

        Первая редакция проверяла тут ``not hasattr(cfg, "inspector")`` — и была
        ВАКУУМНОЙ: ``extra=ignore`` выбрасывает неизвестный ключ сам, поэтому
        утверждение держалось и с полностью снятым алиасом (инъекция I-8 оставила
        его зелёным). ``model_fields_set`` различает «поле задано» и «поле пустое
        по умолчанию» — а на этом различии стоит приоритет typed-поля над
        ``extras`` в ``as_generic_config._pick``.
        """
        cfg = ProcessConfig.model_validate({"process_name": "draw", "inspector": _JOIN, "plugins": []})
        assert COLLECTOR_CONFIG_KEY in cfg.model_fields_set
        assert LEGACY_COLLECTOR_CONFIG_KEY not in cfg.model_fields_set
        assert not hasattr(cfg, LEGACY_COLLECTOR_CONFIG_KEY)

    def test_dump_writes_canonical_key_only(self):
        """Пересохранение рецепта канонизирует ключ — легаси не отращивается заново."""
        cfg = ProcessConfig.model_validate({"process_name": "draw", "inspector": _JOIN, "plugins": []})
        dumped = cfg.model_dump()
        assert dumped[COLLECTOR_CONFIG_KEY] == _JOIN
        assert LEGACY_COLLECTOR_CONFIG_KEY not in dumped

    def test_empty_legacy_value_does_not_shadow(self):
        """``inspector: {}`` не «задан» — не должен затирать/подменять канон."""
        cfg = ProcessConfig.model_validate({"process_name": "draw", "inspector": {}, "collector": _JOIN, "plugins": []})
        assert cfg.collector == _JOIN


class TestAsGenericConfigCarriesLegacyKey:
    def test_legacy_typed_key_reaches_generic_config(self):
        cfg = ProcessConfig.model_validate({"process_name": "draw", "inspector": _JOIN, "plugins": []})
        assert cfg.as_generic_config().collector == _JOIN

    def test_legacy_key_in_extras_reaches_generic_config(self):
        """``extras`` — domain-opaque мешок; before-валидатор его НЕ канонизирует."""
        cfg = ProcessConfig.model_validate({"process_name": "draw", "extras": {"inspector": _JOIN}, "plugins": []})
        assert cfg.as_generic_config().collector == _JOIN

    def test_canonical_key_in_extras_reaches_generic_config(self):
        cfg = ProcessConfig.model_validate({"process_name": "draw", "extras": {"collector": _JOIN}, "plugins": []})
        assert cfg.as_generic_config().collector == _JOIN


class TestGenericProcessConfigAlias:
    def test_proc_dict_from_older_build_is_accepted(self):
        """proc_dict пересекает границу процессов — старая форма обязана подниматься."""
        cfg = GenericProcessConfig.model_validate({"process_name": "draw", "inspector": _JOIN, "plugins": []})
        assert cfg.collector == _JOIN

    def test_canonical_wins_when_both_keys_present(self):
        cfg = GenericProcessConfig.model_validate(
            {
                "process_name": "draw",
                "collector": _JOIN,
                "inspector": {"mode": "fanin"},
                "plugins": [],
            }
        )
        assert cfg.collector == _JOIN


# ---------------------------------------------------------------------------
# Вывод join из wires требует РЕАЛЬНЫХ портов: без зарегистрированных плагинов
# у процесса нет REQUIRED-входов, и проверка шла бы по пустому месту — красная
# не потому, что механизм сломан. Двойники ниже повторяют форму узла ``draw``
# (overlay_draw: frame+overlay, оба REQUIRED) из test_blueprint_wire_collector.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore глобального PluginRegistry (не ``clear()`` в ноль — см. соседний файл)."""
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    _register(_Camera, _LineFilter, _OverlayDraw)
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


class _Camera(ProcessModulePlugin):
    name = "capture"
    category = "source"
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _LineFilter(ProcessModulePlugin):
    name = "line_filter"
    category = "processing"
    outputs = [Port(name="overlay", dtype="dict", shape="-")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _OverlayDraw(ProcessModulePlugin):
    name = "overlay_draw"
    category = "rendering"
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="overlay", dtype="dict", shape="-"),
    ]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


def _register(*classes: type[ProcessModulePlugin]) -> None:
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _draw_blueprint(**draw_fields) -> SystemBlueprint:
    """Два REQUIRED-источника на 'draw' → join выводится из wires."""
    return SystemBlueprint.model_validate(
        {
            "name": "bp",
            "processes": [
                {"process_name": "cam", "plugins": [{"plugin_name": "capture", "plugin_class": ""}]},
                {
                    "process_name": "flt",
                    "plugins": [{"plugin_name": "line_filter", "plugin_class": ""}],
                },
                {
                    "process_name": "draw",
                    "plugins": [{"plugin_name": "overlay_draw", "plugin_class": ""}],
                    **draw_fields,
                },
            ],
            "wires": [
                {"source": "cam.capture.frame", "target": "draw.overlay_draw.frame"},
                {"source": "flt.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )


def test_stand_infers_join_without_any_declaration():
    """Страж стенда: без него «зелено» ниже могло бы означать «join не выводится вовсе»."""
    bp = _draw_blueprint()
    bp.infer_missing_collectors()
    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.collector == {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}


class TestMetadataTuningAcceptsBothKeys:
    @pytest.mark.parametrize("key", [COLLECTOR_CONFIG_KEY, LEGACY_COLLECTOR_CONFIG_KEY])
    def test_tuning_from_metadata_merged_over_wire_skeleton(self, key):
        """Тонкая настройка из metadata доезжает под ОБОИМИ именами ключа."""
        bp = _draw_blueprint(metadata={key: {"timeout_sec": 7}})
        bp.infer_missing_collectors()
        draw = next(p for p in bp.processes if p.process_name == "draw")
        assert draw.collector["mode"] == "join", draw.collector
        assert draw.collector["timeout_sec"] == 7, f"tuning из metadata[{key!r}] потерян: {draw.collector!r}"


class TestExtrasShadowCleanupCoversBothKeys:
    @pytest.mark.parametrize("key", [COLLECTOR_CONFIG_KEY, LEGACY_COLLECTOR_CONFIG_KEY])
    def test_mode_less_shadow_removed_from_extras(self, key):
        """mode-less ключ в extras снимается под обоими именами.

        Оставленный shadow даёт ложный conflict-warning в ``as_generic_config._pick``
        — тихий шум, который потом читают как настоящий конфликт рецепта.
        """
        bp = _draw_blueprint(extras={key: {"timeout_sec": 5}})
        bp.infer_missing_collectors()
        draw = next(p for p in bp.processes if p.process_name == "draw")
        assert draw.collector["mode"] == "join"
        assert draw.collector["timeout_sec"] == 5
        assert key not in (draw.extras or {}), f"shadow-ключ {key!r} остался в extras"

    @pytest.mark.parametrize("key", [COLLECTOR_CONFIG_KEY, LEGACY_COLLECTOR_CONFIG_KEY])
    def test_explicit_mode_in_extras_is_escape_hatch_under_both_keys(self, key):
        """Секция С mode в extras — escape-hatch: вывод из wires НЕ применяется."""
        bp = _draw_blueprint(extras={key: {"mode": "fanin"}})
        bp.infer_missing_collectors()
        draw = next(p for p in bp.processes if p.process_name == "draw")
        assert draw.collector == {}, f"вывод перекрыл явный escape-hatch {key!r}"
        assert draw.as_generic_config().collector == {"mode": "fanin"}
