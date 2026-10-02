# -*- coding: utf-8 -*-
"""Task 4.7d-1 — авторские тесты опасных мест (дополняют слепые, не заменяют).

Опасности механизма:
  (a) цепочка рецепт -> blueprint -> build() -> config -> _init_data_pipeline рвётся на любом
      звене молча (ключ extras.overflow «заявлен, но не проведён» — именно так уже терялись
      chain_max_lag_items и cv_threads); слепые тесты проверяют звенья по отдельности;
  (b) ``meta.get("frame_id") or ...`` съел бы нулевой идентификатор — кадр 0 и камера 0 валидны;
  (c) ``meta["trace_id"]`` = None (а не отсутствует) обязан дать "", не None.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_manager_module.topology.blueprint import ProcessConfig
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import build_marker

from .test_t47d1_overflow_wiring import _wired_process


def test_recipe_extras_every_reaches_receiver_and_executor_end_to_end():
    _, proc_dict = ProcessConfig(process_name="p", extras={"overflow": "every"}).as_generic_config().build()
    proc = _wired_process(proc_dict["config"])
    assert proc._data_receiver.overflow == "every"
    assert proc._pipeline_executor.overflow == "every"


def test_recipe_without_key_stays_latest_end_to_end():
    _, proc_dict = ProcessConfig(process_name="p").as_generic_config().build()
    assert "overflow" not in proc_dict["config"]
    proc = _wired_process(proc_dict["config"])
    assert proc._data_receiver.overflow == "latest"
    assert proc._pipeline_executor.overflow == "latest"


def test_build_marker_keeps_zero_frame_id_and_camera_id():
    marker = build_marker({"frame_id": 0, "camera_id": 0}, reason="lag", source="p")
    assert marker["frame_id"] == 0
    assert marker["camera_id"] == 0


def test_build_marker_none_trace_id_becomes_empty_string():
    marker = build_marker({"trace_id": None}, reason="lag", source="p")
    assert marker["trace_id"] == ""
