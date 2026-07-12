"""Тесты SystemBlueprint.infer_missing_inspectors() — join/inspector из wires (Ф4.7).

Заменяет снятый костыль ``_hoist_inspector_from_metadata``
(``multiprocess_prototype/backend/launch.py``): раньше корректность join зависела от
того, куда GUI-save положил ``inspector`` (прямой ключ vs ``metadata`` — домен-entity
``Process`` не имеет типизир. поля ``inspector`` → сворачивает его в ``metadata`` при
сохранении). Теперь join — СТРУКТУРНЫЙ факт графа ``wires``: процесс, получающий
REQUIRED-порт(ы) от ≥2 разных процессов-источников, получает
``{mode: join, inputs, primary}`` автоматически — независимо от того, есть ли вообще
explicit-декларация и куда она попала.

Плагины ниже — упрощённые двойники реальных плагинов из ``hikvision_letter_robot.yaml``
(``circle_detector``/``line_filter``/``overlay_draw``/``center_crop``/``word_layout``),
воспроизводящие ТОЧНУЮ форму портов живых узлов ``draw``/``recog``/``layout``:

- ``draw`` (overlay_draw): frame + overlay — оба REQUIRED, имена source- и target-порта
  совпадают → join, inputs=[frame, overlay].
- ``recog`` (center_crop): frame + trigger_in — оба REQUIRED, но target-порт
  ``trigger_in`` называется иначе, чем source-порт ``line_filter.overlay`` → тег входа
  берётся из SOURCE-порта ("overlay"), НЕ из target ("trigger_in").
- ``layout`` (word_layout): 2 источника, но только ``predictions`` REQUIRED — остальные
  входы optional → join НЕ выводится (regression guard: 2 источника — необходимое, но
  недостаточное условие).
"""

from __future__ import annotations

import pytest

from ...process_manager_module.topology.blueprint import SystemBlueprint
from ..plugins.base import ProcessModulePlugin
from ..plugins.port import Port
from ..plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    """Изолировать глобальный PluginRegistry вокруг теста — snapshot/restore, не ``clear()``.

    ``clear()``-to-empty (паттерн test_blueprint_chain_validation.py) безопасен только
    пока ничего в СЕССИИ не полагается на ранее накопленную реальную discovery ``Plugins/
    *`` — в combined-прогонах (``pytest multiprocess_prototype``) это не так:
    ``PluginRegistry.discover()`` не переисполняет ``@register_plugin`` для уже
    импортированного модуля (кеш ``sys.modules``), поэтому once-cleared реестр не
    самовосстанавливается. Snapshot/restore не оставляет такого следа независимо от
    порядка сборки тестов.
    """
    snapshot = dict(PluginRegistry._plugins)
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry._plugins.update(snapshot)


class _CircleDetector(ProcessModulePlugin):
    """Источник frame+detections одним item (двойник vision.circle_detector)."""

    name = "circle_detector"
    category = "processing"
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="detections", dtype="list[dict]", shape="N"),
    ]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _LineFilter(ProcessModulePlugin):
    """Источник overlay-item (двойник line.line_filter)."""

    name = "line_filter"
    category = "processing"
    outputs = [Port(name="overlay", dtype="dict", shape="-")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _OverlayDraw(ProcessModulePlugin):
    """draw-подобный join: frame+overlay REQUIRED, имена source==target (двойник overlay_draw)."""

    name = "overlay_draw"
    category = "rendering"
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="overlay", dtype="dict", shape="-"),
    ]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _CenterCrop(ProcessModulePlugin):
    """recog-подобный join: frame+trigger_in REQUIRED, target-имя ≠ source-имя (двойник center_crop)."""

    name = "center_crop"
    category = "processing"
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="trigger_in", dtype="dict", shape="-"),
    ]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(side, side, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _WordLayout(ProcessModulePlugin):
    """layout-подобный: 1 REQUIRED (predictions) + optional-входы (двойник word_layout)."""

    name = "word_layout"
    category = "processing"
    inputs = [
        Port(name="predictions", dtype="list[dict]", shape="N"),
        Port(name="word", dtype="any", optional=True),
        Port(name="return_trigger", dtype="any", optional=True),
    ]
    outputs = []

    def configure(self, ctx): ...
    def start(self, ctx): ...


def _register(*classes: type[ProcessModulePlugin]) -> None:
    for cls in classes:
        PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)


def _plugin(name: str) -> dict:
    return {"plugin_name": name, "plugin_class": ""}


# ---------------------------------------------------------------------------
# draw-сценарий: 2 REQUIRED-источника, имена source==target → join
# ---------------------------------------------------------------------------


def test_join_inferred_from_two_required_sources():
    """draw: vision(frame,detections) + line(overlay) → mode=join, inputs=[frame, overlay]."""
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "draw_join",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {"process_name": "draw", "plugins": [_plugin("overlay_draw")]},
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "vision.circle_detector.detections", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.inspector == {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}


def test_join_not_degraded_to_fanin_when_no_inspector_declared_anywhere():
    """Регресс-тест (acceptance Ф4.7): join не деградирует в fanin без ЛЮБОЙ inspector-декларации."""
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "draw_join_no_decl",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {"process_name": "draw", "plugins": [_plugin("overlay_draw")]},
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.inspector.get("mode") == "join", draw.inspector
    assert draw.inspector.get("mode") != "fanin"


# ---------------------------------------------------------------------------
# recog-сценарий: тег входа берётся из SOURCE-порта, не из target-порта
# ---------------------------------------------------------------------------


