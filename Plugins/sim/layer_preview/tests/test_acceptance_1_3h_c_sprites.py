# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-c (S1-S3) — команда `preset.sprites` на `LayerPreviewPlugin`.

Слепой прогон независимого tester, worktree `ls-13hc-s-tester` на коммите `c8fe3540`
(до реализации). Источник контракта — раздел «Устройство бэкенда (c1)» и критерии S1-S3 плана
`plans/line-sim-layer-editor/task-1.3h-c-layers.md` (не код реализации, которого ещё нет):

- запрос `{}`; каталог — ключ конфига `sprites_dir` (относительный — от корня репозитория,
  абсолютный принимается), по умолчанию `data/line_sim`;
- ответ `{status: "ok", dir, files: [{path, sprite_source}], truncated, layer_template}`;
  `path` — от `sprites_dir`, прямые слэши; рекурсивно, `*.png` без учёта регистра, порядок по
  `path`, не больше 500 записей, лишние отрезаются с `truncated: true`;
- `sprite_source` — от каталога файла пресета хоста, прямые слэши, и он РЕАЛЬНО грузится, когда
  вписан в слой (`preset.layout` -> ok); файл, чей `resolve()` уходит за ограду
  (`confine_preset_paths`: корень репозитория или каталог пресета), в список не попадает;
- `layer_template` — полный набор ключей `LayerSpec` с дефолтами (`mode == "static"`);
- каталога нет -> `io_error` с путём в тексте; каталог вне ограды -> `bad_request`.

Команда вызывается через карту `plugin.commands` (имя метода не закреплено контрактом).
Хелперы фикстуры — копия паттерна `test_acceptance_1_3h_layout.py` (не импорт из чужого теста).
Ожидаемые значения — литералы. Все временные файлы — в `tmp_path` (вне репозитория): внутри
репозитория ограда путей пускала бы любой путь, и тест доказывал бы не то.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset

# --------------------------------------------------------------------------- #
# Фикстура                                                                    #
# --------------------------------------------------------------------------- #


