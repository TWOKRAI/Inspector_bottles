"""Тесты лида после break-injection Task 3.5b: ключи конфига сцены `geometry` и
`match_radius_mm` действительно доходят до сопоставления.

Инъекции J7 (`geometry` из конфига игнорируется) и J8 (`match_radius_mm` игнорируется)
проходили весь набор зелёным: все тесты шли на дефолтах 0/0 и 5.0 мм.
"""

from __future__ import annotations

from Plugins.sim.scene_source.tests.test_scene_source_task_3_5 import (
    _call,
    _job_for_object,
    _make_plugin_with_engine,
    _push_encoder,
)


def _one_object(tmp_path, cfg):
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, cfg)
    _push_encoder(sp, 1000)
    plugin.produce()
    (obj,) = plugin._spawner.active_objects()
    return plugin, obj.passport.spawn_encoder


def _last_outcome(plugin) -> str:
    return _call(plugin, "scene.status")["recent"][-1]["outcome"]


def test_geometry_origin_from_config_is_used(tmp_path):
    plugin, spawn = _one_object(tmp_path, {"geometry": {"origin_x_mm": 100.0, "origin_y_mm": -50.0}})
    job = _job_for_object(index=1, spawn_encoder=spawn, ecap=2000)  # координаты для origin (0, 0)

    _call(plugin, "scene.job_done", job)
    plugin.produce()
    assert _last_outcome(plugin) == "no_object"

    shifted = {**job, "index": 2, "x_mm": job["x_mm"] + 100.0, "y_mm": job["y_mm"] - 50.0}
    _call(plugin, "scene.job_done", shifted)
    plugin.produce()
    assert _last_outcome(plugin) == "matched"


def test_match_radius_from_config_is_used(tmp_path):
    plugin, spawn = _one_object(tmp_path, {"match_radius_mm": 30.0})
    job = _job_for_object(index=1, spawn_encoder=spawn, ecap=2000)
    job["x_mm"] += 20.0  # при дефолтных 5 мм это no_object

    _call(plugin, "scene.job_done", job)
    plugin.produce()
    assert _last_outcome(plugin) == "matched"