def test_tag_derived_from_source_port_not_target_port_name():
    """recog: line.line_filter.overlay -> recog.center_crop.trigger_in — тег "overlay", не "trigger_in"."""
    _register(_CircleDetector, _LineFilter, _CenterCrop)
    bp = SystemBlueprint.model_validate(
        {
            "name": "recog_join",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {"process_name": "recog", "plugins": [_plugin("center_crop")]},
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "recog.center_crop.frame"},
                {"source": "line.line_filter.overlay", "target": "recog.center_crop.trigger_in"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    recog = next(p for p in bp.processes if p.process_name == "recog")
    assert recog.inspector == {"mode": "join", "inputs": ["frame", "overlay"], "primary": "frame"}


# ---------------------------------------------------------------------------
# layout-сценарий: 2 источника, но НЕ join (optional-входы не считаются)
# ---------------------------------------------------------------------------


def test_optional_ports_excluded_no_false_positive_join():
    """layout: recog(predictions, required) + phone(word/return_trigger, optional) → остаётся fanin."""
    _register(_CircleDetector, _CenterCrop, _WordLayout)
    bp = SystemBlueprint.model_validate(
        {
            "name": "layout_no_join",
            "processes": [
                {"process_name": "recog", "plugins": [_plugin("center_crop")]},
                {"process_name": "phone", "plugins": []},
                {"process_name": "layout", "plugins": [_plugin("word_layout")]},
            ],
            "wires": [
                {"source": "recog.center_crop.frame", "target": "layout.word_layout.predictions"},
                {"source": "phone.phone_camera.word", "target": "layout.word_layout.word"},
                {
                    "source": "phone.phone_camera.return_trigger",
                    "target": "layout.word_layout.return_trigger",
                },
            ],
        }
    )
    bp.infer_missing_inspectors()

    layout = next(p for p in bp.processes if p.process_name == "layout")
    assert layout.inspector == {}


def test_single_required_source_stays_fanin():
    """Один источник — join не нужен (fanin остаётся дефолтом)."""
    _register(_CircleDetector, _CenterCrop)
    bp = SystemBlueprint.model_validate(
        {
            "name": "single_source",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "recog", "plugins": [_plugin("center_crop")]},
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "recog.center_crop.frame"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    recog = next(p for p in bp.processes if p.process_name == "recog")
    assert recog.inspector == {}


# ---------------------------------------------------------------------------
# Явный inspector — приоритет, вывод из wires НЕ применяется
# ---------------------------------------------------------------------------


def test_explicit_direct_inspector_not_overridden():
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "explicit_direct",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {
                    "process_name": "draw",
                    "plugins": [_plugin("overlay_draw")],
                    "inspector": {"mode": "fanin"},
                },
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.inspector == {"mode": "fanin"}


def test_explicit_extras_inspector_not_overridden():
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "explicit_extras",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {
                    "process_name": "draw",
                    "plugins": [_plugin("overlay_draw")],
                    "extras": {"inspector": {"mode": "fanin"}},
                },
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.inspector == {}  # typed-поле пустое; extras не трогаем — приоритет explicit


# ---------------------------------------------------------------------------
# Legacy metadata.inspector — тонкая настройка подмешивается, mode/inputs/primary из wires
# ---------------------------------------------------------------------------


def test_legacy_metadata_tuning_merged_over_wire_skeleton():
    """timeout_sec из metadata.inspector сохраняется; mode/inputs/primary — из wires
    (даже если в metadata записан устаревший/иной mode — wires авторитетны)."""
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "legacy_tuning",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {
                    "process_name": "draw",
                    "plugins": [_plugin("overlay_draw")],
                    "metadata": {
                        "inspector": {
                            "mode": "join",
                            "inputs": ["frame", "overlay"],
                            "primary": "frame",
                            "timeout_sec": 0.25,
                        }
                    },
                },
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()

    draw = next(p for p in bp.processes if p.process_name == "draw")
    assert draw.inspector == {
        "mode": "join",
        "inputs": ["frame", "overlay"],
        "primary": "frame",
        "timeout_sec": 0.25,
    }


def test_metadata_field_no_longer_dropped_by_extra_ignore():
    """metadata раньше молча терялась (extra=ignore до model_validate) — теперь typed-поле."""
    cfg = SystemBlueprint.model_validate(
        {
            "name": "metadata_roundtrip",
            "processes": [{"process_name": "p", "plugins": [], "metadata": {"inspector": {"mode": "join"}}}],
            "wires": [],
        }
    )
    proc = cfg.processes[0]
    assert proc.metadata == {"inspector": {"mode": "join"}}


# ---------------------------------------------------------------------------
# Идемпотентность
# ---------------------------------------------------------------------------


def test_infer_missing_inspectors_idempotent():
    _register(_CircleDetector, _LineFilter, _OverlayDraw)
    bp = SystemBlueprint.model_validate(
        {
            "name": "idempotent",
            "processes": [
                {"process_name": "vision", "plugins": [_plugin("circle_detector")]},
                {"process_name": "line", "plugins": [_plugin("line_filter")]},
                {"process_name": "draw", "plugins": [_plugin("overlay_draw")]},
            ],
            "wires": [
                {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
                {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
            ],
        }
    )
    bp.infer_missing_inspectors()
    first = next(p for p in bp.processes if p.process_name == "draw").inspector

    bp.infer_missing_inspectors()
    second = next(p for p in bp.processes if p.process_name == "draw").inspector

    assert first == second
