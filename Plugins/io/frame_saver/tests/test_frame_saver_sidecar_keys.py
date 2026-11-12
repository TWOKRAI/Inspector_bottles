"""Слепые приёмочные тесты Task 1.1a: регистры frame_saver `sidecar_keys` и `sidecar_source`.

Спека: plans/2026-11-11_dataset-sidecar-truth/design.md §4 (абзац «frame_saver»), §8.
Проверяется наблюдаемый эффект — содержимое .json на диске. Ожидаемые значения — литералы.

Допущение (см. отчёт): в каждом item есть payload под ключом `sidecar`, чтобы не зависеть
от неспецифицированного поведения «нет payload — пишется ли .json».
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from Plugins.io.frame_saver.plugin import FrameSaverPlugin

DEADLINE_S = 15.0


def _run_with_deadline(fn, *args, **kwargs):
    """Вызвать fn в daemon-потоке с дедлайном; исключение потока пробрасывается."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в тест как есть
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(DEADLINE_S)
    assert not t.is_alive(), f"{getattr(fn, '__name__', fn)} завис (> {DEADLINE_S} с)"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def make_plugin(tmp_path: Path, **overrides) -> FrameSaverPlugin:
    """Сконфигурированный плагин: output_dir=tmp_path, без подпапки даты, sidecar включён."""
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
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    _run_with_deadline(plugin.configure, ctx)
    return plugin


def make_item(**extra) -> dict:
    """item с кадром и payload под ключом `sidecar`; extra — ключи верхнего уровня."""
    item: dict = {
        "frame": np.zeros((4, 4, 3), dtype=np.uint8),
        "sidecar": {"track_id": 1},
    }
    item.update(extra)
    return item


def save_and_read(tmp_path: Path, item: dict, **overrides) -> dict:
    """Сохранить один item и вернуть содержимое единственного .json."""
    plugin = make_plugin(tmp_path, **overrides)
    _run_with_deadline(plugin.process, [item])
    jsons = sorted(tmp_path.glob("*.json"))
    assert len(jsons) == 1, f"ожидался ровно один .json, найдено: {[p.name for p in jsons]}"
    return json.loads(jsons[0].read_text(encoding="utf-8"))


def test_nested_numpy_written_as_native(tmp_path):
    """np.float32/np.int64 на глубине dict/list → в .json нативные float / int."""
    item = make_item(predictions=[{"label": "Ж", "confidence": np.float32(0.97), "top": [np.int64(3)]}])
    data = save_and_read(tmp_path, item, sidecar_keys="predictions")
    pred = data["predictions"][0]
    assert pred["label"] == "Ж"
    assert isinstance(pred["confidence"], float)
    assert abs(pred["confidence"] - 0.97) < 1e-6
    assert pred["top"] == [3]


def test_listed_keys_copied(tmp_path):
    """sidecar_keys 'predictions, pick_xy' (с пробелом) → оба ключа в .json под своим именем."""
    item = make_item(
        predictions=[{"label": "A", "confidence": 0.5}],
        pick_xy={"x_mm": 450.5, "y_mm": -330.0},
    )
    data = save_and_read(tmp_path, item, sidecar_keys="predictions, pick_xy")
    assert "predictions" in data
    assert data["pick_xy"] == {"x_mm": 450.5, "y_mm": -330.0}


def test_missing_key_absent(tmp_path):
    """Ключ перечислен, но в item его нет → в .json ключа нет (не null)."""
    item = make_item(pick_xy={"x_mm": 1.0, "y_mm": 2.0})
    data = save_and_read(tmp_path, item, sidecar_keys="model_id, pick_xy")
    assert "model_id" not in data
    # якорь против вырожденного прохода: перечисленный и присутствующий ключ скопирован
    assert data["pick_xy"] == {"x_mm": 1.0, "y_mm": 2.0}


def test_source_written_only_when_set(tmp_path):
    """sidecar_source='synthetic' → "source": "synthetic"; '' → ключа source нет."""
    with_source = save_and_read(tmp_path / "set", make_item(), sidecar_source="synthetic")
    assert with_source["source"] == "synthetic"
    without = save_and_read(tmp_path / "empty", make_item(), sidecar_source="")
    assert "source" not in without


def test_defaults_keep_old_key_set(tmp_path):
    """Регистры по умолчанию: ровно старый набор ключей, ключа sidecar нет."""
    item = {
        "frame": np.zeros((4, 4, 3), dtype=np.uint8),
        "sidecar": {"track_id": 7, "frame_id": 41},
    }
    data = save_and_read(tmp_path, item)
    assert set(data) == {"track_id", "frame_id", "file", "width", "height", "saved_ts"}
    assert "sidecar" not in data


@pytest.mark.parametrize(
    ("overrides", "bad_key"),
    [
        ({"sidecar_keys": "frame"}, "frame"),
        ({"sidecar_keys": "predictions, frame"}, "frame"),
        ({"sidecar_keys": "sidecar"}, "sidecar"),
        ({"sidecar_key": "meta", "sidecar_keys": "meta"}, "meta"),
    ],
    ids=["frame", "frame_in_list", "default_sidecar_key", "custom_sidecar_key"],
)
def test_frame_and_sidecar_key_rejected(tmp_path, overrides, bad_key):
    """`frame` или значение sidecar_key в sidecar_keys → ValueError в configure, имя ключа в сообщении."""
    with pytest.raises(ValueError, match=bad_key):
        make_plugin(tmp_path, **overrides)


def test_collision_keeps_payload(tmp_path):
    """Ключ занят в payload → значение payload, extras пропущен."""
    item = {
        "frame": np.zeros((4, 4, 3), dtype=np.uint8),
        "sidecar": {"track_id": 7},
        "track_id": 9,
    }
    data = save_and_read(tmp_path, item, sidecar_keys="track_id")
    assert data["track_id"] == 7


def test_ndarray_value_skipped(tmp_path):
    """ndarray в extras → ключа в .json нет, изображение при этом сохранено."""
    item = make_item(mask=np.zeros((2, 2)), pick_xy={"x_mm": 1.0, "y_mm": 2.0})
    data = save_and_read(tmp_path, item, sidecar_keys="mask, pick_xy")
    assert "mask" not in data
    assert data["pick_xy"] == {"x_mm": 1.0, "y_mm": 2.0}
    assert len(list(tmp_path.glob("*.jpg"))) == 1


def test_ndarray_nested_skipped_whole_key(tmp_path):
    """Доп. (спека: «на любой глубине»): ndarray внутри list/dict → пропущен весь ключ верхнего уровня."""
    item = make_item(predictions=[{"label": "A", "crop": np.zeros((2, 2))}], pick_xy={"x_mm": 1.0, "y_mm": 2.0})
    data = save_and_read(tmp_path, item, sidecar_keys="predictions, pick_xy")
    assert "predictions" not in data
    assert data["pick_xy"] == {"x_mm": 1.0, "y_mm": 2.0}
    assert len(list(tmp_path.glob("*.jpg"))) == 1
