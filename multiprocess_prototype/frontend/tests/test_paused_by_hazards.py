# -*- coding: utf-8 -*-
"""H1 задачи 2.11: метка ``paused_by`` доезжает от приостановленного плагина до экрана (тест автора).

Путь из настоящих объектов: ``PluginRunner`` (плагин в ``PAUSED``) -> ``JoinInspectorManager`` ->
``PluginRunner`` (работающий плагин собирает новый dict) -> ``DataReceiver._build_item`` -> strip в SHM,
круг через pickle -> ``bridge.dispatch`` -> насос -> экран ``run_view: running``. Проводка GUI — из
слепого ``test_paused_by_gate_blind``. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import gc
import os
import pickle
from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import PluginState
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
from multiprocess_prototype.frontend.tests import test_paused_by_gate_blind as blind
from Plugins._shared.fanin.join_inspector_manager import JoinInspectorManager

__all__: list[str] = []

wire = blind.wire
_hang_deadline = blind._hang_deadline  # noqa: SLF001 — автофикстура снятия зависшего теста


@pytest.fixture()
def shm(monkeypatch):
    """Пара настоящих ``FrameShmMiddleware`` (писатель, читатель gui)."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)
    made: list[tuple[Any, Any]] = []

    def _make(owner: str) -> Any:
        memory = MemoryManager()
        middleware = FrameShmMiddleware(memory, owner=owner, slot="output_frames", coll=4)
        made.append((middleware, memory))
        return middleware

    yield _make("paused_by_writer"), _make("paused_by_reader")
    gc.collect()
    for middleware, memory in reversed(made):
        for finalize in (middleware.close_handle_cache, middleware.release_owned_memory, memory.close_all):
            finalize()


class _Plugin:
    def __init__(self, name: str, state: PluginState) -> None:
        self.name = name
        self.enabled = True
        self.state = state

    def process(self, items: list[dict]) -> list[dict]:
        # новый dict, как center_crop: свои поля, чужие переносит только движок
        return [{"frame": item["frame"], "seq_id": item["seq_id"]} for item in items]


def _produce(state: PluginState, marked_branch: str) -> dict:
    """Две ветки (``frame``, ``overlay``) -> join -> работающий плагин; ``state`` — у плагина одной ветки."""
    runner = PluginRunner(validate_ports=False)
    joined: list[dict] = []
    join = JoinInspectorManager(required_inputs=["frame", "overlay"], primary="frame", on_ready=joined.extend)
    # overlay первым: join ждёт второй вход, только если уже видел его (auto-passthrough)
    for data_type in ("overlay", "frame"):
        branch_state = state if data_type == marked_branch else PluginState.RUNNING
        item = {"frame": np.full((48, 64, 3), 200, dtype=np.uint8), "seq_id": 1, "data_type": data_type}
        out = runner.call_process(_Plugin(f"p_{data_type}", branch_state), [item])
        # data_type в боевом тракте ставится на уровне сообщения: новый dict плагина получает его обратно
        join.on_item({**out[0], "data_type": data_type})
    assert len(joined) == 1, "join не выдал ровно один item"
    assert join.pending_count == 0, "join оставил вход в буфере: пара не слита"
    return runner.call_process(_Plugin("tail", PluginState.RUNNING), joined)[0]


def _deliver(w: Any, shm: tuple[Any, Any], item: dict) -> None:
    writer, reader = shm
    w.bridge.set_frame_restorer(reader.on_receive)
    received = DataReceiver._build_item(None, {"data": item})  # noqa: SLF001 — метод self не читает
    sent = writer.strip_data_frame_on_send({"target": "gui", "type": "data", "channel": "data", "data": received})
    assert sent is not None
    message = pickle.loads(pickle.dumps(sent))  # свой же объект: круг как через границу процессов
    message["sender"] = "sm"
    assert "frame" not in message["data"], "предусловие: кадр ушёл ссылкой SHM"
    w.bridge.dispatch(message)


@pytest.mark.parametrize("marked_branch", ["frame", "overlay"])
def test_h1_frame_through_paused_plugin_is_not_shown(wire, shm, marked_branch: str) -> None:
    blind._enter_running(wire)  # noqa: SLF001
    item = _produce(PluginState.PAUSED, marked_branch)
    assert item["paused_by"] == f"p_{marked_branch}"

    _deliver(wire, shm, item)
    blind._spin(0.4)  # noqa: SLF001 — период насоса 33 мс

    assert blind._shown(wire.panel, blind._MASK) == 0  # noqa: SLF001
    assert blind._label(wire.panel, blind._MASK).text() == blind._WAIT  # noqa: SLF001


def test_h1_control_same_path_in_running_is_shown(wire, shm) -> None:
    blind._enter_running(wire)  # noqa: SLF001
    item = _produce(PluginState.RUNNING, "frame")
    assert "paused_by" not in item

    _deliver(wire, shm, item)

    assert blind._spin_until(lambda: blind._shown(wire.panel, blind._MASK) == 1, 1.0)  # noqa: SLF001