def _write_png(path: Path, w: int = 8, h: int = 8) -> None:
    """RGBA PNG `w x h` (ширина x высота), полностью непрозрачный, серый."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = 128
    rgba[:, :, 3] = 255
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _write_many_pngs(directory: Path, names: list[str]) -> None:
    """Много валидных PNG дёшево: один закодированный буфер пишется под разными именами."""
    directory.mkdir(parents=True, exist_ok=True)
    rgba = np.full((4, 4, 4), 200, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    assert ok
    blob = buf.tobytes()
    for name in names:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)


def _make_world(tmp_path: Path) -> tuple[Path, Path]:
    """`work/p.yaml` + `work/cat/<A|B>/0.png` + пустой `work/sprites/`.

    Каталог пресета — `work/`; каталог картинок `work/sprites/` лежит внутри него (ограда пускает
    только корень репозитория и каталог пресета, а `tmp_path` вне репозитория). Вернёт
    `(preset_path, sprites_dir)`.
    """
    work = tmp_path / "work"
    for cls in ("A", "B"):
        _write_png(work / "cat" / cls / "0.png", 30, 30)
    (work / "sprites").mkdir(parents=True)
    preset = ScenePreset(
        catalog_dir=str(work / "cat"),
        angle_range_deg=(0.0, 0.0),
        defect_probability=0.0,
        layers=[LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)],
    )
    preset_path = work / "p.yaml"
    preset.to_yaml(preset_path)
    return preset_path, work / "sprites"


def _new_preview(preset_path_cfg: Path | str | None, **extra: Any):
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    ctx = MagicMock()
    ctx.config = {"preset_path": None if preset_path_cfg is None else str(preset_path_cfg), **extra}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _call_raw(plugin, name: str, data: Any) -> dict:
    """Вызов команды по карте `plugin.commands` БЕЗ приведения `data` к dict."""
    commands = getattr(plugin, "commands", None)
    assert commands is not None and name in commands, f"команда '{name}' отсутствует в plugin.commands ({commands!r})"
    method = getattr(plugin, commands[name], None)
    assert method is not None, f"plugin.commands['{name}'] указывает на несуществующий метод"
    return method(data)


def _sprites(plugin) -> dict:
    return _call_raw(plugin, "preset.sprites", {})


def _sprites_ok(plugin) -> dict:
    res = _sprites(plugin)
    assert isinstance(res, dict) and res.get("status") == "ok", res
    return res


def _layout(plugin, data: dict) -> dict:
    return _call_raw(plugin, "preset.layout", data)


def _client_preset_with_sources(preset_path: Path, entries: list[tuple[str, str]]) -> dict:
    """Пресет клиента: всё из пресета фикстуры, слои = `[(name, sprite_source), ...]`."""
    preset = ScenePreset.from_yaml(preset_path).to_dict()
    preset["layers"] = [{"name": name, "mode": "static", "sprite_source": src} for name, src in entries]
    return preset


def _paths(res: dict) -> list[str]:
    return [entry["path"] for entry in res["files"]]


# --------------------------------------------------------------------------- #
# S0 — команда зарегистрирована                                               #
# --------------------------------------------------------------------------- #


def test_s0_command_registered() -> None:
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    assert "preset.sprites" in LayerPreviewPlugin.commands, LayerPreviewPlugin.commands


# --------------------------------------------------------------------------- #
# S1 — перечень: рекурсия, регистр расширения, порядок, относительные пути    #
# --------------------------------------------------------------------------- #


def test_s1_lists_recursive_case_insensitive_png_only(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "a.png")
    _write_png(sprites_dir / "sub" / "b.PNG")
    (sprites_dir / "c.jpg").write_bytes(b"\xff\xd8\xff\xe0not really a jpeg")
    (sprites_dir / "notes.txt").write_text("hello", encoding="utf-8")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["a.png", "sub/b.PNG"], res["files"]
    assert [entry["sprite_source"] for entry in res["files"]] == ["sprites/a.png", "sprites/sub/b.PNG"], res["files"]
    assert res["truncated"] is False, res["truncated"]


def test_s1_order_is_full_path_sort_not_walk_order(tmp_path: Path) -> None:
    """Обход «файлы корня, потом подкаталоги» дал бы `a.png, z.png, m/x.png`; контракт — по `path`."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "z.png")
    _write_png(sprites_dir / "m" / "x.png")
    _write_png(sprites_dir / "a.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["a.png", "m/x.png", "z.png"], res["files"]


def test_s1_every_listed_sprite_source_loads_in_layout(tmp_path: Path) -> None:
    """`sprite_source` из ответа, вписанный в слой пресета, реально грузится: `preset.layout` -> ok,
    и слой несёт размер именно ЭТОГО файла (a.png 24x12, b.PNG 10x30), а не какого-то другого."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "a.png", 24, 12)
    _write_png(sprites_dir / "sub" / "b.PNG", 10, 30)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    listed = _sprites_ok(plugin)["files"]
    assert [e["path"] for e in listed] == ["a.png", "sub/b.PNG"], listed
    preset = _client_preset_with_sources(
        preset_path, [("la", listed[0]["sprite_source"]), ("lb", listed[1]["sprite_source"])]
    )
    res = _layout(plugin, {"preset": preset})

    assert res.get("status") == "ok", res
    sizes = {layer["name"]: layer["size_px"] for layer in res["layers"]}
    assert sizes["la"] == [24, 12], sizes
    assert sizes["lb"] == [10, 30], sizes


def test_s1_control_source_relative_to_sprites_dir_is_rejected_by_layout(tmp_path: Path) -> None:
    """Контроль харнесса (зелёный уже сейчас): `a.png` (от каталога картинок, а не от каталога
    пресета) `preset.layout` отвергает -> проверка загрузки выше не вакуумна."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "a.png", 24, 12)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _layout(plugin, {"preset": _client_preset_with_sources(preset_path, [("la", "a.png")])})

    assert res.get("status") == "error" and res.get("code") == "invalid", res


def test_s1_unicode_and_spaces_listed_with_forward_slashes_and_load(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "папка 1" / "имя файла.png", 16, 9)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert res["files"] == [{"path": "папка 1/имя файла.png", "sprite_source": "sprites/папка 1/имя файла.png"}], res[
        "files"
    ]
    layout = _layout(
        plugin, {"preset": _client_preset_with_sources(preset_path, [("u", res["files"][0]["sprite_source"])])}
    )
    assert layout.get("status") == "ok", layout
    assert {layer["name"]: layer["size_px"] for layer in layout["layers"]}["u"] == [16, 9], layout["layers"]


def test_s1_empty_dir_is_ok_with_empty_list_and_template(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert res["files"] == [], res["files"]
    assert res["truncated"] is False
    assert isinstance(res["layer_template"], dict) and res["layer_template"], (
        "пустой каталог — шаблон слоя всё равно отдаётся"
    )


def test_s1_dir_field_is_absolute_when_outside_repo(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert Path(res["dir"]).is_absolute(), res["dir"]
    assert Path(res["dir"]).resolve() == sprites_dir.resolve(), (res["dir"], str(sprites_dir))


def test_s1_relative_sprites_dir_resolves_from_repo_root_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Относительный `sprites_dir` — от корня репозитория; `dir` внутри репо отдаётся относительно корня.
    cwd уводится в `tmp_path`: разрешение от cwd не нашло бы каталог (`Plugins/sim/layer_preview` там нет)."""
    preset_path, _ = _make_world(tmp_path)
    monkeypatch.chdir(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir="Plugins/sim/layer_preview")

    res = _sprites_ok(plugin)

    assert res["dir"].replace("\\", "/") == "Plugins/sim/layer_preview", res["dir"]
    assert all(p.lower().endswith(".png") for p in _paths(res)), res["files"]


# --------------------------------------------------------------------------- #
# S2 — layer_template                                                         #
# --------------------------------------------------------------------------- #


def test_s2_template_keys_match_layerspec_fields_and_builds_layerspec(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    template = _sprites_ok(plugin)["layer_template"]

    assert set(template) == set(LayerSpec.model_fields), (sorted(template), sorted(LayerSpec.model_fields))
    built = LayerSpec(**{**template, "name": "x", "sprite_source": "sprites/x.png"})
    assert built.name == "x" and built.sprite_source == "sprites/x.png"
    json.dumps(template)  # mode="json": шаблон сериализуется в JSON без потерь типов


def test_s2_template_defaults_are_literal(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    template = _sprites_ok(plugin)["layer_template"]

    assert template["mode"] == "static", template
    assert template["offset_px"] == [0, 0], template["offset_px"]  # список (json-режим), не кортеж
    assert isinstance(template["offset_px"], list), template["offset_px"]
    assert template["angle_deg"] == 0, template["angle_deg"]
    assert template["scale"] == 1, template["scale"]
    assert template["augment"] is None and template["color_rgb"] is None, template
    assert template["defect_probability"] == 0, template["defect_probability"]


# --------------------------------------------------------------------------- #
# S3 — отказы, потолок, симлинк, ограда                                       #
# --------------------------------------------------------------------------- #


def test_s3_missing_dir_is_io_error_with_path_in_message(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    missing = sprites_dir.parent / "sprites_missing_zq7"
    plugin = _new_preview(preset_path, sprites_dir=str(missing))

    res = _sprites(plugin)

    assert res.get("status") == "error" and res.get("code") == "io_error", res
    assert "sprites_missing_zq7" in str(res.get("message")), res


def test_s3_exactly_500_files_not_truncated(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_many_pngs(sprites_dir, [f"f_{i:03d}.png" for i in range(500)])
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert len(res["files"]) == 500, len(res["files"])
    assert res["truncated"] is False, res["truncated"]


def test_s3_501_files_cut_to_500_and_truncated(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_many_pngs(sprites_dir, [f"f_{i:03d}.png" for i in range(501)])
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert len(res["files"]) == 500, len(res["files"])
    assert res["truncated"] is True, res["truncated"]
    assert _paths(res)[0] == "f_000.png" and _paths(res)[-1] == "f_499.png", (_paths(res)[0], _paths(res)[-1])


def test_s3_truncation_cuts_the_sorted_tail_not_the_walk_tail(tmp_path: Path) -> None:
    """500 файлов корня `b_000..b_499` + `a/x.png` (по `path` идёт ПЕРВЫМ). Обход, остановленный на
    500-й записи, потерял бы `a/x.png`; контракт — «порядок по path, лишние отрезаются»."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_many_pngs(sprites_dir, [f"b_{i:03d}.png" for i in range(500)] + ["a/x.png"])
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    paths = _paths(res)
    assert res["truncated"] is True
    assert len(paths) == 500, len(paths)
    assert paths[0] == "a/x.png", paths[:2]
    assert paths[-1] == "b_498.png", paths[-2:]
    assert "b_499.png" not in paths


def test_s3_symlink_to_file_outside_fence_is_omitted(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "ok.png")
    outside = tmp_path / f"outside-{uuid.uuid4().hex}"
    _write_png(outside / "x.png")
    link = sprites_dir / "link.png"
    try:
        os.symlink(outside / "x.png", link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"ОС не даёт создать симлинк ({type(exc).__name__}: {exc}) — S3-симлинк не проверен")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["ok.png"], res["files"]


def test_s3_dir_outside_fence_is_bad_request(tmp_path: Path) -> None:
    """Хост с файлом пресета: ограда = корень репозитория + `work/`; `outside/` (брат `work/`) вне неё."""
    preset_path, _ = _make_world(tmp_path)
    outside = tmp_path / "outside"
    _write_png(outside / "x.png")
    plugin = _new_preview(preset_path, sprites_dir=str(outside))

    res = _sprites(plugin)

    assert res.get("status") == "error" and res.get("code") == "bad_request", res
    assert isinstance(res.get("message"), str) and res["message"], res


def test_s3_dir_outside_repo_without_preset_file_is_bad_request(tmp_path: Path) -> None:
    """Хост без файла пресета: ограда = только корень репозитория; каталог в `tmp_path` вне неё."""
    somewhere = tmp_path / "somewhere"
    _write_png(somewhere / "x.png")
    plugin = _new_preview(None, sprites_dir=str(somewhere))

    res = _sprites(plugin)

    assert res.get("status") == "error" and res.get("code") == "bad_request", res
