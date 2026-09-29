# -*- coding: utf-8 -*-
"""Тесты `LayerPreviewPlugin` — `preset.preview` в своём процессе `layers` (ревью 1.2a S1).

Перенесено из приёмки тестера 1.2a, хост превью сменился — ревью S1:
`test_p6_*` / `test_p7_*` — из `Plugins/sim/scene_source/tests/test_acceptance_1_2a_preset_commands.py`
(каждое утверждение сохранено; P6 «превью не влияет на кадры сцены» теперь означает: кадры
`SceneSourcePlugin` побитово те же при любом числе превью на `LayerPreviewPlugin` с тем же файлом).
Hazard-тесты автора (бюджет пикселей, ограда путей S3, кэш/смена файла, форс-брак) — из
`test_scene_source_hazards_1_2a.py`.

Команды вызываются через карту `plugin.commands`, как у тестера.
"""

from __future__ import annotations

import base64
import copy
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

FRAME_W = 64
FRAME_H = 64


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        pass


def _emit_encoder(state_proxy: _FakeStateProxy, value: float, t: float) -> None:
    state_proxy.emit(
        [Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value, "t": t}, source="robot")]
    )


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Фикстура тестера 1.2a без изменений: `cat/<A|B>/0.png` + `disk.png` + `preset.yaml`."""
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


#: Поток объектов ПО ЭНКОДЕРУ (`spawn_spacing_mm`): кадр — чистая функция (пресет, seed, энкодер).
#: Поток по времени (`spawn_interval_s`) считает срок спавна по `time.monotonic()` в
#: `produce()` — два инстанса, вызванные один за другим, видят РАЗНЫЕ часы и спавнят на разных
#: шагах; для сравнения кадров двух инстансов он не годится (флейк p6: 8 расхождений из 1000
#: прогонов в одном процессе без единого превью, замер 2026-09-29).
_SPACING_FLOW = {"spawn_spacing_mm": [4.0, 6.0]}
_INTERVAL_FLOW = {"spawn_interval_s": [0.01, 0.02]}


def _new_scene(preset_path_cfg: Path, flow: dict | None = None) -> tuple[SceneSourcePlugin, _FakeStateProxy]:
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": FRAME_W,
        "resolution_height": FRAME_H,
        "px_per_mm": 1.0,
        "belt_y_px": FRAME_H / 2,
        **(flow if flow is not None else _INTERVAL_FLOW),
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(preset_path_cfg),
        "seed": 0,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался (фикстура): {ctx.log_error.call_args_list}"
    plugin.start(ctx)
    return plugin, state_proxy


def _new_preview(preset_path_cfg: Path | str | None, **extra):
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    ctx = MagicMock()
    ctx.config = {"preset_path": None if preset_path_cfg is None else str(preset_path_cfg), **extra}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _call_command(plugin, name: str, data: dict) -> dict:
    commands = getattr(plugin, "commands", None)
    assert commands is not None and name in commands, f"команда '{name}' отсутствует в plugin.commands ({commands!r})"
    method = getattr(plugin, commands[name], None)
    assert method is not None, f"plugin.commands['{name}'] указывает на несуществующий метод"
    return method(dict(data))


def _decode(result: dict) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(base64.b64decode(result["png_b64"]), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.size > 0
    return img


# --- P6 (перенесено из приёмки тестера) ---


#: p6: 30 шагов по 5 отсчётов энкодера. Спавны spacing-потока (шаг 4-6 мм, 0.72 мм на шаг) — на
#: шагах 0, 8, 14, 23 (замер): превью вызываются после шага 5, так что три спавна из четырёх
#: происходят ПОСЛЕ превью — побочный эффект превью на рождение объектов виден.
_P6_STEPS = 30
_P6_PREVIEW_AFTER = 5


def _p6_run(plugin: SceneSourcePlugin, sp: _FakeStateProxy, steps: range) -> list[np.ndarray]:
    frames = []
    for i in steps:
        _emit_encoder(sp, i * 5.0, float(i))
        frames.append(plugin.produce()[0]["frame"])
    return frames


def test_p6_preview_grid_and_no_effect_on_frames(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    # Эталон записан ДО любого превью на отдельном инстансе (spacing-поток — чистая функция
    # пресета, seed и энкодера): симметричный побочный эффект превью, задевающий и «тот же»
    # инстанс, и сравниваемый с ним, сравнением двух живых инстансов не виден.
    ref_plugin, ref_sp = _new_scene(preset_path, _SPACING_FLOW)
    reference = _p6_run(ref_plugin, ref_sp, range(_P6_STEPS))

    plugin, sp = _new_scene(preset_path, _SPACING_FLOW)
    preview = _new_preview(preset_path)

    before = _p6_run(plugin, sp, range(_P6_PREVIEW_AFTER + 1))
    for i, frame in enumerate(before):
        assert np.array_equal(frame, reference[i]), f"инстанс разошёлся с эталоном ДО preview на шаге {i}"

    for _ in range(3):  # любое число превью
        result = _call_command(preview, "preset.preview", {"seeds": [1, 2, 3, 4]})
        assert result["status"] == "ok", result

        png_bytes = base64.b64decode(result["png_b64"])
        img = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert img is not None and img.size > 0, "png_b64 должен декодироваться в валидное изображение"

        tiles = result["tiles"]
        assert [t["seed"] for t in tiles] == [1, 2, 3, 4], f"порядок tiles должен совпадать с порядком seeds: {tiles}"
        for tile in tiles:
            assert "class_name" in tile and "layer_params" in tile, tile

    spawned_before = len(plugin._spawner.active_objects())
    after = _p6_run(plugin, sp, range(_P6_PREVIEW_AFTER + 1, _P6_STEPS))
    assert len(plugin._spawner.active_objects()) > spawned_before, "после превью не было ни одного спавна — окно пустое"
    for i, frame in enumerate(after, start=_P6_PREVIEW_AFTER + 1):
        assert np.array_equal(frame, reference[i]), (
            f"preview повлиял на последующие кадры (расхождение с эталоном) на шаге {i}"
        )


def _frames_under_clock_offset(preset_path: Path, flow: dict, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Два одинаковых инстанса на одних значениях энкодера; с шага 2 и до конца `b` видит часы
    на 0.5 с впереди `a` (тик Windows 15.6 мс между `a.produce()` и `b.produce()` — то же
    самое, только постоянное). `time.monotonic` подменён глобально (как в `test_lead_6_1.py`),
    а не `scene_plugin.time`, поэтому виден и спавнер, читающий свои часы сам.
    Возвращает по шагу: совпали ли кадры побитно.

    30 шагов: энкодер идёт по 5 отсчётов за шаг = 5 × FACTOR_MM 0.144473 ≈ 0.72 мм, а шаг
    спавна >= 4 мм — спавн случается раз в 6-8 шагов (замер: шаги 0, 8, 14, 23). Окно в 6
    шагов после скачка не содержит ни одного спавна, и часы в пороге спавна остаются
    невидимыми; с 2 по 29 шаг их три."""
    import time

    clock = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    plugin_a, sp_a = _new_scene(preset_path, flow)
    plugin_b, sp_b = _new_scene(preset_path, flow)
    equal = []
    for i in range(30):
        _emit_encoder(sp_a, i * 5.0, float(i))
        _emit_encoder(sp_b, i * 5.0, float(i))
        clock["t"] = 1000.0
        frame_a = plugin_a.produce()[0]["frame"]
        clock["t"] = 1000.0 + (0.5 if i >= 2 else 0.0)
        frame_b = plugin_b.produce()[0]["frame"]
        equal.append(bool(np.array_equal(frame_a, frame_b)))
    return equal


