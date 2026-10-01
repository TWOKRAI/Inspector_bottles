"""Hazard-тест автора sim-lateral-offset (ревью ит.1): кривой `frame_down` в конфиге плагина.

Вынесен из `Services/line_sim/tests/test_lateral_offset_hazards.py`: тест импортирует
плагин, а слой Services не импортирует Plugins (правило слоёв, CLAUDE.md п.9).
"""

from unittest.mock import MagicMock

import pytest

from Plugins.sim.scene_source.plugin import SceneSourcePlugin

_BAD_FRAME_DOWN = [
    pytest.param((0.0, 0.0), id="zero-vector"),
    pytest.param((-78.4, 0.0), id="not-unit-mm-length"),
    pytest.param((float("nan"), 0.0), id="nan"),
    pytest.param((float("inf"), 0.0), id="inf"),
]


@pytest.mark.parametrize("ux_uy", _BAD_FRAME_DOWN)
def test_plugin_configure_rejects_bad_frame_down(ux_uy) -> None:
    """Что ломается: плагин собирал `BeltGeometry.from_dict` без проверки — кривой вектор при
    `lateral_offset_px > 0` стартовал бы, а истина робота молча врала. ValueError обязан вылететь
    из `configure`, не из `produce()`. Конфиг минимален: проверка геометрии идёт раньше сборки движка."""
    ux, uy = ux_uy
    ctx = MagicMock()
    ctx.config = {
        "resolution_width": 320,
        "resolution_height": 240,
        "px_per_mm": 8.163265,
        "belt_y_px": 120,
        "lateral_offset_px": [10.0, 20.0],
        "geometry": {"origin_x_mm": 458.2, "origin_y_mm": 0.0, "frame_down_ux": ux, "frame_down_uy": uy},
    }
    with pytest.raises(ValueError, match="frame_down_ux.*frame_down_uy"):
        SceneSourcePlugin().configure(ctx)  # type: ignore[arg-type]
