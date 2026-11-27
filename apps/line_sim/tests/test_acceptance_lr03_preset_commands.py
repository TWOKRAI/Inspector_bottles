# -*- coding: utf-8 -*-
"""Слепая приёмка ЛР-03 (критерии 6-8), написана ДО реализации.

Пресет без `catalog_dir` из одних слоёв `mode="defect"` на уровне команд плагинов:
`preset.commit` сцены, `preset.preview` / `preset.layout` превью и `configure` сцены.
Файл живёт в `apps/`: `Services` не имеет права импортировать `Plugins`.

Плохие пресеты заданы сырыми dict/YAML (после реализации конструктор `ScenePreset` их не соберёт).
Ответ команды несёт `str(exc)`, а тот повторяет `input_value`; эхо вырезается перед проверкой слов,
и отдельно проверяется, что во входе слова `static` нет. Имена тестов намеренно не содержат это
слово: имя теста попадает в `tmp_path`, а путь — в `base_dir` и в эхо.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.layer_render import imwrite_unicode

FRAME_W = 64
FRAME_H = 64


# --------------------------------------------------------------------------- #
# Помощники                                                                   #
# --------------------------------------------------------------------------- #


class _FakeStateProxy:
    """Минимальная замена ``StateProxy``: копит подписчиков и раздаёт им дельты."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for callback in self._callbacks:
            callback(deltas)

    def set(self, path: str, value: object) -> None:
        pass


def _emit_encoder(proxy: _FakeStateProxy, value: float, t: float) -> None:
    proxy.emit([Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value, "t": t}, source="robot")])


def _write_sprite(path: Path) -> None:
    """Непрозрачный квадрат 30x30, чисто красный (порядок каналов файла — BGRA)."""
    sprite = np.zeros((30, 30, 4), dtype=np.uint8)
    sprite[:, :, 2] = 255
    sprite[:, :, 3] = 255
    imwrite_unicode(path, sprite)


def _good_preset_dict() -> dict:
    return {
        "angle_range_deg": [0.0, 0.0],
        "layers": [{"name": "disk", "mode": "static", "sprite_source": "spot.png"}],
    }


def _bad_preset_dict() -> dict:
    """Без `catalog_dir`, единственный слой — брак, который не выпадает (вероятность 0.0)."""
    return {
        "catalog_dir": None,
        "angle_range_deg": [0.0, 0.0],
        "layers": [{"name": "scratch_zz", "mode": "defect", "sprite_source": "spot.png"}],
    }


def _write_preset(directory: Path, data: dict, filename: str = "preset.yaml") -> Path:
    _write_sprite(directory / "spot.png")
    path = directory / filename
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _new_scene(preset_path: Path) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = proxy
    ctx.config = {
        "resolution_width": FRAME_W,
        "resolution_height": FRAME_H,
        "px_per_mm": 1.0,
        "belt_y_px": FRAME_H / 2,
        "spawn_interval_s": [0.01, 0.02],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(preset_path),
        "seed": 0,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, proxy


def _new_preview(preset_path: Path) -> LayerPreviewPlugin:
    ctx = MagicMock()
    ctx.config = {"preset_path": str(preset_path)}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _call(plugin: Any, name: str, data: dict | None = None) -> dict:
    """Вызов команды через карту `plugin.commands`, как это делает роутер."""
    assert name in plugin.commands, f"команды '{name}' нет в plugin.commands"
    return getattr(plugin, plugin.commands[name])(dict(data or {}))


def _without_echo(message: str) -> str:
    """Убрать хвост pydantic `[type=..., input_value=..., input_type=...]`."""
    return re.sub(r"\[type=.*?input_type=\w+\]", "", message, flags=re.S)


def _tick_errors(ctx: MagicMock) -> list[str]:
    return [str(call) for call in ctx.log_error.call_args_list if "spawner.tick()" in str(call)]


# --------------------------------------------------------------------------- #
# Критерий 6: preset.commit на живой сцене                                    #
# --------------------------------------------------------------------------- #


def _commit_bad(tmp_path: Path) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy, Path, bytes, dict]:
    preset_path = _write_preset(tmp_path, _good_preset_dict())
    plugin, ctx, proxy = _new_scene(preset_path)
    assert _call(plugin, "scene.status")["flow"] != {}, f"движок не собрался (фикстура): {ctx.log_error.call_args_list}"
    before = preset_path.read_bytes()
    reply = _call(
        plugin,
        "preset.commit",
        {"preset": _bad_preset_dict(), "base_rev": hashlib.sha256(before).hexdigest()},
    )
    return plugin, ctx, proxy, preset_path, before, reply


