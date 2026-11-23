"""Hazard-тесты Task 1.1a: гонки и lock, once-предупреждения, разбор sidecar_keys, порядок слияния.

Авторские тесты разработчика (слепая приёмка — в test_frame_saver_sidecar_keys.py).
Каждый вызов configure()/process() идёт в daemon-потоке с дедлайном: двойной захват
``self._lock`` даёт красный тест, а не зависание.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

import Plugins.io.frame_saver.plugin as plugin_mod
from Plugins.io.frame_saver.plugin import FrameSaverPlugin

JOIN_DEADLINE_S = 5.0


def call(fn, *args, **kwargs):
    """Вызвать fn в daemon-потоке с дедлайном 5 с; исключение потока пробрасывается."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в тест как есть
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(JOIN_DEADLINE_S)
    assert not t.is_alive(), f"{getattr(fn, '__name__', fn)} завис (> {JOIN_DEADLINE_S} с): взаимная блокировка?"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def make_ctx(tmp_path: Path, **overrides) -> MagicMock:
    cfg: dict = {
        "output_dir": str(tmp_path),
        "subfolder_by_date": False,
        "write_sidecar": True,
        "index_source": "counter",
    }
    cfg.update(overrides)
    ctx = MagicMock()
    ctx.config = cfg
    ctx.registers = None
    return ctx


def make_plugin(tmp_path: Path, **overrides) -> tuple[FrameSaverPlugin, MagicMock]:
    """Сконфигурированный плагин + его ctx (для проверки log_warning)."""
    plugin = FrameSaverPlugin()
    ctx = make_ctx(tmp_path, **overrides)
    call(plugin.configure, ctx)
    return plugin, ctx


def make_item(i: int, **extra) -> dict:
    item: dict = {"frame": np.zeros((4, 4, 3), dtype=np.uint8), "sidecar": {"track_id": i}}
    item.update(extra)
    return item


def only_json(tmp_path: Path) -> dict:
    jsons = list(tmp_path.glob("*.json"))
    assert len(jsons) == 1, [p.name for p in jsons]
    return json.loads(jsons[0].read_text(encoding="utf-8"))


# --- гонки и lock ---


def test_save_now_during_process_leaves_complete_sidecars(tmp_path):
    """_cmd_save_now из второго потока во время process(): у каждого кадра полный .json, без .tmp."""
    n_frames = 40
    plugin, _ = make_plugin(
        tmp_path,
        save_mode="trigger",
        buffer_mode="accumulate",
        buffer_size=n_frames,
        sidecar_keys="pick_xy",
    )
    stop = threading.Event()
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for i in range(n_frames):
                plugin.process([make_item(i, pick_xy={"x_mm": np.float32(1.5), "y_mm": float(i)})])
        except BaseException as exc:  # noqa: BLE001 — собираем для проверки в основном потоке
            errors.append(exc)
        finally:
            stop.set()

    def saver() -> None:
        try:
            while not stop.is_set():
                plugin._cmd_save_now({})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=producer, daemon=True), threading.Thread(target=saver, daemon=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_DEADLINE_S)
        assert not t.is_alive(), "поток завис (> 5 с): возможна взаимная блокировка на self._lock"
    assert errors == []
    call(plugin._cmd_save_now, {})  # добираем остаток буфера

    images = sorted(tmp_path.glob("*.jpg"))
    assert len(images) == n_frames
    assert list(tmp_path.glob("*.tmp")) == []
    for img in images:
        sidecar = img.with_suffix(".json")
        assert sidecar.exists(), f"нет .json у {img.name}"
        data = json.loads(sidecar.read_text(encoding="utf-8"))  # полный, парсится
        assert data["file"] == img.name
        assert data["pick_xy"]["x_mm"] == 1.5
        assert {"track_id", "width", "height", "saved_ts"} <= set(data)


