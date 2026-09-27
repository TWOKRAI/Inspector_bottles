# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 1.2a (независимый тестер, ДО реализации) — команды пресета
`scene_source`: `preset.get` / `preset.commit` / `preset.preview`, горячая подмена на
живой ленте. Источник контракта — `plans/line-sim-layer-editor.md`, раздел «Устройство»
и критерии P1-P8 Task 1.2a; спецификация не смотрела в реализацию (её ещё нет).

Плагин собирается через фейковый `ctx` (паттерн — `test_scene_source_hazards_1_1b.py`,
единственный разрешённый образец гармонии). Команды вызываются НЕ по прямому имени
метода, а через карту `plugin.commands["<имя>"] -> имя метода -> getattr(...)`, как
велел лид: если карты нет или ключа нет — это и есть RED-причина этой задачи, гасим
её явным `assert` с текстом, а не `KeyError`/`AttributeError` наружу.

`rev` — ЛИТЕРАЛ: `hashlib.sha256(path.read_bytes()).hexdigest()`, посчитанный тестом из
файла напрямую, никогда не из ответа плагина (иначе тест согласится с любым значением).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset

pytestmark = pytest.mark.timeout(30)

FRAME_W = 64
FRAME_H = 64


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — копия паттерна `test_scene_source_hazards_1_1b.py`."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


def _emit_encoder(state_proxy: _FakeStateProxy, value: float, t: float) -> None:
    state_proxy.emit(
        [Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value, "t": t}, source="robot")]
    )


