"""Хазард- и охранные тесты FrameBufferPlugin (T10, файл developer-а).

Purpose: потоки (process() против команд), замок счётчиков вне imencode / imdecode, отсутствие
записи на диск, accepts_markers, отказы без падения (нет seq_id, порядок, oversize), пределы
buffer.seek без max_height, отказ конфигурации и границы регистров. Ожидания — литералы.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import builtins
import pathlib
import sys
import threading
import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

__all__: list[str] = []

_DEADLINE_S = 20.0


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _within_deadline(fn, *args, deadline: float = _DEADLINE_S):
    """Вызвать fn(*args) в daemon-потоке с дедлайном; вернуть результат или поднять ошибку."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - пробросим в тест как есть
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(deadline)
    if th.is_alive():
        pytest.fail(f"вызов завис дольше {deadline} c")
    if "error" in box:
        raise box["error"]
    return box.get("result")


def make_plugin_ctx(**overrides):
    """Сконфигурированный плагин; счётчики пишутся в dict ``last`` (быстрее MagicMock на 20000 вызовов).

    Возвращает (plugin, last, ctx): ctx нужен тестам, которые смотрят ``ctx.health``.
    """
    from Plugins.io.frame_buffer.plugin import FrameBufferPlugin

    plugin = FrameBufferPlugin()
    ctx = MagicMock()
    ctx.config = dict(overrides)
    ctx.registers = None
    last: dict = {}
    ctx.publish_metric = last.__setitem__
    ctx.health = MagicMock()
    plugin.configure(ctx)
    return plugin, last, ctx


def make_plugin(**overrides):
    plugin, last, _ctx = make_plugin_ctx(**overrides)
    return plugin, last


def command(plugin, name: str, data: dict):
    return _within_deadline(getattr(plugin, plugin.commands[name]), data)


def item(seq: int, capture_ns: int, *, frame=None) -> dict:
    if frame is None:
        frame = np.zeros((48, 64, 3), np.uint8)
    return {"frame": frame, "capture_ns": capture_ns, "capture_ts": capture_ns / 1e9, "seq_id": seq}


def solid(b: int, rows: int = 48, cols: int = 64) -> np.ndarray:
    img = np.zeros((rows, cols, 3), np.uint8)
    img[:, :, 0] = b
    return img


# ---------------------------------------------------------------------------
# Потоки
# ---------------------------------------------------------------------------


def test_concurrent_process_and_commands():
    """20000 process() против seek / pin / range: кадр seek целый и свой, счётчики без потерь."""
    n_frames, step = 20000, 40_000_000
    plugin, last = make_plugin(buffer_seconds=600, buffer_max_mb=1024)
    colors = [solid(c + 20, rows=24, cols=32) for c in range(200)]  # кадр i красится в (i % 200) + 20
    errors: list[BaseException] = []
    stop = threading.Event()
    seeks_ok = [0]
    pins_ok = [0]

    def writer() -> None:
        try:
            for i in range(1, n_frames + 1):
                plugin.process([item(i, i * step, frame=colors[i % 200])])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            stop.set()

    def seeker() -> None:
        try:
            while not stop.is_set():
                t_ns = int(time.perf_counter_ns() % (n_frames * step))
                res = plugin._cmd_seek({"t_ns": t_ns, "mode": "nearest"})
                if res["status"] != "ok":
                    time.sleep(0.0005)
                    continue
                frame, cns = res["frame"], res["capture_ns"]
                assert frame.shape == (24, 32, 3)
                assert cns % step == 0
                expected = (cns // step) % 200 + 20  # кадр целый и принадлежит своему capture_ns
                assert abs(int(frame[0, 0, 0]) - expected) <= 3
                assert abs(int(frame[23, 31, 0]) - expected) <= 3
                seeks_ok[0] += 1
                time.sleep(0.0005)  # без паузы голодает писатель на GIL (замер: >10 мин вместо 7 с)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def pinner() -> None:
        try:
            k = 0
            while not stop.is_set():
                rng = plugin._cmd_range({})
                if rng["frames"]:
                    assert rng["t_min_ns"] <= rng["t_max_ns"]
                    res = plugin._cmd_pin(
                        {"t0_ns": rng["t_max_ns"] - 10 * step, "t1_ns": rng["t_max_ns"], "tag": f"e{k % 4}"}
                    )
                    assert res["status"] == "ok"
                    pins_ok[0] += 1
                k += 1
                time.sleep(0.002)  # pin пересчитывает закреплённые байты сканом кольца под его замком
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=fn, daemon=True) for fn in (writer, seeker, seeker, pinner)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(240.0)
        alive = [th for th in threads if th.is_alive()]
    finally:
        sys.setswitchinterval(old_interval)
    assert not alive, "поток завис"
    assert errors == []
    assert seeks_ok[0] > 0 and pins_ok[0] > 0  # читатели действительно работали
    assert last["frames_in"] == n_frames
    assert last["encoded"] == n_frames
    assert last["missed_seq"] == 0
    assert last["gaps"] == 0
    for name in ("rejected_no_capture_ns", "encode_errors", "rejected_order", "rejected_oversize", "rejected_invalid"):
        assert last[name] == 0, name