def test_write_sidecar_runs_under_lock(tmp_path):
    """_write_sidecar вызывается под self._lock (шпион видит locked() == True)."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="pick_xy")
    seen: list[bool] = []
    original = plugin._write_sidecar

    def spy(*args, **kwargs):
        seen.append(plugin._lock.locked())
        return original(*args, **kwargs)

    plugin._write_sidecar = spy
    call(plugin.process, [make_item(1, pick_xy={"x": np.float32(1.5)})])
    assert seen == [True]


def test_two_flushers_never_overlap_in_save_frame(tmp_path, monkeypatch):
    """Два потока сливают буфер с замедленным imencode: одновременно в _save_frame ровно один, jpg == json == n."""
    n = 20
    plugin, _ = make_plugin(
        tmp_path, save_mode="trigger", buffer_mode="accumulate", buffer_size=n, sidecar_keys="pick_xy"
    )
    for i in range(n):
        call(plugin.process, [make_item(i, pick_xy={"x": np.float32(1.5)})])

    inflight = {"cur": 0, "max": 0}
    counter_lock = threading.Lock()
    real_imencode = plugin_mod.cv2.imencode

    def slow_imencode(*args, **kwargs):
        with counter_lock:
            inflight["cur"] += 1
            inflight["max"] = max(inflight["max"], inflight["cur"])
        time.sleep(0.002)
        try:
            return real_imencode(*args, **kwargs)
        finally:
            with counter_lock:
                inflight["cur"] -= 1

    monkeypatch.setattr(plugin_mod.cv2, "imencode", slow_imencode)
    buf = list(plugin._buffer)
    half = len(buf) // 2

    def drain(items: list[dict]) -> None:
        for it in items:
            plugin._save_frame(it)

    threads = [
        threading.Thread(target=drain, args=(buf[:half],), daemon=True),
        threading.Thread(target=drain, args=(buf[half:],), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_DEADLINE_S)
        assert not t.is_alive(), "поток завис (> 5 с)"
    assert inflight["max"] == 1
    assert len(list(tmp_path.glob("*.jpg"))) == n
    assert len(list(tmp_path.glob("*.json"))) == n


# --- configure(): разбор, валидация, предупреждения ---


def test_sidecar_keys_parsing_strips_and_drops_empty(tmp_path):
    """'a,, b ,' -> ('a', 'b'): пробелы срезаны, пустые сегменты отброшены."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="a,, b ,")
    assert plugin._sidecar_keys == ("a", "b")


def test_shutdown_after_failed_configure_does_not_raise(tmp_path):
    """configure с sidecar_keys='frame' -> ValueError; следом shutdown() (его зовёт фреймворк) не падает."""
    plugin = FrameSaverPlugin()
    ctx = make_ctx(tmp_path, sidecar_keys="frame")
    with pytest.raises(ValueError, match="frame"):
        call(plugin.configure, ctx)
    call(plugin.shutdown, ctx)  # без AttributeError на _lock / _saved_count


def test_reserved_keys_in_sidecar_keys_warn_once_in_configure(tmp_path):
    """Служебные ключи в sidecar_keys -> один log_warning в configure, без ValueError."""
    _, ctx = make_plugin(tmp_path, sidecar_keys="pick_xy, file, source")
    assert ctx.log_warning.call_count == 1
    msg = ctx.log_warning.call_args.args[0]
    assert "file" in msg and "source" in msg


# --- once-предупреждения ---


def test_collision_warning_once_per_node_lifetime(tmp_path):
    """Коллизия ключа с payload на каждом кадре -> ровно одна строка log_warning за жизнь узла."""
    plugin, ctx = make_plugin(tmp_path, sidecar_keys="track_id", save_every_n=1)
    for i in range(5):
        call(plugin.process, [make_item(i, track_id=100 + i)])
    assert len(list(tmp_path.glob("*.json"))) == 5
    assert ctx.log_warning.call_count == 1
    assert "track_id" in ctx.log_warning.call_args.args[0]


# --- конвертация значений ---


def test_self_referencing_value_skipped_with_one_warning(tmp_path):
    """Самоссылка в extras -> RecursionError не выходит из process(): ключ пропущен, остальные записаны."""
    plugin, ctx = make_plugin(tmp_path, sidecar_keys="loop, pick_xy")
    loop: dict = {"a": 1}
    loop["self"] = loop
    for i in range(2):
        call(plugin.process, [make_item(i, loop=loop, pick_xy={"x_mm": 1.0})])
    assert len(list(tmp_path.glob("*.jpg"))) == 2
    for sidecar in tmp_path.glob("*.json"):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        assert "loop" not in data
        assert data["pick_xy"] == {"x_mm": 1.0}
    assert ctx.log_warning.call_count == 1
    assert "loop" in ctx.log_warning.call_args.args[0]


def test_non_json_dict_keys_converted(tmp_path):
    """np.int64-ключ -> 1, tuple-ключ -> строка: .json записан целиком, не теряется на TypeError."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="pick_xy")
    call(plugin.process, [make_item(1, pick_xy={np.int64(1): 2.0, (1, 2): 3.0})])
    assert only_json(tmp_path)["pick_xy"] == {"1": 2.0, "(1, 2)": 3.0}


def test_tuple_recursed_into(tmp_path):
    """tuple внутри dict -> список с нативными значениями: (np.int64(3),) -> [3]."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="pick_xy")
    call(plugin.process, [make_item(1, pick_xy={"top": (np.int64(3),)})])
    data = only_json(tmp_path)
    assert data["pick_xy"] == {"top": [3]}
    assert isinstance(data["pick_xy"]["top"][0], int)


# --- порядок слияния ---


def test_frame_fields_and_register_source_override_extras(tmp_path):
    """sidecar_keys='file,width,source' + item с теми же ключами: file/width от кадра, source от регистра."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="file,width,source", sidecar_source="real")
    call(plugin.process, [make_item(1, file="evil.jpg", width=999, source="synthetic")])
    data = only_json(tmp_path)
    assert data["file"] == "frame_000001.jpg"
    assert data["width"] == 4
    assert data["source"] == "real"
