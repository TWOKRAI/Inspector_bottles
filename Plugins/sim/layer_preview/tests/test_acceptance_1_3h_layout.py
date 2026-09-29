# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-a — команда `preset.layout` на `LayerPreviewPlugin`.

Слепой прогон независимого tester, worktree `ls-13h-tester` на коммите `807e4faf`
(до реализации). Источник контракта — DESIGN из брифа лида (не код реализации):

- `preset.layout` отдаёт КАЖДЫЙ слой пресета отдельно, преобразованный тем же движком, что и
  лента (`color_rgb` -> `scale` -> поворот `angle_deg` CCW, rotate-expand), при НОМИНАЛЬНЫХ
  параметрах: диапазоны `augment` не применяются. Слой `class://` — спрайт класса, выбранный `seed`.
- Запрос `{preset?: dict, seed?: int}`; без `preset` — пресет хоста; `seed` по умолчанию 0.
- Ответ `{"status": "ok", "class_name": str, "canvas_px": [w, h],
  "layers": [{"name", "png_b64" (RGBA PNG), "center_px": [x, y], "size_px": [w, h]}]}`;
  порядок слоёв = порядок пресета (снизу вверх); `center_px` — центр преобразованной картинки
  слоя ОТНОСИТЕЛЬНО центра объекта, px, Y вниз; `size_px` = размер декодированного PNG.
  У defect-слоёв ничего не закреплено.
- Ошибки в стиле `preset.preview`: не-dict -> `bad_request`; невалидный пресет / путь вне
  разрешённых корней / нет пресета нигде -> `invalid`; исключения наружу не выходят.

Команда вызывается через карту `plugin.commands` (имя метода не закреплено контрактом).
Хелперы фикстуры — копия паттерна `test_layer_preview.py` (не импорт из чужого теста).
Ожидаемые значения — литералы. Объектный угол в фикстуре нулевой (`angle_range_deg=(0, 0)`),
чтобы центр/размеры не зависели от неопределённой в контракте позы объекта.
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset

RECT_W = 40
RECT_H = 20