def test_command_during_process_not_blocked(monkeypatch):
    """Пока imencode заблокирован, команды отвечают и process() другого потока не ждёт замок счётчиков;
    пока заблокирован imdecode (seek), process() идёт. Без обращения к приватным атрибутам плагина."""
    import Plugins.io.frame_buffer.plugin as plugin_module

    plugin, last = make_plugin()
    plugin.process([item(1, 100)])

    original_encode, original_decode = cv2.imencode, cv2.imdecode
    entered, release = threading.Event(), threading.Event()
    calls = {"encode": 0}

    def blocking_first_encode(*args, **kwargs):
        calls["encode"] += 1
        if calls["encode"] == 1:  # блокируется только первый вызов; второй процесс проходит насквозь
            entered.set()
            release.wait(10.0)
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", blocking_first_encode)
    proc = threading.Thread(target=plugin.process, args=([item(2, 200)],), daemon=True)
    proc.start()
    assert entered.wait(5.0), "process() не дошёл до imencode"
    try:
        assert command(plugin, "buffer.range", {})["frames"] == 1
        assert command(plugin, "buffer.seek", {"t_ns": 100, "mode": "prev"})["status"] == "ok"
        assert command(plugin, "buffer.pin", {"t0_ns": 0, "t1_ns": 50, "tag": "x"})["status"] == "ok"
        # второй process() под дедлайном: если замок счётчиков удержан на imencode, он повиснет на frames_in
        _within_deadline(plugin.process, [item(3, 300)], deadline=5.0)
        assert last["frames_in"] == 3
    finally:
        release.set()
        proc.join(10.0)
    assert not proc.is_alive()
    monkeypatch.setattr(plugin_module.cv2, "imencode", original_encode)

    # seek заблокирован на imdecode: process() другого кадра не ждёт его
    d_entered, d_release = threading.Event(), threading.Event()

    def blocking_decode(*args, **kwargs):
        d_entered.set()
        d_release.wait(10.0)
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imdecode", blocking_decode)
    seeker = threading.Thread(target=plugin._cmd_seek, args=({"t_ns": 100, "mode": "prev"},), daemon=True)
    seeker.start()
    assert d_entered.wait(5.0), "seek не дошёл до imdecode"
    try:
        _within_deadline(plugin.process, [item(4, 400)], deadline=5.0)
        assert last["frames_in"] == 4
    finally:
        d_release.set()
        seeker.join(10.0)
    assert not seeker.is_alive()


# ---------------------------------------------------------------------------
# Диск
# ---------------------------------------------------------------------------


def test_process_does_not_touch_disk(monkeypatch):
    """СЛАБЫЙ тест: патчатся только builtins.open и Path.write_bytes; настоящая страховка — git grep в ACCEPTANCE."""
    plugin, _last = make_plugin()

    def forbidden(*args, **kwargs):
        raise AssertionError("запись на диск из process()")

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", forbidden)
        m.setattr(pathlib.Path, "write_bytes", forbidden)
        m.setattr(pathlib.Path, "write_text", forbidden)
        plugin.process([item(1, 100), item(2, 200)])
        assert plugin._cmd_range({})["frames"] == 2
        assert plugin._cmd_seek({"t_ns": 100, "mode": "prev"})["status"] == "ok"


# ---------------------------------------------------------------------------
# Охранные
# ---------------------------------------------------------------------------


def test_plugin_accepts_markers():
    from Plugins.io.frame_buffer.plugin import FrameBufferPlugin

    assert getattr(FrameBufferPlugin, "accepts_markers", None) is True


