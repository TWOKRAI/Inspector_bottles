"""Слепые приёмочные тесты FrameBufferPlugin (T10, RED до кода).

Purpose: проверить контракт плагина буфера кадров: индексация по capture_ns, отказ
кадров без штампа, команды buffer.range / buffer.seek / buffer.pin, учёт разрывов
нумерации, окно buffer_seconds и переживание сбоя кодирования.

Реальный плагин и реальное кольцо TimeRing; контекст - MagicMock (как в тестах
frame_saver). Счётчики читаются из вызовов ctx.publish_metric(name, value).
Плагин импортируется внутри каждого теста: отсутствие пакета краснит тест по
ImportError, а не весь файл при сборе.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

__all__: list[str] = []

_DEADLINE_S = 20.0


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _within_deadline(fn, *args):
    """Вызвать fn(*args) в daemon-потоке с дедлайном; вернуть результат или поднять ошибку."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - пробросим в тест как есть
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(_DEADLINE_S)
    if th.is_alive():
        pytest.fail(f"вызов завис дольше {_DEADLINE_S} c")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def make_plugin(**overrides):
    """Сконфигурированный плагин; overrides идут через ctx.config. Возвращает (plugin, ctx)."""
    from Plugins.io.frame_buffer.plugin import FrameBufferPlugin

    plugin = FrameBufferPlugin()
    ctx = MagicMock()
    ctx.config = dict(overrides)
    ctx.registers = None
    ctx.publish_metric = MagicMock()
    ctx.health = MagicMock()
    plugin.configure(ctx)
    return plugin, ctx


def run_process(plugin, items):
    """process() под дедлайном."""
    return _within_deadline(plugin.process, items)


def command(plugin, name: str, data: dict):
    """Вызвать команду по имени регистрации: getattr(plugin, plugin.commands[name])(data)."""
    handler = getattr(plugin, plugin.commands[name])
    return _within_deadline(handler, data)


def metrics(ctx) -> dict:
    """Последнее значение каждого счётчика из вызовов ctx.publish_metric(name, value)."""
    last: dict = {}
    for call in ctx.publish_metric.call_args_list:
        last[call.args[0]] = call.args[1]
    return last


def item(
    seq: int,
    capture_ns: int,
    *,
    frame=None,
    device_frame_num: int | None = None,
    **extra,
) -> dict:
    """Кадровый item: frame, capture_ns, capture_ts, seq_id (+ device_frame_num)."""
    if frame is None:
        frame = np.zeros((48, 64, 3), np.uint8)
    out = {
        "frame": frame,
        "capture_ns": capture_ns,
        "capture_ts": capture_ns / 1e9,
        "seq_id": seq,
    }
    if device_frame_num is not None:
        out["device_frame_num"] = device_frame_num
    out.update(extra)
    return out


def solid(b: int) -> np.ndarray:
    """Сплошной кадр 64x48, BGR (b, 0, 0)."""
    img = np.zeros((48, 64, 3), np.uint8)
    img[:, :, 0] = b
    return img


def seek(plugin, t_ns: int, mode: str, max_width=None, max_height=None) -> dict:
    return command(
        plugin,
        "buffer.seek",
        {"t_ns": t_ns, "mode": mode, "max_width": max_width, "max_height": max_height},
    )


def buffer_range(plugin) -> dict:
    return command(plugin, "buffer.range", {})


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_every_frame_indexed_by_capture_ns():
    plugin, ctx = make_plugin(buffer_seconds=60)
    stamps = [1_000_000_000 + i * 40_000_000 for i in range(100)]
    run_process(plugin, [item(i + 1, ns) for i, ns in enumerate(stamps)])

    rng = buffer_range(plugin)
    assert rng["frames"] == 100
    assert rng["gaps"] == []

    for ns in stamps:
        res = seek(plugin, ns, "prev")
        assert res["status"] == "ok"
        assert res["capture_ns"] == ns

    m = metrics(ctx)
    assert m["frames_in"] == 100
    assert m["encoded"] == 100
    assert m["gaps"] == 0
    assert m["bytes_held"] > 0
    assert m["span_s"] == pytest.approx(3.96)
    assert m["enc_ms_p99"] >= 0