def test_ac6_commit_reply_is_invalid_and_names_the_allowed_modes(tmp_path: Path) -> None:
    assert "static" not in str(tmp_path), "путь фикстуры сделал бы проверку слова пустой"
    _plugin, _ctx, _proxy, _path, _before, reply = _commit_bad(tmp_path)
    assert reply["status"] == "error", reply
    assert reply["code"] == "invalid", reply
    assert "static" in _without_echo(reply["message"]), reply["message"]


def test_ac6_commit_leaves_file_bytes_unchanged(tmp_path: Path) -> None:
    _plugin, _ctx, _proxy, preset_path, before, _reply = _commit_bad(tmp_path)
    assert preset_path.read_bytes() == before


def test_ac6_old_factory_keeps_spawning_after_commit(tmp_path: Path) -> None:
    # До commit ни одного produce(): любой объект ниже порождён уже ПОСЛЕ команды.
    plugin, ctx, proxy, _path, _before, _reply = _commit_bad(tmp_path)
    assert _call(plugin, "scene.status")["active"] == 0

    saw_red = False
    for i in range(200):
        _emit_encoder(proxy, 5.0 * (i + 1), float(i))
        frame = plugin.produce()[0]["frame"]
        # кадр BGR: красный спрайт старого пресета
        saw_red = saw_red or bool(np.any((frame[..., 2] > 200) & (frame[..., 1] < 40) & (frame[..., 0] < 40)))
        if saw_red and i >= 10:
            break
        time.sleep(0.005)

    assert _tick_errors(ctx) == [], "spawner.tick() падает после отклонённого commit"
    assert _call(plugin, "scene.status")["active"] >= 1
    assert saw_red, "объект старого пресета не появился в кадре"


# --------------------------------------------------------------------------- #
# Критерий 7: preset.preview / preset.layout                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", ["preset.preview", "preset.layout"])
def test_ac7_control_good_preset_is_ok(tmp_path: Path, command: str) -> None:
    plugin = _new_preview(_write_preset(tmp_path, _good_preset_dict()))
    reply = _call(plugin, command, {"preset": _good_preset_dict()})
    assert reply["status"] == "ok", reply


def _assert_clear_refusal(reply: dict) -> None:
    assert reply["status"] == "error", reply
    assert reply["code"] == "invalid", reply
    message = _without_echo(reply["message"])
    assert "static" in message, reply["message"]
    assert "max()" not in message, reply["message"]


@pytest.mark.parametrize("command", ["preset.preview", "preset.layout"])
def test_ac7_client_preset_refused_with_clear_text(tmp_path: Path, command: str) -> None:
    assert "static" not in str(tmp_path), "путь фикстуры сделал бы проверку слова пустой"
    plugin = _new_preview(_write_preset(tmp_path, _good_preset_dict()))
    _assert_clear_refusal(_call(plugin, command, {"preset": _bad_preset_dict()}))


@pytest.mark.parametrize("command", ["preset.preview", "preset.layout"])
def test_ac7_configured_file_refused_with_clear_text(tmp_path: Path, command: str) -> None:
    assert "static" not in str(tmp_path), "путь фикстуры сделал бы проверку слова пустой"
    plugin = _new_preview(_write_preset(tmp_path, _bad_preset_dict()))
    _assert_clear_refusal(_call(plugin, command))


# --------------------------------------------------------------------------- #
# Критерий 8: configure с таким файлом                                        #
# --------------------------------------------------------------------------- #


def test_ac8_configure_survives_and_defect_now_is_not_applied(tmp_path: Path) -> None:
    plugin, _ctx, _proxy = _new_scene(_write_preset(tmp_path, _bad_preset_dict()))
    reply = _call(plugin, "scene.defect_now")
    assert reply["status"] == "ok", reply
    assert reply.get("applied") is False, f"движок собран из пресета, который нечем рисовать: {reply}"


def test_ac8_status_reports_no_engine(tmp_path: Path) -> None:
    plugin, _ctx, _proxy = _new_scene(_write_preset(tmp_path, _bad_preset_dict()))
    status = _call(plugin, "scene.status")
    assert status["flow"] == {}, status


def test_ac8_frame_is_plain_background(tmp_path: Path) -> None:
    plugin, ctx, proxy = _new_scene(_write_preset(tmp_path, _bad_preset_dict()))
    for i in range(10):
        _emit_encoder(proxy, 5.0 * (i + 1), float(i))
        frame = plugin.produce()[0]["frame"]
        assert frame.shape == (64, 64, 3)
        assert np.unique(frame).tolist() == [60], f"кадр {i} — не чистый фон"
        time.sleep(0.025)
    assert _tick_errors(ctx) == [], "spawner.tick() падает на кадрах"