def test_item_without_seq_id_counted_not_raised():
    plugin, last = make_plugin()
    bad = {"frame": np.zeros((48, 64, 3), np.uint8), "capture_ns": 100, "capture_ts": 1.0}  # нет seq_id
    plugin.process([bad])  # не бросает
    assert last["rejected_invalid"] == 1
    assert plugin._cmd_range({})["frames"] == 0
    plugin.process([item(1, 200)])
    assert plugin._cmd_range({})["frames"] == 1
    assert last["rejected_invalid"] == 1


def test_rejected_frame_does_not_move_prev_seq():
    plugin, last = make_plugin()
    plugin.process([item(5, 200), item(3, 150), item(6, 300)])
    assert last["rejected_order"] == 1
    assert last["missed_seq"] == 0
    assert plugin._cmd_range({})["frames"] == 2


def test_oversize_frame_counted_not_raised(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, np.zeros(16 * 1024 * 1024 + 1, np.uint8)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", fake)
    plugin, last = make_plugin(buffer_max_mb=16)
    plugin.process([item(1, 100)])  # не бросает
    assert last["rejected_oversize"] == 1
    assert plugin._cmd_range({})["frames"] == 0

    plugin.process([item(2, 200)])  # следующий обычный кадр принят
    assert last["rejected_oversize"] == 1
    assert plugin._cmd_range({})["frames"] == 1
    assert last["frames_in"] == 2


# ---------------------------------------------------------------------------
# seek: пределы; конфигурация; окно p99
# ---------------------------------------------------------------------------


def test_seek_absent_limit_means_no_limit():
    plugin, _last = make_plugin()
    plugin.process([item(1, 1000, frame=np.zeros((1080, 1440, 3), np.uint8))])

    only_w = plugin._cmd_seek({"t_ns": 1000, "mode": "prev", "max_width": 720})  # max_height нет в dict
    assert only_w["frame"].shape == (540, 720, 3)
    only_h = plugin._cmd_seek({"t_ns": 1000, "mode": "prev", "max_height": 540, "max_width": None})
    assert only_h["frame"].shape == (540, 720, 3)
    neither = plugin._cmd_seek({"t_ns": 1000, "mode": "prev"})
    assert neither["frame"].shape == (1080, 1440, 3)
    default_mode = plugin._cmd_seek({"t_ns": 1000})  # mode по умолчанию nearest
    assert default_mode["status"] == "ok" and default_mode["capture_ns"] == 1000


def test_seek_bad_input_is_error_not_exception():
    plugin, _last = make_plugin()
    plugin.process([item(1, 1000)])
    for data in (
        {"t_ns": "1000"},
        {"t_ns": 1000, "mode": "sideways"},
        {"t_ns": 1000, "max_width": 0},
        {"t_ns": 1000, "max_height": -5},
        {"t_ns": 1000, "mode": ["prev"]},  # нехешируемый mode
        {"t_ns": 1000, "mode": {}},
        {"t_ns": 1000, "mode": None},
        {},
        "x",  # data не dict
        [1, 2],
        5,
    ):
        assert plugin._cmd_seek(data)["status"] == "error", data
    assert plugin._cmd_seek(None)["status"] == "error"  # нет t_ns
    assert plugin._cmd_range(None)["frames"] == 1  # data может отсутствовать


def test_pin_exceeding_buffer_max_refuses_configure():
    from Plugins.io.frame_buffer.plugin import FrameBufferPlugin

    plugin = FrameBufferPlugin()
    ctx = MagicMock()
    ctx.config = {"buffer_max_mb": 16, "pin_max_mb": 32}
    ctx.registers = None
    with pytest.raises(ValueError, match="pin_max_mb"):  # текст плагина, а не конструктора кольца
        plugin.configure(ctx)
    # плагин жив и безопасен: process — pass-through, команды отвечают status error
    items = [item(1, 100)]
    assert plugin.process(items) is items
    assert plugin._cmd_range({})["status"] == "error"
    assert plugin._cmd_seek({"t_ns": 1})["status"] == "error"
    assert plugin._cmd_pin({"t0_ns": 0, "t1_ns": 1, "tag": "a"})["status"] == "error"


def test_register_bounds_from_field_meta():
    for bad in (
        {"jpeg_quality": 0},
        {"jpeg_quality": 150},
        {"buffer_seconds": 0.0},
        {"buffer_max_mb": 8},
        {"pin_max_mb": -1},
    ):
        with pytest.raises(ValidationError):
            make_plugin(**bad)
    make_plugin(jpeg_quality=50)  # принято


def test_frames_in_counts_rejected_frames():
    """frames_in считает все кадры с frame, в том числе отвергнутые (DESIGN п.4)."""
    plugin, last = make_plugin()
    base = np.zeros((48, 64, 3), np.uint8)
    plugin.process([{"frame": base, "capture_ts": 1.0, "seq_id": 1}, item(1, 100)])
    assert last["frames_in"] == 2
    assert last["rejected_no_capture_ns"] == 1
    assert last["encoded"] == 1


def test_pin_bad_input_is_error_not_exception():
    plugin, _last = make_plugin()
    plugin.process([item(1, 100)])
    for data in (
        {"t0_ns": "0", "t1_ns": 10, "tag": "a"},
        {"t0_ns": 0, "t1_ns": 10.0, "tag": "a"},
        {"t0_ns": 0, "t1_ns": 10},  # нет tag
        {"t0_ns": 0, "t1_ns": 10, "tag": True},
        {"t0_ns": 0, "t1_ns": 10, "tag": ["a"]},  # не хешируется
        {},
        "x",  # data не dict
        [1, 2],
        5,
    ):
        assert plugin._cmd_pin(data)["status"] == "error", data
    assert plugin._cmd_pin({"t0_ns": 0, "t1_ns": 10, "tag": "a"})["status"] == "ok"


def test_seek_size_rounds_half_up_to_nearest():
    plugin, _last = make_plugin()
    plugin.process([item(1, 1000, frame=np.zeros((1080, 1440, 3), np.uint8))])
    res = plugin._cmd_seek({"t_ns": 1000, "mode": "prev", "max_width": 721})  # высота 540.75 -> 541
    assert res["frame"].shape == (541, 721, 3)

    plugin2, _last2 = make_plugin()
    plugin2.process([item(1, 1000, frame=np.zeros((20, 64, 3), np.uint8))])
    res = plugin2._cmd_seek({"t_ns": 1000, "mode": "prev", "max_width": 8})  # высота 2.5 -> 3 (half-up)
    assert res["frame"].shape == (3, 8, 3)


def test_marker_count_fallback_is_one():
    plugin, last = make_plugin()
    base = {"inspection_status": "not_inspected", "overflow_marker": True, "reason": "lag", "capture_ts": 1.0}
    plugin.process([dict(base)])  # count нет
    assert last["lag_markers"] == 1
    for bad in (0, -3, "x", True, None):
        before = last["lag_markers"]
        plugin.process([{**base, "count": bad}])
        assert last["lag_markers"] == before + 1, bad
    plugin.process([{**base, "count": 4}])
    assert last["lag_markers"] == 10


def test_reconfigure_resets_counters_and_ring():
    from unittest.mock import MagicMock as _MM

    plugin, last = make_plugin()
    plugin.process([item(1, 100), item(2, 200), item(5, 500)])
    assert last["frames_in"] == 3 and last["missed_seq"] == 2
    ctx2 = _MM()
    ctx2.config = {}
    ctx2.registers = None
    fresh: dict = {}
    ctx2.publish_metric = fresh.__setitem__
    plugin.configure(ctx2)
    plugin.process([item(9, 900)])
    assert fresh["frames_in"] == 1
    assert fresh["missed_seq"] == 0  # prev_seq не пережил configure
    assert plugin._cmd_range({})["frames"] == 1


def test_jpeg_quality_from_config():
    noise = np.random.default_rng(0).integers(0, 256, (48, 64, 3), dtype=np.uint8)
    plugin_lo, last_lo = make_plugin(jpeg_quality=10)
    plugin_hi, last_hi = make_plugin(jpeg_quality=95)
    plugin_lo.process([item(1, 100, frame=noise)])
    plugin_hi.process([item(1, 100, frame=noise)])
    assert last_hi["bytes_held"] > 2 * last_lo["bytes_held"]


def test_enc_ms_p99_follows_slow_encodes(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def sometimes_slow(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 97:  # три последних кадра из 100 — по 25 мс
            time.sleep(0.025)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", sometimes_slow)
    plugin, last = make_plugin()
    plugin.process([item(i, i * 100) for i in range(1, 101)])
    assert last["enc_ms_p99"] >= 20.0


def test_enc_ms_p99_is_not_the_maximum(monkeypatch):
    """Один выброс из 100 не попадает в p99 (99-й по порядку из 100), в отличие от максимума."""
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def one_outlier(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 100:
            time.sleep(0.3)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", one_outlier)
    plugin, last = make_plugin()
    plugin.process([item(i, i * 100) for i in range(1, 101)])
    assert last["enc_ms_p99"] < 150.0


# ---------------------------------------------------------------------------
# Охранные тесты по ревью стадии 5 (каждый красен на своём мутанте)
# ---------------------------------------------------------------------------


def test_gaps_metric_counts_gap_entries():
    plugin, last = make_plugin()
    plugin.process([item(1, 100), item(2, 200), item(5, 500)])
    assert last["gaps"] == 1


def test_equal_device_frame_num_adds_no_missed_device():
    plugin, last = make_plugin()
    first, second = item(1, 100), item(2, 200)
    first["device_frame_num"] = second["device_frame_num"] = 10
    plugin.process([first, second])
    assert last["missed_device"] == 0


def test_none_device_frame_num_neighbour_not_counted():
    plugin, last = make_plugin()
    frames = [item(1, 100), item(2, 200), item(3, 300)]
    for frame, device in zip(frames, (10, None, 15)):
        if device is not None:
            frame["device_frame_num"] = device
    plugin.process(frames)
    assert last["missed_device"] == 0


def test_same_seq_with_greater_capture_ns_is_restart_not_gap():
    plugin, last = make_plugin()
    plugin.process([item(1, 100), item(2, 200), item(2, 300)])
    assert last["missed_seq"] == 0
    assert last["rejected_order"] == 0


def test_pin_max_equal_to_buffer_max_is_allowed():
    plugin, _last = make_plugin(buffer_max_mb=16, pin_max_mb=16)
    plugin.process([item(1, 100)])
    assert plugin._cmd_range({})["frames"] == 1


def test_errors_reported_to_health_with_context():
    plugin, _last, ctx = make_plugin_ctx()
    plugin.process([item(1, 100, frame=np.zeros((0, 0, 3), np.uint8))])  # imencode отказывает на пустом кадре
    assert ctx.health.report_error.call_count == 1
    assert ctx.health.report_error.call_args.kwargs["context"] == "frame_buffer.encode"

    no_seq = {"frame": np.zeros((8, 8, 3), np.uint8), "capture_ns": 200, "capture_ts": 1.0}
    plugin.process([no_seq])  # кольцо отказывает: ValueError на None
    assert ctx.health.report_error.call_count == 2
    assert ctx.health.report_error.call_args.kwargs["context"] == "frame_buffer.append"


def test_process_returns_the_same_items():
    plugin, _last = make_plugin()
    items = [item(1, 100)]
    result = plugin.process(items)
    assert result is items
    assert len(items) == 1


def test_oversize_frame_does_not_move_prev_seq(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, np.zeros(16 * 1024 * 1024 + 1, np.uint8)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", fake)
    plugin, last = make_plugin(buffer_max_mb=16)
    plugin.process([item(1, 100), item(5, 500)])
    assert last["rejected_oversize"] == 1
    assert last["missed_seq"] == 0  # кадр seq 1 кольцом не принят: счёт стартует с seq 5


def test_counting_resumes_after_ring_rejection():
    plugin, last = make_plugin()
    plugin.process([item(5, 200), item(3, 150), item(6, 300), item(9, 400)])
    assert last["rejected_order"] == 1
    assert last["missed_seq"] == 2  # 6 -> 9: пропущено 7 и 8


def test_enc_ms_window_is_bounded_to_512(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def slow_first_88(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 88:
            time.sleep(0.025)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", slow_first_88)
    plugin, last = make_plugin()
    plugin.process([item(i, i * 100) for i in range(1, 701)])
    # 88 медленных кадров вытеснены окном из 512 (700 - 512 = 188 > 88): p99 быстрый
    assert last["enc_ms_p99"] < 20.0


def test_two_pin_tags_both_protect():
    plugin, _last = make_plugin(buffer_seconds=0.15)
    assert plugin._cmd_pin({"t0_ns": 0, "t1_ns": 100_000_000, "tag": "a"})["status"] == "ok"
    assert plugin._cmd_pin({"t0_ns": 500_000_000, "t1_ns": 600_000_000, "tag": "b"})["status"] == "ok"
    plugin.process([item(i + 1, i * 100_000_000) for i in range(14)])
    # пин a: кадры 0 и 100 мс; пин b: 500 и 600 мс; плюс два свежих (1200, 1300 мс)
    assert plugin._cmd_range({})["frames"] == 6


def test_frame_of_exactly_buffer_max_bytes_is_accepted(monkeypatch):
    import Plugins.io.frame_buffer.plugin as plugin_module

    monkeypatch.setattr(plugin_module.cv2, "imencode", lambda *a, **k: (True, np.zeros(16 * 1024 * 1024, np.uint8)))
    plugin, last = make_plugin(buffer_max_mb=16)
    plugin.process([item(1, 100)])
    assert last["rejected_oversize"] == 0  # мегабайт = 1024 * 1024, а не 10**6
    assert plugin._cmd_range({})["frames"] == 1


def test_seek_default_mode_is_nearest():
    plugin, _last = make_plugin()
    plugin.process([item(1, 1000), item(2, 2000)])
    assert plugin._cmd_seek({"t_ns": 1600})["capture_ns"] == 2000  # prev дал бы 1000


def test_failed_reconfigure_keeps_previous_state():
    plugin, last, _ctx = make_plugin_ctx()
    plugin.process([item(1, 100), item(2, 200)])
    assert last["frames_in"] == 2

    bad_ctx = MagicMock()
    bad_ctx.config = {"buffer_max_mb": 16, "pin_max_mb": 32}
    bad_ctx.registers = None
    bad_published: dict = {}
    bad_ctx.publish_metric = bad_published.__setitem__
    with pytest.raises(ValueError):
        plugin.configure(bad_ctx)

    # плагин продолжает на прежнем кольце, прежних счётчиках и прежнем ctx
    plugin.process([item(3, 300)])
    assert plugin._cmd_range({})["frames"] == 3
    assert last["frames_in"] == 3
    assert last["missed_seq"] == 0
    assert bad_published == {}


def test_pin_max_mb_from_config_limits_pinned_bytes(monkeypatch):
    """pin_max_mb доходит до кольца: пин, превысивший бюджет 1 МБ, освобождается."""
    import Plugins.io.frame_buffer.plugin as plugin_module

    monkeypatch.setattr(plugin_module.cv2, "imencode", lambda *a, **k: (True, np.zeros(600_000, np.uint8)))
    plugin, _last = make_plugin(buffer_seconds=0.15, buffer_max_mb=16, pin_max_mb=1)
    assert plugin._cmd_pin({"t0_ns": 0, "t1_ns": 100_000_000, "tag": "e1"})["status"] == "ok"
    frames = [item(i + 1, i * 100_000_000) for i in range(14)]
    plugin.process(frames)
    # два кадра пина по 600000 байт = 1,2 МБ > 1 МБ: пин освобождён, остались два свежих кадра
    # (с бюджетом пинов 16 МБ защищены были бы 4 кадра)
    assert plugin._cmd_range({})["frames"] == 2


def test_enc_ms_p99_takes_slow_encodes_from_window_start(monkeypatch):
    """p99 берётся по порядку значений, а не по времени: медленные кадры стоят в начале окна."""
    import Plugins.io.frame_buffer.plugin as plugin_module

    original = cv2.imencode
    calls = {"n": 0}

    def slow_first_three(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 3:
            time.sleep(0.025)
        return original(*args, **kwargs)

    monkeypatch.setattr(plugin_module.cv2, "imencode", slow_first_three)
    plugin, last = make_plugin()
    plugin.process([item(i, i * 100) for i in range(1, 101)])
    assert last["enc_ms_p99"] >= 20.0


def test_seek_size_never_collapses_to_zero_pixels():
    plugin, _last = make_plugin()
    plugin.process([item(1, 1000, frame=np.zeros((20, 640, 3), np.uint8))])
    res = plugin._cmd_seek({"t_ns": 1000, "mode": "prev", "max_width": 8})  # высота 20*8/640 = 0,25 -> не меньше 1
    assert res["status"] == "ok"
    assert res["frame"].shape == (1, 8, 3)