def test_missing_capture_ns_rejected():
    plugin, ctx = make_plugin()
    base = np.zeros((48, 64, 3), np.uint8)
    bad = [
        {"frame": base, "capture_ts": 1.0, "seq_id": 1},  # нет ключа
        {"frame": base, "capture_ns": None, "capture_ts": 1.0, "seq_id": 2},
        {"frame": base, "capture_ns": 1.0, "capture_ts": 1.0, "seq_id": 3},  # float не штамп
        {"frame": base, "capture_ns": True, "capture_ts": 1.0, "seq_id": 4},  # bool не штамп
    ]
    run_process(plugin, bad)  # не бросает

    # счётчики опубликованы и после вызова, где отвергнуты все item
    assert metrics(ctx)["rejected_no_capture_ns"] == 4
    assert buffer_range(plugin)["frames"] == 0

    run_process(plugin, [item(1, 5)])
    assert buffer_range(plugin)["frames"] == 1
    assert metrics(ctx)["rejected_no_capture_ns"] == 4


def test_seek_returns_frame_of_requested_time():
    plugin, _ctx = make_plugin()
    run_process(
        plugin,
        [
            item(1, 1000, frame=solid(40)),
            item(2, 2000, frame=solid(120)),
            item(3, 3000, frame=solid(200)),
        ],
    )

    res = seek(plugin, 2100, "nearest")
    assert res["status"] == "ok"
    assert res["capture_ns"] == 2000
    # канал B пикселя (0, 0); допуск 3 уровня на JPEG q85
    assert abs(int(res["frame"][0, 0, 0]) - 120) <= 3

    res = seek(plugin, 2600, "nearest")
    assert res["status"] == "ok"
    assert res["capture_ns"] == 3000

    res = seek(plugin, 500, "prev")
    assert res["status"] == "empty"


def test_seek_respects_max_width():
    plugin, _ctx = make_plugin()
    run_process(plugin, [item(1, 1000, frame=np.zeros((1080, 1440, 3), np.uint8))])

    res = seek(plugin, 1000, "prev", max_width=720)
    assert res["status"] == "ok"
    assert res["frame"].shape == (540, 720, 3)

    res = seek(plugin, 1000, "prev", max_width=4000, max_height=4000)
    assert res["status"] == "ok"
    assert res["frame"].shape == (1080, 1440, 3)

    res = seek(plugin, 1000, "prev", max_width=720, max_height=300)
    assert res["status"] == "ok"
    assert res["frame"].shape == (300, 400, 3)


