"""Тесты io_peek — сводка in/out плагина (бэкенд io-debug, Этап 5).

Покрытие:
- summarize_payload: ndarray→{shape,dtype} без пикселей, list→{len,head}, None→items=None,
  JSON-safe (никаких ndarray/bytes в результате), усечение по head_len;
- IoPeekPublisher: publish в state_proxy по пути plugins.{name}.io_peek;
- throttle: между публикациями merge не зовётся;
- snapshot входа снимается ДО мутации плагином (pre-хук);
- state_proxy=None → no-op (без падений).
"""

from __future__ import annotations

import json

import numpy as np

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.io_peek import (
    IoPeekPublisher,
    summarize_payload,
)


class _FakePlugin:
    name = "fake"

    def __init__(self, process_fn=None):
        self._fn = process_fn or (lambda items: items)

    def process(self, items):
        return self._fn(items)


class _RecordingProxy:
    """Двойник StateProxy: пишет set-вызовы в список (publisher публикует через set)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def set(self, path, value):
        self.calls.append((path, value))


# ---------------------------------------------------------------------------
#  summarize_payload
# ---------------------------------------------------------------------------


def test_summarize_none_input():
    assert summarize_payload(None) == {"count": 0, "items": None}


def test_summarize_ndarray_no_pixels():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = summarize_payload([{"frame": frame, "seq_id": 7}])
    item = out["items"][0]
    assert item["frame"] == {"_type": "ndarray", "shape": [480, 640, 3], "dtype": "uint8"}
    assert item["seq_id"] == 7
    # JSON-safe: сериализуется без ошибок (пикселей нет).
    json.dumps(out)


def test_summarize_list_len_and_head():
    out = summarize_payload([{"detections": [[1, 2], [3, 4], [5, 6], [7, 8]]}], head_len=2)
    det = out["items"][0]["detections"]
    assert det["_type"] == "list"
    assert det["len"] == 4
    assert len(det["head"]) == 2  # усечено по head_len


def test_summarize_count_truncates_items():
    out = summarize_payload([{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}], head_len=2)
    assert out["count"] == 4  # полный счётчик
    assert len(out["items"]) == 2  # показаны только head_len


def test_summarize_long_string_truncated():
    out = summarize_payload([{"label": "x" * 200}])
    assert out["items"][0]["label"].endswith("…")


# ---------------------------------------------------------------------------
#  IoPeekPublisher через PluginRunner
# ---------------------------------------------------------------------------


def test_publisher_publishes_input_output():
    proxy = _RecordingProxy()
    pub = IoPeekPublisher(proxy, process_name="proc", rate_hz=0)  # rate 0 → каждый вызов
    runner = PluginRunner()
    pub.attach(runner)

    plugin = _FakePlugin(process_fn=lambda items: [{"overlay": {"vlines": [1]}}])
    runner.call_process(plugin, [{"detections": [[1, 2]]}])

    assert len(proxy.calls) == 1
    path, data = proxy.calls[0]
    assert path == "processes.proc.plugins.fake.io_peek"
    assert data["method"] == "process"
    assert data["input"]["items"][0]["detections"]["len"] == 1
    assert "overlay" in data["output"]["items"][0]


def test_publisher_throttle_skips_between_intervals():
    proxy = _RecordingProxy()
    pub = IoPeekPublisher(proxy, process_name="proc", rate_hz=1.0)  # 1 Гц
    runner = PluginRunner()
    pub.attach(runner)
    plugin = _FakePlugin()

    # Подряд несколько вызовов в пределах 1 сек → только первый публикуется.
    for _ in range(5):
        runner.call_process(plugin, [{"x": 1}])

    assert len(proxy.calls) == 1


def test_publisher_input_snapshot_before_mutation():
    """Сводка входа снимается в pre-хуке — до того, как плагин мутирует item."""
    proxy = _RecordingProxy()
    pub = IoPeekPublisher(proxy, process_name="proc", rate_hz=0)
    runner = PluginRunner()
    pub.attach(runner)

    def mutating(items):
        items[0]["added_by_plugin"] = True  # мутация in-place
        return items

    plugin = _FakePlugin(process_fn=mutating)
    runner.call_process(plugin, [{"orig": 1}])

    _, data = proxy.calls[0]
    # Вход зафиксирован ДО мутации: добавленного ключа в сводке входа нет.
    assert "added_by_plugin" not in data["input"]["items"][0]
    # А в выходе — есть.
    assert data["output"]["items"][0]["added_by_plugin"] is True


def test_publisher_noop_without_state_proxy():
    pub = IoPeekPublisher(None, process_name="proc", rate_hz=0)
    runner = PluginRunner()
    pub.attach(runner)
    plugin = _FakePlugin()
    # Не должно падать; публиковать некуда.
    result = runner.call_process(plugin, [{"x": 1}])
    assert result == [{"x": 1}]
