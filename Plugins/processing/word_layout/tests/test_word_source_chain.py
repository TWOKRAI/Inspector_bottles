"""C-37 C1: слово с телефона и запись регистра — цепочка на настоящих объектах, без IPC.

Что настоящее: ``RegistersManager`` с регистром ``word_layout``; запись регистра — настоящий
``PluginOrchestrator._on_register_update``; порт слова — настоящий ``PhoneCameraPlugin``
(``cmd_emit_signal`` -> ``produce()``); диски — настоящие ``line_filter`` (zone_edge) -> ``center_crop``,
``predictions`` дописываются к item от center_crop (распознавание не нужно).

Что НЕ покрыто (боевой layout: fanin-passthrough, батчи по одному item): пикл, ``chain_queue``,
поток ``pipeline_executor``, реальный рецепт (конфиги — литералы из ``letter_robot_sim.yaml``).

Ячейки «МИР»: М0 И1 Р2; «РИМ»: Р0 И1 М2.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager

from Plugins.filter.line_filter.plugin import LineFilterPlugin
from Plugins.processing.center_crop.plugin import CenterCropPlugin
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Plugins.processing.word_layout.registers import WordLayoutRegisters
from Services.phone_gateway.plugin.plugin import PhoneCameraPlugin

# Литерал word_layout из multiprocess_prototype/recipes/letter_robot_sim.yaml:311-330;
# require_pick переопределён: pick_xy появляется только после калибровки, в тесте его нет.
_WORD_CFG: dict[str, Any] = {
    "target_word": "",
    "word_source": "signal_2",
    "use_pitch": True,
    "first_x": 320.0,
    "first_y": -200.0,
    "line_angle_deg": 90.0,
    "pitch_mm": 0.0,
    "last_x": 320.0,
    "last_y": 300.0,
    "place_z_mm": -132.0,
    "disk_radius_mm": 55.0,
    "word_gap_slots": 1,
    "angle_zero_deg": 0.0,
    "angle_invert": False,
    "min_confidence": 0.5,
    "settle_frames": 1,
    "use_trigger": False,
    "pick_source": "pick_xy",
    "encoder_source": "e_capture",
    "require_pick": False,  # рецепт: true; здесь pick_xy нет без калибровки
    "pick_z_mm": -132.0,
}
# Процесс phone из того же рецепта (строки 398-411), auto_start false.
_PHONE_CFG: dict[str, Any] = {
    "camera_id": 9,
    "host": "0.0.0.0",
    "http_port": 8080,
    "resolution_width": 640,
    "resolution_height": 480,
    "auto_start": False,
    "show_hint": True,
}
# Конфиги line_filter / center_crop — как tests/test_disk_identity_chain.py:19-35.
_LINE_CFG = {
    "center_x": 376,
    "center_y": 262,
    "angle": 90,
    "zone_width": 250,
    "mode": "zone_edge",
    "rearm_frames": 2,
    # C-42: zone_edge помнит место пропажи; значения — как в рецепте letter_robot_sim.yaml.
    "max_match_distance": 60,
    "max_age": 20,
}
_CROP_CFG = {
    "size_mode": "radius",
    "radius_scale": 1.0,
    "margin_px": 14,
    "side_px": 256,
    "output_size": 128,
    "drop_partial": False,
    "pad_if_oob": True,
}
# Физическая геометрия (как в test_disk_identity_chain.py): линия angle=90, зона x в [251, 501];
# диск едет по x слева направо, новый входит слева — 228 px от места выхода прежнего.
_PASS_XS = (260, 298, 336, 374, 412, 450, 488)
_CHANGE_MARK = "смена слова"
_DEADLINE_S = 5.0


def _bounded(fn: Callable[[], Any]) -> Any:
    """Вызов, способный зависнуть, — в daemon-потоке с дедлайном."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросить в поток теста
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(_DEADLINE_S)
    if t.is_alive():
        pytest.fail(f"вызов завис дольше {_DEADLINE_S} с")
    if "error" in box:
        raise box["error"]
    return box["result"]


def _mk(cls: type, cfg: dict) -> Any:
    plugin = cls()
    plugin.configure(PluginContext(services=MockProcessServices(name="x", config=cfg), config=cfg))
    return plugin


def test_chain_on_real_objects_port_and_register() -> None:
    layout_services = MockProcessServices(name="layout", config=dict(_WORD_CFG))
    rm = RegistersManager(registers={"word_layout": WordLayoutRegisters()})
    word = WordLayoutPlugin()
    word.configure(PluginContext(services=layout_services, config=dict(_WORD_CFG), registers=rm))
    assert word._reg is rm.get_register("word_layout")  # плагин держит тот же экземпляр, что менеджер

    orch = PluginOrchestrator(MockProcessServices(name="layout", config={}))
    orch._registers_manager = rm

    phone_services = MockProcessServices(name="phone", config=dict(_PHONE_CFG))
    phone = PhoneCameraPlugin()
    phone.configure(PluginContext(services=phone_services, config=dict(_PHONE_CFG)))

    line = _mk(LineFilterPlugin, _LINE_CFG)
    crop = _mk(CenterCropPlugin, _CROP_CFG)
    frame = np.zeros((481, 800, 3), np.uint8)

    def phone_word(value: str) -> None:
        """Кнопка телефона: emit_signal -> produce() -> item сигнала -> word_layout."""
        assert phone.cmd_emit_signal({"port": "signal_2", "value": value})["status"] == "ok"
        items = _bounded(phone.produce)
        signals = [it for it in items if "signal_2" in it]
        assert len(signals) == 1
        assert signals[0]["signal_2"] == value
        assert signals[0]["data_type"] == "signal"
        word.process(signals)

    def write_register(value: str) -> None:
        """Запись регистра настоящим обработчиком register_update."""
        msg = {"data": {"register": "word_layout", "field": "target_word", "value": value}}
        result = _bounded(lambda: orch._on_register_update(msg))
        assert result["success"] is True

    def feed(dets: list[dict], seq: int, label: str) -> list[dict]:
        ov = line.process([{"detections": dets, "seq_id": seq}])[0]
        crops = crop.process([{"frame": frame, "filtered": ov["filtered"], "detections": dets, "seq_id": seq}])
        pred = {"label": label, "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}
        return [word.process([{**c, "predictions": [pred]}])[0] for c in crops]

    seq = 0

    def disk(label: str) -> int | None:
        """Один диск: проход зоны слева направо (событие только на входе) + пустые кадры для повторного взвода."""
        nonlocal seq
        outs: list[dict] = []
        for x in _PASS_XS:
            seq += 1
            outs += feed([{"center": [x, 262], "radius": 40}], seq, label)
        for _ in range(2):
            seq += 1
            feed([], seq, label)
        assert len(outs) == 1  # достижимость: один диск = одно событие
        job = outs[0].get("robot_job")
        return job["slot"] if job else None

    for _ in range(2):  # C-42/О1: защёлка стартует закрытой, взводится rearm_frames пустых кадров
        seq += 1
        feed([], seq, "Р")

    phone_word("МИР")
    assert rm.get_register("word_layout").target_word == "МИР"
    assert disk("Р") == 2

    write_register("РИМ")
    assert disk("Р") == 0

    phone_word("МИР")
    assert disk("И") == 1

    changes = [e["msg"] for e in layout_services.logs if _CHANGE_MARK in e["msg"]]
    assert len(changes) == 2
    assert "источник: регистр" in changes[0]
    assert "источник: порт signal_2" in changes[1]