def test_seq_gap_of_three_counts_missed_seq_3():
    plugin, ctx = make_plugin()
    stamps = {1: 100, 2: 200, 3: 300, 7: 700, 8: 800}
    run_process(plugin, [item(s, ns) for s, ns in stamps.items()])

    assert metrics(ctx)["missed_seq"] == 3
    gaps = buffer_range(plugin)["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["after_seq"] == 3
    assert gaps[0]["before_seq"] == 7
    assert gaps[0]["missed"] == 3
    assert gaps[0]["capture_ns"] == 700

    # рестарт нумерации при растущем capture_ns
    run_process(plugin, [item(1, 900)])
    gaps = buffer_range(plugin)["gaps"]
    assert len(gaps) == 2
    assert gaps[1]["restart"] is True
    assert gaps[1]["missed"] == 0
    assert metrics(ctx)["missed_seq"] == 3


def test_device_frame_num_gap_counts_missed_device():
    plugin, ctx = make_plugin()
    run_process(
        plugin,
        [
            item(1, 100, device_frame_num=10),
            item(2, 200, device_frame_num=11),
            item(3, 300, device_frame_num=15),
        ],
    )
    m = metrics(ctx)
    assert m["missed_device"] == 3
    assert m["missed_seq"] == 0

    plugin2, ctx2 = make_plugin()
    run_process(
        plugin2,
        [
            item(1, 100, device_frame_num=None),
            item(2, 200, device_frame_num=None),
            item(3, 300, device_frame_num=None),
        ],
    )
    assert metrics(ctx2)["missed_device"] == 0


def test_lag_marker_becomes_gap():
    plugin, ctx = make_plugin()
    run_process(plugin, [item(1, 100), item(2, 200)])

    marker = {
        "inspection_status": "not_inspected",
        "overflow_marker": True,
        "reason": "lag",
        "count": 2,
        "capture_ts": 1.0,
    }
    run_process(plugin, [marker])
    # счётчики публикуются и в вызове, где был только маркер
    m = metrics(ctx)
    assert m["lag_markers"] == 2
    assert m["rejected_no_capture_ns"] == 0

    run_process(plugin, [item(5, 500)])

    m = metrics(ctx)
    assert m["lag_markers"] == 2
    assert m["rejected_no_capture_ns"] == 0
    assert m["missed_seq"] == 2
    rng = buffer_range(plugin)
    assert rng["frames"] == 3
    assert len(rng["gaps"]) == 1
    assert rng["gaps"][0]["after_seq"] == 2
    assert rng["gaps"][0]["before_seq"] == 5
    assert rng["gaps"][0]["missed"] == 2


def test_encode_failure_does_not_stop_plugin(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = plugin_module.cv2.imencode
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            return False, None
        if calls["n"] == 3:
            raise cv2.error("boom")
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", fake)

    plugin, ctx = make_plugin()
    run_process(plugin, [item(i, i * 100) for i in range(1, 5)])  # не бросает

    m = metrics(ctx)
    assert m["encode_errors"] == 2
    assert m["encoded"] == 2
    assert buffer_range(plugin)["frames"] == 2


def test_buffer_seconds_from_config():
    stamps = [i * 40_000_000 for i in range(400)]  # 25 Гц

    plugin10, _ = make_plugin(buffer_seconds=10, buffer_max_mb=1024)
    run_process(plugin10, [item(i + 1, ns) for i, ns in enumerate(stamps)])
    assert buffer_range(plugin10)["frames"] == 251

    plugin5, _ = make_plugin(buffer_seconds=5, buffer_max_mb=1024)
    run_process(plugin5, [item(i + 1, ns) for i, ns in enumerate(stamps)])
    assert buffer_range(plugin5)["frames"] == 126


def _pin_frames() -> list[dict]:
    first = [item(i + 1, i * 100_000_000) for i in range(4)]  # 0 .. 300 мс
    rest = [item(5 + j, (4 + j) * 100_000_000) for j in range(10)]  # 400 мс .. 1300 мс
    return first + rest


def test_pin_command_protects_range():
    plugin, _ctx = make_plugin(buffer_seconds=0.15)
    # пин ДО первого кадра: кольцо защищает будущие кадры
    command(plugin, "buffer.pin", {"t0_ns": 0, "t1_ns": 100_000_000, "tag": "e1"})
    run_process(plugin, _pin_frames())

    rng = buffer_range(plugin)
    assert rng["frames"] == 4
    assert rng["t_min_ns"] == 0
    assert rng["t_max_ns"] == 1_300_000_000
    assert rng["gaps"] == []
    assert seek(plugin, 0, "prev")["capture_ns"] == 0
    assert seek(plugin, 100_000_000, "prev")["capture_ns"] == 100_000_000
    assert seek(plugin, 200_000_000, "prev")["capture_ns"] == 100_000_000

    # тот же вход без buffer.pin: пин ничего не защитил
    bare, _ctx2 = make_plugin(buffer_seconds=0.15)
    run_process(bare, _pin_frames())
    rng = buffer_range(bare)
    assert rng["frames"] == 2
    assert rng["t_min_ns"] == 1_200_000_000
    assert seek(bare, 0, "prev")["status"] == "empty"

    # t0 > t1: status error без исключения, текст без значений входа
    err = command(plugin, "buffer.pin", {"t0_ns": 987_654_321, "t1_ns": 123_456_789, "tag": "bad"})
    assert err["status"] == "error"
    for value in err.values():
        if isinstance(value, str):
            assert "987654321" not in value
            assert "123456789" not in value