def test_frames_independent_of_wall_clock_in_spacing_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Причина флейка p6: часы между двумя `produce()` не должны менять кадр, если поток — по
    энкодеру. То же смещение часов в потоке по времени РАСХОДИТСЯ (так задумано: `interval_s` —
    секунды стенда) — второе утверждение доказывает, что смещение часов реально ловится."""
    preset_path, _ = _make_fixture(tmp_path)
    assert all(_frames_under_clock_offset(preset_path, _SPACING_FLOW, monkeypatch)), "spacing-поток зависит от часов"
    assert not all(_frames_under_clock_offset(preset_path, _INTERVAL_FLOW, monkeypatch)), (
        "смещение часов не разошло кадры interval-потока — проверка стала пустой"
    )


# --- P7 (перенесено из приёмки тестера) ---


def test_p7_preview_unsaved_preset_and_limits(tmp_path: Path) -> None:
    preset_path, _catalog_dir = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)

    before_bytes = preset_path.read_bytes()

    unsaved = ScenePreset.from_yaml(preset_path).to_dict()
    unsaved["layers"][0]["color_rgb"] = [255, 0, 0]
    result_unsaved = _call_command(plugin, "preset.preview", {"preset": unsaved, "seeds": [1]})
    assert result_unsaved["status"] == "ok", result_unsaved
    assert preset_path.read_bytes() == before_bytes, "preview с несохранённым preset не должен трогать файл"

    result_seeds = _call_command(plugin, "preset.preview", {"seeds": list(range(17))})
    assert result_seeds["status"] == "error" and result_seeds.get("code") == "bad_request", result_seeds

    result_tile = _call_command(plugin, "preset.preview", {"seeds": [1], "tile_px": 257})
    assert result_tile["status"] == "error" and result_tile.get("code") == "bad_request", result_tile

    assert preset_path.read_bytes() == before_bytes, "bad_request preview не должен трогать файл"


# --- Hazard-тесты автора (перенесены из test_scene_source_hazards_1_2a.py) ---


def test_preview_pixel_budget_bad_request(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    cases = [
        ({}, "ok"),
        ({"seeds": list(range(8)), "tile_px": 160}, "ok"),
        ({"seeds": list(range(16)), "tile_px": 113}, "ok"),  # 16*113^2 = 204304 <= 8*160^2
        ({"seeds": list(range(16)), "tile_px": 114}, "bad_request"),  # 207936
        ({"seeds": list(range(16)), "tile_px": 160}, "bad_request"),
        ({"seeds": list(range(9)), "tile_px": 160}, "bad_request"),
        ({"seeds": list(range(17)), "tile_px": 16}, "bad_request"),  # P7: сидов > 16
        ({"seeds": [1], "tile_px": 257}, "bad_request"),  # P7: тайл > 256
        ({"seeds": [-1]}, "bad_request"),
        ({"seeds": [True]}, "bad_request"),
        ({"seeds": [1], "tile_px": 15}, "bad_request"),
    ]
    for data, expected in cases:
        res = _call_command(plugin, "preset.preview", data)
        got = res["status"] if res["status"] == "ok" else res["code"]
        assert got == expected, (data, res)
    # Пределы проверяются ДО пресета: кривой preset + кривые seeds -> bad_request, не invalid.
    res = _call_command(plugin, "preset.preview", {"preset": {"layers": "x"}, "seeds": list(range(17))})
    assert res["code"] == "bad_request", res


def _outside_png(tmp_path: Path) -> Path:
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
    outside.mkdir()
    img = np.full((10, 10, 4), 200, dtype=np.uint8)
    imwrite_unicode(outside / "x.png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA))
    return outside / "x.png"


def test_client_path_outside_roots_rejected_without_existence_oracle(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    base = ScenePreset.from_yaml(preset_path).to_dict()
    existing = _outside_png(tmp_path)
    missing = existing.parent / "nope.png"

    def with_sprite(src: str) -> dict:
        d = copy.deepcopy(base)
        d["layers"][0]["sprite_source"] = src
        return d

    variants = {
        "abs-existing": with_sprite(str(existing)),
        "abs-missing": with_sprite(str(missing)),
        "rel-existing": with_sprite(f"../{existing.parent.name}/x.png"),
        "rel-missing": with_sprite(f"../{existing.parent.name}/nope.png"),
        "catalog-existing": {**base, "catalog_dir": str(existing.parent)},
        "catalog-missing": {**base, "catalog_dir": str(existing.parent / "nodir")},
    }
    messages = set()
    for label, preset_dict in variants.items():
        res = _call_command(plugin, "preset.preview", {"preset": preset_dict, "seeds": [1]})
        assert res["status"] == "error" and res["code"] == "invalid", (label, res)
        messages.add(res["message"])
    assert len(messages) == 1, f"сообщение зависит от существования файла: {messages}"
    assert str(existing.parent) not in next(iter(messages))

    # base_dir клиента отбрасывается: "x.png" ищется в каталоге файла пресета, а не рядом
    # с существующим outside/x.png — ответ invalid о ненайденном файле в tmp_path.
    res = _call_command(
        plugin, "preset.preview", {"preset": {**with_sprite("x.png"), "base_dir": str(existing.parent)}, "seeds": [1]}
    )
    assert res["status"] == "error" and res["code"] == "invalid", res
    assert str(existing.parent) not in res["message"], res

    from Services.line_sim.core import REPO_ROOT

    in_repo = with_sprite(str(REPO_ROOT / f"no-such-{uuid.uuid4().hex}.png"))
    res = _call_command(plugin, "preset.preview", {"preset": in_repo, "seeds": [1]})
    assert res["status"] == "error" and res["message"] not in messages, "корень репозитория обязан быть разрешён"
    ok = _call_command(plugin, "preset.preview", {"preset": base, "seeds": [1]})
    assert ok["status"] == "ok", "каталог файла пресета обязан быть разрешён"


def test_preview_reflects_commit_through_scene_source_without_restart(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    scene, _sp = _new_scene(preset_path)
    preview = _new_preview(preset_path)
    first = _call_command(preview, "preset.preview", {"seeds": [1]})
    second = _call_command(preview, "preset.preview", {"seeds": [1]})
    assert first["status"] == "ok" and first["png_b64"] == second["png_b64"]

    got = _call_command(scene, "preset.get", {})
    red = copy.deepcopy(got["preset"])
    red["layers"][0]["color_rgb"] = [255, 0, 0]
    assert _call_command(scene, "preset.commit", {"preset": red, "base_rev": got["rev"]})["status"] == "ok"

    third = _call_command(preview, "preset.preview", {"seeds": [1]})
    assert third["status"] == "ok" and third["png_b64"] != first["png_b64"], "превью не увидело commit без рестарта"
    img = _decode(third)
    red_px = int(((img[..., 2] > 200) & (img[..., 1] < 60) & (img[..., 0] < 60)).sum())
    assert red_px > 0, "в превью после commit нет красного диска"


def test_preview_applies_stand_defect_override(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    forced = _new_preview(preset_path, defect_probability=1.0)
    plain = _new_preview(preset_path)
    res_forced = _call_command(forced, "preset.preview", {"seeds": [1, 2]})
    res_plain = _call_command(plain, "preset.preview", {"seeds": [1, 2]})
    assert all(t["layer_params"]["damaged"]["active"] for t in res_forced["tiles"]), res_forced["tiles"]
    assert not any(t["layer_params"]["damaged"]["active"] for t in res_plain["tiles"]), res_plain["tiles"]


def test_preview_catalog_mode_like_the_stand(tmp_path: Path) -> None:
    """Каталожный `preset_path` (каталог классов, не .yaml) — режим стенда до 1.3h, остаётся рабочим."""
    _preset_path, catalog_dir = _make_fixture(tmp_path)
    plugin = _new_preview(catalog_dir)
    res = _call_command(plugin, "preset.preview", {"seeds": [1, 2]})
    assert res["status"] == "ok", res
    assert {t["class_name"] for t in res["tiles"]} <= {"A", "B"}
    # Клиентский пресет у каталожного хоста: разрешён только корень репозитория.
    client = {"catalog_dir": str(catalog_dir)}
    res = _call_command(plugin, "preset.preview", {"preset": client, "seeds": [1]})
    assert res["status"] == "error" and res["code"] == "invalid", res


def test_preview_without_preset_is_invalid_not_crash() -> None:
    plugin = _new_preview(None)
    res = _call_command(plugin, "preset.preview", {})
    assert res["status"] == "error" and res["code"] == "invalid", res
    res = plugin.cmd_preset_preview("not a dict")  # type: ignore[arg-type]
    assert res["status"] == "error" and res["code"] == "bad_request", res


def test_plugin_is_side_effect_control_without_ports() -> None:
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    assert LayerPreviewPlugin.category == "control"
    assert LayerPreviewPlugin.inputs == [] and LayerPreviewPlugin.outputs == []
    assert LayerPreviewPlugin.commands == {
        "preset.preview": "cmd_preset_preview",
        "preset.layout": "cmd_preset_layout",
        "preset.sprites": "cmd_preset_sprites",
    }


def test_layer_preview_does_not_import_scene_source() -> None:
    """Плагин превью не тянет плагин сцены (связь plugin -> plugin и лишняя регистрация
    `scene_source` в процессе `layers`) — проверка в чистом интерпретаторе."""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[4]
    code = (
        "import sys; import Plugins.sim.layer_preview.plugin as m; "
        "assert m.LayerPreviewPlugin.name == 'layer_preview'; "
        "bad = sorted(k for k in sys.modules if k.startswith('Plugins.sim.scene_source')); "
        "print(bad); raise SystemExit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env={**__import__("os").environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr[-2000:]!r}"