# --------------------------------------------------------------------------- #
# Фикстура                                                                    #
# --------------------------------------------------------------------------- #


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """`cat/<A|B>/0.png` (30x30 серый) + `disk.png` (60x60 белый) + `rect.png` + `preset.yaml`.

    `rect.png` — 40x20 (ширина x высота), левая половина чисто красная, правая чисто синяя,
    полностью непрозрачный. Файл лежит в каталоге пресета -> разрешён оградой путей.
    """
    catalog_dir = tmp_path / "cat"
    for cls in ("A", "B"):
        class_dir = catalog_dir / cls
        class_dir.mkdir(parents=True)
        sprite = np.zeros((30, 30, 4), dtype=np.uint8)
        sprite[:, :, :3] = 128
        sprite[:, :, 3] = 255
        imwrite_unicode(class_dir / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    disk = np.zeros((60, 60, 4), dtype=np.uint8)
    disk[:, :, :3] = 255
    disk[:, :, 3] = 255
    imwrite_unicode(tmp_path / "disk.png", cv2.cvtColor(disk, cv2.COLOR_RGBA2BGRA))

    rect = np.zeros((RECT_H, RECT_W, 4), dtype=np.uint8)
    rect[:, : RECT_W // 2, 0] = 255  # RGBA: красный слева
    rect[:, RECT_W // 2 :, 2] = 255  # RGBA: синий справа
    rect[:, :, 3] = 255
    imwrite_unicode(tmp_path / "rect.png", cv2.cvtColor(rect, cv2.COLOR_RGBA2BGRA))

    preset = ScenePreset(
        catalog_dir=str(catalog_dir),
        angle_range_deg=(0.0, 0.0),
        defect_probability=0.0,
        layers=[
            LayerSpec(name="disk", mode="static", sprite_source=str(tmp_path / "disk.png"), color_rgb=(255, 255, 255)),
            LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE, color_rgb=(0, 0, 0)),
        ],
    )
    preset_path = tmp_path / "preset.yaml"
    preset.to_yaml(preset_path)
    return preset_path, catalog_dir


def _new_preview(preset_path_cfg: Path | str | None, **extra):
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    ctx = MagicMock()
    ctx.config = {"preset_path": None if preset_path_cfg is None else str(preset_path_cfg), **extra}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _call_raw(plugin, name: str, data: Any) -> dict:
    """Вызов команды по карте `plugin.commands` БЕЗ приведения `data` к dict (нужно для не-dict)."""
    commands = getattr(plugin, "commands", None)
    assert commands is not None and name in commands, f"команда '{name}' отсутствует в plugin.commands ({commands!r})"
    method = getattr(plugin, commands[name], None)
    assert method is not None, f"plugin.commands['{name}'] указывает на несуществующий метод"
    return method(data)


def _layout(plugin, data: dict | None = None) -> dict:
    return _call_raw(plugin, "preset.layout", dict(data or {}))


def _layout_ok(plugin, data: dict | None = None) -> dict:
    res = _layout(plugin, data)
    assert isinstance(res, dict) and res.get("status") == "ok", res
    return res


def _by_name(res: dict) -> dict[str, dict]:
    return {layer["name"]: layer for layer in res["layers"]}


def _decode_rgba(layer: dict) -> np.ndarray:
    """PNG слоя -> массив (h, w, 4) в порядке BGRA (как отдаёт cv2)."""
    img = cv2.imdecode(np.frombuffer(base64.b64decode(layer["png_b64"]), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert img is not None and img.ndim == 3 and img.shape[2] == 4, "png_b64 должен декодироваться в RGBA-картинку"
    return img


def _layer_dict(name: str, sprite: str, **fields: Any) -> dict:
    return {"name": name, "mode": "static", "sprite_source": sprite, **fields}


def _client_preset(preset_path: Path, layers: list[dict]) -> dict:
    """Пресет клиента: всё из пресета фикстуры (catalog_dir, angle_range_deg 0..0), слои заменены."""
    preset = ScenePreset.from_yaml(preset_path).to_dict()
    preset["layers"] = layers
    return preset


def _outside_png(tmp_path: Path) -> Path:
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
    outside.mkdir()
    img = np.full((10, 10, 4), 200, dtype=np.uint8)
    imwrite_unicode(outside / "x.png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA))
    return outside / "x.png"


# --------------------------------------------------------------------------- #
# A — слои раздельно, в порядке пресета                                       #
# --------------------------------------------------------------------------- #


def test_a_layers_separate_in_preset_order(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)

    res = _layout_ok(plugin)  # без preset -> пресет хоста
    assert [layer["name"] for layer in res["layers"]] == ["disk", "letter"], res["layers"]
    assert res["class_name"] in {"A", "B"}, res["class_name"]
    canvas = res["canvas_px"]
    assert len(canvas) == 2 and all(isinstance(v, int) and v > 0 for v in canvas), canvas
    for layer in res["layers"]:
        img = _decode_rgba(layer)
        h, w = img.shape[:2]
        assert layer["size_px"] == [w, h], (layer["name"], layer["size_px"], (w, h))
        assert len(layer["center_px"]) == 2, layer["center_px"]

    # Порядок — порядок пресета, а не алфавитный: у пресета хоста имена «disk» < «letter»
    # совпадают с алфавитом, поэтому проверяем ещё пресет, где порядок и алфавит расходятся.
    reversed_alpha = _client_preset(
        preset_path,
        [_layer_dict("zz_first", "disk.png"), _layer_dict("aa_second", "rect.png")],
    )
    res2 = _layout_ok(plugin, {"preset": reversed_alpha})
    # Решение лида 2026-09-29 (эскалация разработчика): каталог без слоя class:// -> лента сама
    # подкладывает снизу авто-слой «base» со спрайтом класса; раскладка показывает объект ленты
    # как есть («что видно в редакторе, то и поедет»), поэтому «base» первым, дальше — пресет.
    assert [layer["name"] for layer in res2["layers"]] == ["base", "zz_first", "aa_second"], res2["layers"]


# --------------------------------------------------------------------------- #
# B — center_px относительно центра объекта                                   #
# --------------------------------------------------------------------------- #


def test_b_center_is_offset_from_object_center(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    preset = _client_preset(
        preset_path,
        [
            _layer_dict("shifted", "disk.png", offset_px=[30, -10]),
            _layer_dict("letter", CLASS_SPRITE_SOURCE),
        ],
    )

    layers = _by_name(_layout_ok(plugin, {"preset": preset}))

    cx, cy = layers["shifted"]["center_px"]
    assert abs(cx - 30) <= 1 and abs(cy - (-10)) <= 1, (
        f"offset_px [30,-10] -> center_px {[cx, cy]} (ожидалось [30,-10] ±1)"
    )
    lx, ly = layers["letter"]["center_px"]
    assert abs(lx) <= 1 and abs(ly) <= 1, f"слой без offset_px -> center_px {[lx, ly]} (ожидалось [0,0] ±1)"


# --------------------------------------------------------------------------- #
# C — поворот и масштаб меняют размер; направление поворота CCW               #
# --------------------------------------------------------------------------- #


def test_c_rotation_and_scale_change_size(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    preset = _client_preset(
        preset_path,
        [
            _layer_dict("rot90", "rect.png", angle_deg=90.0),
            _layer_dict("scaled", "rect.png", scale=2.0),
        ],
    )

    layers = _by_name(_layout_ok(plugin, {"preset": preset}))

    rw, rh = layers["rot90"]["size_px"]
    assert abs(rw - 20) <= 1 and abs(rh - 40) <= 1, (
        f"rect 40x20 при angle 90 -> size_px {[rw, rh]} (ожидалось ≈[20,40])"
    )
    sw, sh = layers["scaled"]["size_px"]
    assert abs(sw - 80) <= 1 and abs(sh - 40) <= 1, f"rect 40x20 при scale 2 -> size_px {[sw, sh]} (ожидалось ≈[80,40])"

    # Контроль порядка каналов и ориентации без поворота: слева красный, справа синий (BGRA).
    scaled_img = _decode_rgba(layers["scaled"])
    left = scaled_img[scaled_img.shape[0] // 2, 10]
    right = scaled_img[scaled_img.shape[0] // 2, scaled_img.shape[1] - 10]
    assert left[2] > 200 and left[0] < 60, f"неповёрнутый слой: слева должен быть красный, BGRA={left.tolist()}"
    assert right[0] > 200 and right[2] < 60, f"неповёрнутый слой: справа должен быть синий, BGRA={right.tolist()}"

    # CCW: правая (синяя) половина при +90° уходит вверх, левая (красная) — вниз (конвенция interfaces.py).
    rot_img = _decode_rgba(layers["rot90"])
    top = rot_img[5, rot_img.shape[1] // 2]
    bottom = rot_img[rot_img.shape[0] - 6, rot_img.shape[1] // 2]
    assert top[0] > 200 and top[2] < 60, f"angle 90 (CCW): сверху должен быть синий, BGRA={top.tolist()}"
    assert bottom[2] > 200 and bottom[0] < 60, f"angle 90 (CCW): снизу должен быть красный, BGRA={bottom.tolist()}"


# --------------------------------------------------------------------------- #
# D — номинальные параметры: augment не применяется; детерминизм по seed      #
# --------------------------------------------------------------------------- #


def test_d_nominal_ignores_augment_and_is_deterministic(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    augmented = {
        "name": "aug",
        "mode": "augmented",
        "sprite_source": "disk.png",
        "offset_px": [10, 0],
        "augment": {"offset_x_px": [40, 40], "scale": [2, 2], "angle_deg": [45, 45]},
    }
    preset = _client_preset(preset_path, [augmented])

    first = _layout_ok(plugin, {"preset": preset, "seed": 5})
    layer = _by_name(first)["aug"]

    cx, cy = layer["center_px"]
    assert abs(cx - 10) <= 1 and abs(cy) <= 1, (
        f"augment.offset_x_px [40,40] не должен применяться: center_px {[cx, cy]} (ожидалось [10,0] ±1, не [50,0])"
    )
    w, h = layer["size_px"]
    assert abs(w - 60) <= 1 and abs(h - 60) <= 1, (
        f"augment.scale [2,2] / angle_deg [45,45] не должны применяться: size_px {[w, h]} (ожидалось ≈[60,60])"
    )

    second = _layout_ok(plugin, {"preset": preset, "seed": 5})
    assert first["layers"] == second["layers"], "тот же preset и seed дали разные слои (не детерминировано)"
    assert first["class_name"] == second["class_name"]


# --------------------------------------------------------------------------- #
# E — заливка color_rgb                                                       #
# --------------------------------------------------------------------------- #


def test_e_color_fill_applied(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    preset = _client_preset(preset_path, [_layer_dict("red", "disk.png", color_rgb=[255, 0, 0])])

    img = _decode_rgba(_by_name(_layout_ok(plugin, {"preset": preset}))["red"])

    opaque = img[img[..., 3] > 0]
    assert len(opaque) > 0, "в слое нет непрозрачных пикселей"
    # cv2 отдаёт BGRA: B=0, G=0, R=255. Исходный диск белый — без заливки было бы 255/255/255.
    assert int(opaque[:, 2].min()) >= 253, f"R у непрозрачных пикселей: min={int(opaque[:, 2].min())}"
    assert int(opaque[:, 1].max()) <= 2, f"G у непрозрачных пикселей: max={int(opaque[:, 1].max())}"
    assert int(opaque[:, 0].max()) <= 2, f"B у непрозрачных пикселей: max={int(opaque[:, 0].max())}"


# --------------------------------------------------------------------------- #
# F — class_name следует seed                                                 #
# --------------------------------------------------------------------------- #


def test_f_class_name_follows_seed(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)

    names = [_layout_ok(plugin, {"seed": seed})["class_name"] for seed in range(20)]

    assert set(names) <= {"A", "B"}, names
    assert len(set(names)) >= 2, (
        f"20 разных seed дали один класс: {sorted(set(names))} — seed не влияет на выбор класса"
    )


# --------------------------------------------------------------------------- #
# G — ошибки кодами, не исключениями                                          #
# --------------------------------------------------------------------------- #


def test_g_errors_are_codes_not_exceptions(tmp_path: Path) -> None:
    preset_path, _ = _make_fixture(tmp_path)
    plugin = _new_preview(preset_path)
    empty_host = _new_preview(None)
    existing = _outside_png(tmp_path)
    outside = _client_preset(preset_path, [_layer_dict("out", str(existing))])

    cases: list[tuple[str, Any, Any, str]] = [
        # (метка, плагин, тело запроса, ожидаемый code)
        ("не-dict запрос", plugin, "not a dict", "bad_request"),
        ("невалидный пресет", plugin, {"preset": {"layers": "x"}}, "invalid"),
        ("нет пресета нигде", empty_host, {}, "invalid"),
        ("спрайт вне разрешённых корней", plugin, {"preset": outside}, "invalid"),
    ]
    failures: list[str] = []
    for label, target, body, expected in cases:
        res = _call_raw(target, "preset.layout", body)  # исключение здесь = падение теста
        if not (isinstance(res, dict) and res.get("status") == "error" and res.get("code") == expected):
            failures.append(f"{label}: ожидалось error/{expected}, получено {res!r}")
        elif not (isinstance(res.get("message"), str) and res["message"]):
            failures.append(f"{label}: нет непустого message (стиль preset.preview): {res!r}")
    assert not failures, "; ".join(failures)


# --------------------------------------------------------------------------- #
# H — команда зарегистрирована                                                #
# --------------------------------------------------------------------------- #


def test_h_command_registered() -> None:
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    assert "preset.layout" in LayerPreviewPlugin.commands, LayerPreviewPlugin.commands
