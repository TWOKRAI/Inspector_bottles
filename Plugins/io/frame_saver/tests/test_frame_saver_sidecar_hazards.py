"""Hazard-тесты Task 1.1a: гонка save_now/process, once-предупреждение, разбор sidecar_keys.

Авторские тесты разработчика (слепая приёмка — в test_frame_saver_sidecar_keys.py).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from Plugins.io.frame_saver.plugin import FrameSaverPlugin

JOIN_DEADLINE_S = 5.0


def make_plugin(tmp_path: Path, **overrides) -> tuple[FrameSaverPlugin, MagicMock]:
    """Сконфигурированный плагин + его ctx (для проверки log_warning)."""
    cfg: dict = {
        "output_dir": str(tmp_path),
        "subfolder_by_date": False,
        "write_sidecar": True,
        "index_source": "counter",
    }
    cfg.update(overrides)
    plugin = FrameSaverPlugin()
    ctx = MagicMock()
    ctx.config = cfg
    ctx.registers = None
    plugin.configure(ctx)
    return plugin, ctx


def make_item(i: int, **extra) -> dict:
    item: dict = {"frame": np.zeros((4, 4, 3), dtype=np.uint8), "sidecar": {"track_id": i}}
    item.update(extra)
    return item


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
    plugin._cmd_save_now({})  # добираем остаток буфера

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


def test_collision_warning_once_per_node_lifetime(tmp_path):
    """Коллизия ключа с payload на каждом кадре -> ровно одна строка log_warning за жизнь узла."""
    plugin, ctx = make_plugin(tmp_path, sidecar_keys="track_id", save_every_n=1)
    for i in range(5):
        plugin.process([make_item(i, track_id=100 + i)])
    assert len(list(tmp_path.glob("*.json"))) == 5
    assert ctx.log_warning.call_count == 1
    assert "track_id" in ctx.log_warning.call_args.args[0]


def test_sidecar_keys_parsing_strips_and_drops_empty(tmp_path):
    """'a,, b ,' -> ('a', 'b'): пробелы срезаны, пустые сегменты отброшены."""
    plugin, _ = make_plugin(tmp_path, sidecar_keys="a,, b ,")
    assert plugin._sidecar_keys == ("a", "b")
