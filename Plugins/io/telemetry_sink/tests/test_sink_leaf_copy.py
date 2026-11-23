"""П3 (Task 2.8a) — слепой RED-тест: накопитель стока хранит листья.

Сборка стока — как в ``test_writer_subtree_evict_hazards`` (``make_plugin`` из соседнего файла).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta

from .test_telemetry_sink_plugin import make_plugin

ПУТЬ = "processes.cam.state.plugins.capture"


def test_sink_dict_delta_replaces_subtree():
    """Вторая dict-дельта на тот же путь заменяет поддерево: ``y`` из первой не остаётся."""
    plugin = make_plugin()
    plugin._on_deltas(
        [
            Delta(path=ПУТЬ, old_value=MISSING, new_value={"x": 1, "y": 2}, source="heartbeat"),
            Delta(path=ПУТЬ, old_value={"x": 1, "y": 2}, new_value={"x": 3}, source="heartbeat"),
        ]
    )
    assert dict(plugin._cache) == {ПУТЬ + ".x": 3}
