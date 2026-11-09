"""P3 word-layout: сторожа разработчика (Г1а, Г1б, Г4, Г6).

Зелёные по построению после правки; в приёмочные REDS (test_p3_disk_journal.py) не входят.
Ячейки слова «ПЕРЕМИРИЕ»: П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8. Ожидаемые значения — литералы.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.io.robot_io.plugin import RobotIoPlugin
from Plugins.processing.word_layout.assembler import WordAssembler
from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_RECIPE = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "recipes" / "letter_robot_sim.yaml"
_PICK = {"x_mm": 458.2, "y_mm": -343.0}
_WORD = "ПЕРЕМИРИЕ"


def _recipe_cfg(**over: object) -> dict:
    """Конфиг word_layout из рецепта letter_robot_sim.yaml; поверх — over."""

    def find(node: object) -> dict | None:
        if isinstance(node, dict):
            if node.get("process_name") == "layout":
                return node
            children = list(node.values())
        elif isinstance(node, list):
            children = node
        else:
            return None
        for child in children:
            found = find(child)
            if found is not None:
                return found
        return None

    proc = find(yaml.safe_load(_RECIPE.read_text(encoding="utf-8")))
    assert proc is not None
    plug = next(p for p in proc["plugins"] if p["plugin_name"] == "word_layout")
    conf = dict(plug["config"])
    conf.update({"target_word": _WORD, "word_source": ""})
    conf.update(over)
    return conf


def _layout(**over: object) -> tuple[WordLayoutPlugin, MockProcessServices]:
    conf = _recipe_cfg(**over)
    services = MockProcessServices(name="layout", config=conf)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services


def _robot_io() -> RobotIoPlugin:
    """RobotIoPlugin по образцу make_plugin из test_robot_io_plugin.py; start не зовём."""
    ctx = MagicMock()
    ctx.config = {"device_id": "robot_main", "forward_deque_maxlen": 64}
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    plugin = RobotIoPlugin()
    plugin.configure(ctx)
    return plugin


def _disc(label: str, tid: int, angle: float) -> dict:
    return {
        "predictions": [{"label": label, "confidence": 0.9, "angle_deg": angle, "angle_valid": True}],
        "sidecar": {"track_id": tid},
        "pick_xy": dict(_PICK),
    }


def _through_robot_io(layout: WordLayoutPlugin, io: RobotIoPlugin, item: dict) -> dict:
    """Диск → WordLayoutPlugin → RobotIoPlugin; вернуть payload, лёгший в очередь отправки."""
    out = layout.process([item])
    assert "robot_job" in out[0], "диск не взят: задания нет"
    before = len(io._deque)
    io.process(out)
    assert len(io._deque) == before + 1, "задание не легло в очередь robot_io"
    return io._deque[-1]


# --- Г1а: place_rz доходит до payload ---------------------------------------


def test_g1a_place_rz_in_robot_io_payload() -> None:
    layout, _ = _layout()
    io = _robot_io()
    payload = _through_robot_io(layout, io, _disc("Е", 1, 0.0))
    assert "place_rz" in payload
    assert payload == {
        "device_id": "robot_main",
        "x_mm": 458.2,
        "y_mm": -343.0,
        "z_mm": -132.0,
        "place_x": 320.0,
        "place_y": -330.0,
        "place_z": -132.0,
        "place_rz": 0.0,
    }


def test_g1a_place_rz_zero_with_angle_invert() -> None:
    layout, _ = _layout(angle_invert=True)
    payload = _through_robot_io(layout, _robot_io(), _disc("Е", 1, 0.0))
    assert payload["place_rz"] == 0.0


# --- Г1б: знак доворота из рецепта ------------------------------------------


def test_g1b_place_rz_sign_from_recipe() -> None:
    layout, _ = _layout()
    io = _robot_io()
    first = _through_robot_io(layout, io, _disc("Е", 1, 30.0))
    assert first["place_y"] == -330.0  # ячейка 1
    assert first["place_rz"] == -30.0
    second = _through_robot_io(layout, io, _disc("Е", 2, 330.0))
    assert second["place_y"] == -110.0  # ячейка 3
    assert second["place_rz"] == 30.0


# --- Г4: строка о смене геометрии посреди слова ------------------------------


def test_g4_geometry_change_midword_line_and_reset() -> None:
    layout, services = _layout()
    for tid, label in ((1, "П"), (2, "Е")):
        assert "robot_job" in layout.process([_disc(label, tid, 0.0)])[0]
    ok, err = layout._reg.update_field("first_y", -430.0)
    assert ok, err
    out = layout.process([_disc("Р", 3, 0.0)])[0]
    lines = [e["msg"] for e in services.logs if "геометрия ячеек изменена" in e["msg"]]
    assert lines == ["WordLayoutPlugin: геометрия ячеек изменена — ячейки с нуля (было заполнено 2/9)"]
    job = out["robot_job"]
    assert job["slot"] == 2
    assert job["place_y_mm"] == -210.0
    assert layout._reg.slots_filled == 1


# --- Г6: slots_of напрямую --------------------------------------------------


def test_g6_slots_of_independent_of_filling() -> None:
    asm = WordAssembler.from_word(_WORD, (0.0, 0.0), (0.0, 800.0))
    assert asm.slots_of("Е") == [1, 3, 8]
    for _ in range(3):
        assert asm.offer("Е", 0.0, True) is not None
    assert asm.filled_count == 3
    assert asm.slots_of("Е") == [1, 3, 8]
    assert asm.slots_of(" е ") == [1, 3, 8]
    assert asm.slots_of("А") == []