def _count_red_px(frame_bgr: np.ndarray) -> int:
    """Пиксели, близкие к чистому красному в BGR (кадры плагина — BGR, README)."""
    b = frame_bgr[..., 0].astype(int)
    g = frame_bgr[..., 1].astype(int)
    r = frame_bgr[..., 2].astype(int)
    mask = (b < 60) & (g < 60) & (r > 200)
    return int(mask.sum())


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Каталог классов `cat/<A|B>/0.png` (чёрные квадраты-заглушки 30x30) + `disk.png`
    (белый 60x60) + `preset.yaml` рядом: диск (`static`, `color_rgb` белый) снизу, буква
    (`class://`, `color_rgb` чёрный) сверху, `angle_range_deg=[0, 0]` — угол ОБЪЕКТА
    зафиксирован, не мешает счёту красных пикселей. Возвращает (preset_path, catalog_dir).
    """
    catalog_dir = tmp_path / "cat"
    for cls in ("A", "B"):
        class_dir = catalog_dir / cls
        class_dir.mkdir(parents=True)
        sprite = np.zeros((30, 30, 4), dtype=np.uint8)
        sprite[:, :, :3] = 128
        sprite[:, :, 3] = 255
        imwrite_unicode(class_dir / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    disk_path = tmp_path / "disk.png"
    disk = np.zeros((60, 60, 4), dtype=np.uint8)
    disk[:, :, :3] = 255
    disk[:, :, 3] = 255
    imwrite_unicode(disk_path, cv2.cvtColor(disk, cv2.COLOR_RGBA2BGRA))

    preset = ScenePreset(
        catalog_dir=str(catalog_dir),
        angle_range_deg=(0.0, 0.0),
        defect_probability=0.0,
        layers=[
            LayerSpec(name="disk", mode="static", sprite_source=str(disk_path), color_rgb=(255, 255, 255)),
            LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE, color_rgb=(0, 0, 0)),
        ],
    )
    preset_path = tmp_path / "preset.yaml"
    preset.to_yaml(preset_path)
    return preset_path, catalog_dir


def _base_cfg(preset_path_cfg: Path) -> dict:
    return {
        "resolution_width": FRAME_W,
        "resolution_height": FRAME_H,
        "px_per_mm": 1.0,
        "belt_y_px": FRAME_H / 2,
        "spawn_interval_s": [0.01, 0.02],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(preset_path_cfg),
        "seed": 0,
    }


def _new_plugin(preset_path_cfg: Path) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    """Собирает и стартует плагин; двигатель ОБЯЗАН собраться (иначе фикстура сама
    сломана — это не должно маскироваться под RED задачи)."""
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = _base_cfg(preset_path_cfg)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался (фикстура): {ctx.log_error.call_args_list}"
    plugin.start(ctx)
    return plugin, ctx, state_proxy


def _call_command(plugin: SceneSourcePlugin, name: str, data: dict) -> dict:
    """Единственная точка вызова команд — через карту `plugin.commands`, как велел лид.
    Отсутствие команды/карты — это RED-причина задачи 1.2a, гасим явным `assert`."""
    commands = getattr(plugin, "commands", None)
    assert commands is not None and name in commands, (
        f"команда '{name}' отсутствует в plugin.commands ({commands!r}) — "
        "preset.get/preset.commit/preset.preview ещё не реализованы (Task 1.2a)"
    )
    method_name = commands[name]
    method = getattr(plugin, method_name, None)
    assert method is not None, f"plugin.commands['{name}'] указывает на несуществующий метод '{method_name}'"
    return method(dict(data))


# --- GREEN-контроль: фикстура сама по себе рабочая (README: движок собран, кадры идут) ---


def test_control_fixture_engine_ready_and_produces_frames(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, state_proxy = _new_plugin(preset_path)
    assert plugin._compositor is not None
    _emit_encoder(state_proxy, 5.0, 0.0)
    items = plugin.produce()
    assert items[0]["frame"].shape == (FRAME_H, FRAME_W, 3)


# --- P1 ---


def test_p1_get_returns_file_preset_and_sha_rev(tmp_path: Path) -> None:
    preset_path, catalog_dir = _make_fixture(tmp_path)

    plugin, _ctx, _sp = _new_plugin(preset_path)
    result = _call_command(plugin, "preset.get", {})
    assert result["status"] == "ok", result

    expected_rev = hashlib.sha256(preset_path.read_bytes()).hexdigest()
    assert result["rev"] == expected_rev, "rev ответа должен быть sha256 байт файла, посчитанным тестом"
    assert Path(result["path"]).resolve() == preset_path.resolve(), result["path"]

    expected_preset = ScenePreset.from_yaml(preset_path).to_dict()
    assert result["preset"] == expected_preset, "preset ответа должен быть ScenePreset.from_yaml(файл).to_dict()"

    # плагин из каталога (не .yaml) — rev/path недоступны
    plugin_catalog, _ctx2, _sp2 = _new_plugin(catalog_dir)
    result_catalog = _call_command(plugin_catalog, "preset.get", {})
    assert result_catalog["status"] == "ok", result_catalog
    assert result_catalog["rev"] is None, "плагин из каталога — rev is None"
    assert result_catalog["path"] is None, "плагин из каталога — path is None"


# --- P2 ---


def test_p2_commit_fresh_rev_writes_file_and_new_rev(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, _sp = _new_plugin(preset_path)

    original = ScenePreset.from_yaml(preset_path)
    original_disk_source = original.layers[0].sprite_source
    original_letter_source = original.layers[1].sprite_source

    base_rev = hashlib.sha256(preset_path.read_bytes()).hexdigest()
    preset_dict = original.to_dict()
    preset_dict["layers"][0]["color_rgb"] = [255, 0, 0]  # диск -> красный

    result = _call_command(plugin, "preset.commit", {"preset": preset_dict, "base_rev": base_rev})
    assert result["status"] == "ok", result

    new_bytes = preset_path.read_bytes()
    expected_new_rev = hashlib.sha256(new_bytes).hexdigest()
    assert result["rev"] == expected_new_rev, "rev ответа должен быть sha256 НОВЫХ байт файла"
    assert result["rev"] != base_rev

    reloaded = ScenePreset.from_yaml(preset_path)
    assert tuple(reloaded.layers[0].color_rgb) == (255, 0, 0), "файл, перечитанный from_yaml, должен нести новый цвет"
    assert reloaded.layers[0].sprite_source == original_disk_source, "строки путей в файле должны остаться теми же"
    assert reloaded.layers[1].sprite_source == original_letter_source


# --- P3 ---


def test_p3_stale_rev_conflict_and_single_winner(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, _sp = _new_plugin(preset_path)

    before_bytes = preset_path.read_bytes()
    stale_rev = hashlib.sha256(b"this is not the real file content").hexdigest()
    assert stale_rev != hashlib.sha256(before_bytes).hexdigest()

    preset_dict = ScenePreset.from_yaml(preset_path).to_dict()
    preset_dict["layers"][0]["color_rgb"] = [255, 0, 0]
    result = _call_command(plugin, "preset.commit", {"preset": preset_dict, "base_rev": stale_rev})
    assert result["status"] == "error" and result.get("code") == "conflict", result
    current_rev = hashlib.sha256(before_bytes).hexdigest()
    assert result.get("current_rev") == current_rev, result
    assert preset_path.read_bytes() == before_bytes, "байты файла не должны были измениться при conflict"

    # два потока, один общий свежий base_rev -> ровно один победитель
    base_rev = hashlib.sha256(preset_path.read_bytes()).hexdigest()
    base_preset_dict = ScenePreset.from_yaml(preset_path).to_dict()
    results: dict[str, object] = {}

    def _worker(key: str, color: list[int]) -> None:
        try:
            preset_dict_local = copy.deepcopy(base_preset_dict)
            preset_dict_local["layers"][0]["color_rgb"] = color
            results[key] = _call_command(plugin, "preset.commit", {"preset": preset_dict_local, "base_rev": base_rev})
        except BaseException as exc:  # прокидываем через results — поток не должен молча проглатывать
            results[key] = exc

    t1 = threading.Thread(target=_worker, args=("t1", [255, 0, 0]), daemon=True)
    t2 = threading.Thread(target=_worker, args=("t2", [0, 255, 0]), daemon=True)
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive() and not t2.is_alive(), "commit завис — гонка не разрешилась за 10с (P3)"

    for key in ("t1", "t2"):
        if isinstance(results.get(key), BaseException):
            raise results[key]  # type: ignore[misc]

    statuses = [results["t1"]["status"], results["t2"]["status"]]  # type: ignore[index]
    assert statuses.count("ok") == 1, f"ожидался ровно один победитель commit с общим base_rev: {results}"
    assert statuses.count("error") == 1, results
    loser = results["t1"] if results["t1"]["status"] == "error" else results["t2"]  # type: ignore[index]
    assert loser["code"] == "conflict", loser  # type: ignore[index]


# --- P4 ---


def test_p4_invalid_preset_rejected_file_untouched_frames_continue(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, state_proxy = _new_plugin(preset_path)

    before_bytes = preset_path.read_bytes()
    base_rev = hashlib.sha256(before_bytes).hexdigest()

    # два слоя class:// -> invalid, имя слоя в тексте
    dup = ScenePreset.from_yaml(preset_path).to_dict()
    dup["layers"][0]["sprite_source"] = CLASS_SPRITE_SOURCE
    dup["layers"][0]["name"] = "letter2"
    result_dup = _call_command(plugin, "preset.commit", {"preset": dup, "base_rev": base_rev})
    assert result_dup["status"] == "error" and result_dup.get("code") == "invalid", result_dup
    message = result_dup.get("message", "")
    assert any(name in message for name in ("letter2", "letter", "disk")), (
        f"текст ошибки должен называть имя слоя: {message!r}"
    )
    assert preset_path.read_bytes() == before_bytes

    # несуществующая картинка слоя -> invalid
    missing = ScenePreset.from_yaml(preset_path).to_dict()
    missing["layers"][0]["sprite_source"] = "does_not_exist_at_all.png"
    result_missing = _call_command(plugin, "preset.commit", {"preset": missing, "base_rev": base_rev})
    assert result_missing["status"] == "error" and result_missing.get("code") == "invalid", result_missing
    assert preset_path.read_bytes() == before_bytes

    # produce() продолжает давать кадры после обоих отказов
    _emit_encoder(state_proxy, 5.0, 0.0)
    items = plugin.produce()
    assert items[0]["frame"].shape == (FRAME_H, FRAME_W, 3), "produce() должен продолжать работать после invalid commit"


# --- P5 ---


def test_p5_hot_swap_recolors_new_objects_without_restart(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, state_proxy = _new_plugin(preset_path)

    encoder = 0.0
    found_red_before = False
    for i in range(15):
        encoder += 5.0
        _emit_encoder(state_proxy, encoder, float(i))
        frame = plugin.produce()[0]["frame"]
        if _count_red_px(frame) > 0:
            found_red_before = True
        time.sleep(0.005)
    assert not found_red_before, "до commit диск белый — красных пикселей быть не должно"

    base_rev = hashlib.sha256(preset_path.read_bytes()).hexdigest()
    preset_dict = ScenePreset.from_yaml(preset_path).to_dict()
    preset_dict["layers"][0]["color_rgb"] = [255, 0, 0]
    result = _call_command(plugin, "preset.commit", {"preset": preset_dict, "base_rev": base_rev})
    assert result["status"] == "ok", result

    cap = 400
    found_red_after = False
    for i in range(cap):
        encoder += 5.0
        _emit_encoder(state_proxy, encoder, float(15 + i))
        frame = plugin.produce()[0]["frame"]
        if _count_red_px(frame) > 0:
            found_red_after = True
            break
        time.sleep(0.01)
    assert found_red_after, f"новый объект с красным диском не появился за {cap} кадров после commit (без рестарта)"


# --- P6 ---


def test_p6_preview_grid_and_no_effect_on_frames(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin_a, _ctx_a, sp_a = _new_plugin(preset_path)
    plugin_b, _ctx_b, sp_b = _new_plugin(preset_path)

    def _step(enc: float, t: float) -> tuple[np.ndarray, np.ndarray]:
        _emit_encoder(sp_a, enc, t)
        _emit_encoder(sp_b, enc, t)
        frame_a = plugin_a.produce()[0]["frame"]
        frame_b = plugin_b.produce()[0]["frame"]
        return frame_a, frame_b

    for i, enc in enumerate((0.0, 5.0, 10.0)):
        fa, fb = _step(enc, float(i))
        assert np.array_equal(fa, fb), f"два одинаковых инстанса разошлись ДО preview на шаге {i}"

    result = _call_command(plugin_a, "preset.preview", {"seeds": [1, 2, 3, 4]})
    assert result["status"] == "ok", result

    png_bytes = base64.b64decode(result["png_b64"])
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None and img.size > 0, "png_b64 должен декодироваться в валидное изображение"

    tiles = result["tiles"]
    assert [t["seed"] for t in tiles] == [1, 2, 3, 4], f"порядок tiles должен совпадать с порядком seeds: {tiles}"
    for tile in tiles:
        assert "class_name" in tile and "layer_params" in tile, tile

    for i, enc in enumerate((15.0, 20.0, 25.0), start=3):
        fa, fb = _step(enc, float(i))
        assert np.array_equal(fa, fb), f"preview повлиял на последующие кадры (побитовое расхождение) на шаге {i}"


# --- P7 ---


def test_p7_preview_unsaved_preset_and_limits(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, _sp = _new_plugin(preset_path)

    before_bytes = preset_path.read_bytes()

    unsaved = ScenePreset.from_yaml(preset_path).to_dict()
    unsaved["layers"][0]["color_rgb"] = [255, 0, 0]
    result_unsaved = _call_command(plugin, "preset.preview", {"preset": unsaved, "seeds": [1]})
    assert result_unsaved["status"] == "ok", result_unsaved
    assert preset_path.read_bytes() == before_bytes, "preview с несохранённым preset не должен трогать файл"

    too_many_seeds = list(range(17))
    result_seeds = _call_command(plugin, "preset.preview", {"seeds": too_many_seeds})
    assert result_seeds["status"] == "error" and result_seeds.get("code") == "bad_request", result_seeds

    result_tile = _call_command(plugin, "preset.preview", {"seeds": [1], "tile_px": 257})
    assert result_tile["status"] == "error" and result_tile.get("code") == "bad_request", result_tile

    assert preset_path.read_bytes() == before_bytes, "bad_request preview не должен трогать файл"


# --- P8 ---


def test_p8_catalog_plugin_commit_bad_request(tmp_path: Path) -> None:
    preset_path, catalog_dir = _make_fixture(tmp_path)
    plugin, _ctx, _sp = _new_plugin(catalog_dir)  # preset_path конфига = каталог, не .yaml

    before_files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())

    preset_dict = ScenePreset.from_yaml(preset_path).to_dict()
    result = _call_command(plugin, "preset.commit", {"preset": preset_dict, "base_rev": "irrelevant"})
    assert result["status"] == "error" and result.get("code") == "bad_request", result

    after_files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert after_files == before_files, "commit на плагине из каталога не должен ничего писать на диск"
