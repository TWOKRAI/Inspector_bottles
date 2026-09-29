# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 1.3h-c (c1) — что может сломаться в `preset.sprites` ИМЕННО при такой сборке.

Механизм: `os.walk` по `sprites_dir` -> фильтр `.png` + `is_file()` -> ограда по `resolve()` файла ->
`sprite_entry` (два `relpath`) -> сортировка по `path` -> потолок 500. Опасные места:

1. Обход дерева. `os.walk` без `followlinks` не заходит в симлинк-каталог, но на Windows заходит в
   junction: петля `sprites/loop -> sprites` даёт ~32 дубля каждого файла (`loop/loop/.../a.png`), а
   петля симлинков-файлов (`a -> b -> a`) даёт `RuntimeError`/`OSError` из `resolve()`. Любой такой сбой
   не должен ни зависеть, ни ронять весь ответ. Каталог, чьё имя оканчивается на `.png`, — не файл.
2. Ограда. Симлинк-каталог, ведущий за ограду, не должен просочиться в список через обход.
3. `relpath`. На Windows между дисками он бросает `ValueError`: файл, у которого нет пути от каталога
   пресета хоста, в список не идёт (а не роняет весь ответ). Прямые слэши, кириллица и пробелы — и в
   именах файлов, и в самих каталогах.
4. Шов для 1.3h-d: запись `sprite_entry` -> слой -> `preset.layout` -> ok, в том числе когда каталог
   картинок НЕ лежит под каталогом пресета и `sprite_source` начинается с `../..`. Ограда пускает такой
   путь только внутри корня репозитория, а `tmp_path` лежит вне репо, поэтому `REPO_ROOT` плагина
   подменяется на каталог внутри `tmp_path` (по другому «внутри корня, но не под пресетом» не получить).
5. Отказы и умолчание: не-dict, `sprites_dir` — файл, умолчание `data/line_sim` при отсутствующем каталоге
   (на свежем клоне) — `io_error`, а не исключение.

Всё, что может зависнуть, гонится в daemon-потоке с дедлайном: зависший тест прятал бы регрессию за таймаутом
(`@pytest.mark.timeout` в этом окружении не работает). Все временные файлы — в `tmp_path`.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset

_DEADLINE_S = 20.0

# --------------------------------------------------------------------------- #
# Фикстура                                                                    #
# --------------------------------------------------------------------------- #


def _write_png(path: Path, w: int = 8, h: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = 128
    rgba[:, :, 3] = 255
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _write_preset(preset_path: Path, catalog_dir: Path) -> None:
    for cls in ("A", "B"):
        _write_png(catalog_dir / cls / "0.png", 30, 30)
    preset = ScenePreset(
        catalog_dir=str(catalog_dir),
        angle_range_deg=(0.0, 0.0),
        defect_probability=0.0,
        layers=[LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)],
    )
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset.to_yaml(preset_path)


def _make_world(tmp_path: Path, work_name: str = "work") -> tuple[Path, Path]:
    """`<work>/p.yaml` + `<work>/cat/...` + `<work>/sprites/`; вернёт `(preset_path, sprites_dir)`."""
    work = tmp_path / work_name
    (work / "sprites").mkdir(parents=True)
    _write_preset(work / "p.yaml", work / "cat")
    return work / "p.yaml", work / "sprites"


def _new_preview(preset_path_cfg: Path | str | None, **extra: Any):
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    ctx = MagicMock()
    ctx.config = {"preset_path": None if preset_path_cfg is None else str(preset_path_cfg), **extra}
    plugin = LayerPreviewPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


def _within_deadline(fn: Callable[[], Any]) -> Any:
    """Вызов `fn` в daemon-потоке с дедлайном: зависание = падение теста, а не подвисший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["res"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(_DEADLINE_S)
    assert not thread.is_alive(), f"preset.sprites не вернулся за {_DEADLINE_S} с — обход завис"
    if "exc" in box:
        raise box["exc"]
    return box["res"]


def _sprites_ok(plugin) -> dict:
    res = _within_deadline(lambda: plugin.cmd_preset_sprites({}))
    assert isinstance(res, dict) and res.get("status") == "ok", res
    return res


def _paths(res: dict) -> list[str]:
    return [entry["path"] for entry in res["files"]]


def _symlink_or_skip(target: Path, link: Path, *, is_dir: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"ОС не даёт создать симлинк ({type(exc).__name__}: {exc}) — проверка не выполнена")


def _junction_or_skip(link: Path, target: Path) -> None:
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if proc.returncode != 0:
        pytest.skip(f"mklink /J не удался (код {proc.returncode}) — проверка не выполнена")


# --------------------------------------------------------------------------- #
# 1-2. Обход: петли, выход за ограду, «каталог с расширением .png»            #
# --------------------------------------------------------------------------- #


def test_symlink_dir_loop_terminates_and_lists_each_file_once(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "a.png")
    _symlink_or_skip(sprites_dir, sprites_dir / "loop", is_dir=True)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["a.png"], res["files"]


@pytest.mark.skipif(os.name != "nt", reason="junction — только Windows")
def test_junction_loop_terminates_and_lists_each_file_once(tmp_path: Path) -> None:
    """`os.walk` заходит в junction (не считает его симлинком): без выкидывания из обхода петля
    `loop -> sprites` даёт `a.png` + `loop/a.png` + `loop/loop/a.png` ... (~32 дубля)."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "a.png")
    _junction_or_skip(sprites_dir / "loop", sprites_dir)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    try:
        res = _sprites_ok(plugin)
    finally:
        os.rmdir(sprites_dir / "loop")  # junction снимается rmdir, а не rmtree — rmtree пошёл бы внутрь

    assert _paths(res) == ["a.png"], res["files"]


def test_symlinked_dir_pointing_outside_fence_leaks_nothing(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "ok.png")
    outside = tmp_path / "outside_dir"
    _write_png(outside / "x.png")
    _symlink_or_skip(outside, sprites_dir / "out", is_dir=True)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["ok.png"], res["files"]


def test_file_symlink_loop_is_skipped_not_fatal(tmp_path: Path) -> None:
    """`a.png -> b.png -> a.png`: `resolve()` такой пары бросает или возвращает мусор — файл пропускается,
    остальные файлы в ответе остаются."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "ok.png")
    _symlink_or_skip(sprites_dir / "b.png", sprites_dir / "a.png", is_dir=False)
    _symlink_or_skip(sprites_dir / "a.png", sprites_dir / "b.png", is_dir=False)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["ok.png"], res["files"]


def test_directory_named_like_png_is_not_a_file(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "d.png" / "in.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert _paths(res) == ["d.png/in.png"], res["files"]


# --------------------------------------------------------------------------- #
# 3. relpath: кириллица/пробелы в каталогах, разные диски                     #
# --------------------------------------------------------------------------- #


def test_cyrillic_and_spaces_in_preset_dir_and_sprites_dir(tmp_path: Path) -> None:
    """Кириллица и пробел не в имени файла (это у тестера), а в самих каталогах пресета и картинок."""
    work = tmp_path / "мой пресет"
    sprites_dir = work / "картинки 2"
    sprites_dir.mkdir(parents=True)
    _write_preset(work / "p.yaml", work / "cat")
    _write_png(sprites_dir / "буква а.png", 14, 6)
    plugin = _new_preview(work / "p.yaml", sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert res["files"] == [{"path": "буква а.png", "sprite_source": "картинки 2/буква а.png"}], res["files"]
    preset = ScenePreset.from_yaml(work / "p.yaml").to_dict()
    preset["layers"] = [{"name": "u", "mode": "static", "sprite_source": res["files"][0]["sprite_source"]}]
    layout = plugin.cmd_preset_layout({"preset": preset})
    assert layout.get("status") == "ok", layout
    assert {layer["name"]: layer["size_px"] for layer in layout["layers"]}["u"] == [14, 6], layout["layers"]


@pytest.mark.skipif(os.name != "nt", reason="диски — только Windows")
def test_sprite_entry_across_drives_raises_value_error() -> None:
    """Контракт шва для 1.3h-d: между дисками `sprite_entry` бросает `ValueError` (вызывающий решает)."""
    from Plugins.sim.layer_preview.plugin import sprite_entry

    with pytest.raises(ValueError):
        sprite_entry(Path("C:/a/b.png"), Path("C:/a"), Path("D:/p"))


@pytest.mark.skipif(os.name != "nt", reason="диски — только Windows")
def test_file_on_another_drive_from_preset_dir_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Каталог пресета хоста на другом диске, чем `sprites_dir`: для каждого файла `relpath` бросает
    `ValueError` -> список пуст, ответ `ok` (а не исключение на весь запрос).
    Диск пресета несуществующий: `sprites` читает только путь, файла пресета не открывает.
    Буква берётся вне маски `GetLogicalDrives()`: она включает и сетевые диски, в том числе отключённые,
    а `resolve()` на отключённом сетевом диске ждёт сетевой таймаут (так тест вис на `Z:`)."""
    import ctypes
    import string

    import Plugins.sim.layer_preview.plugin as plugin_module

    root = tmp_path / "root"
    sprites_dir = root / "sprites"
    _write_png(sprites_dir / "a.png")
    monkeypatch.setattr(plugin_module, "REPO_ROOT", root.resolve())
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    free = [c for i, c in enumerate(string.ascii_uppercase) if i >= 2 and not mask >> i & 1]
    if not free:
        pytest.skip("все буквы дисков заняты")
    other_drive = f"{free[-1]}:"
    plugin = _new_preview(f"{other_drive}\\presets\\p.yaml", sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert res["files"] == [], res["files"]
    assert res["truncated"] is False


# --------------------------------------------------------------------------- #
# 4. Шов для 1.3h-d: запись -> слой -> preset.layout, `..` в sprite_source     #
# --------------------------------------------------------------------------- #


def test_entry_round_trip_with_parent_segments_in_sprite_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пресет `root/presets/nested/p.yaml`, картинки `root/sprites/` (НЕ под каталогом пресета):
    `sprite_source` = `../../sprites/...`; он проходит ограду (внутри корня) и грузится `preset.layout`
    с размером именно этого файла."""
    import Plugins.sim.layer_preview.plugin as plugin_module

    root = tmp_path / "root"
    preset_path = root / "presets" / "nested" / "p.yaml"
    _write_preset(preset_path, root / "cat")
    sprites_dir = root / "sprites"
    _write_png(sprites_dir / "a.png", 24, 12)
    _write_png(sprites_dir / "sub" / "b.png", 10, 30)
    monkeypatch.setattr(plugin_module, "REPO_ROOT", root.resolve())
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    res = _sprites_ok(plugin)

    assert res["files"] == [
        {"path": "a.png", "sprite_source": "../../sprites/a.png"},
        {"path": "sub/b.png", "sprite_source": "../../sprites/sub/b.png"},
    ], res["files"]
    assert res["dir"] == "sprites", res["dir"]  # внутри (подменённого) корня репо — от корня
    preset = ScenePreset.from_yaml(preset_path).to_dict()
    preset["layers"] = [
        {"name": "la", "mode": "static", "sprite_source": res["files"][0]["sprite_source"]},
        {"name": "lb", "mode": "static", "sprite_source": res["files"][1]["sprite_source"]},
    ]
    layout = plugin.cmd_preset_layout({"preset": preset})
    assert layout.get("status") == "ok", layout
    sizes = {layer["name"]: layer["size_px"] for layer in layout["layers"]}  # первый слой — авто-`base`
    assert (sizes["la"], sizes["lb"]) == ([24, 12], [10, 30]), sizes


# --------------------------------------------------------------------------- #
# 5. Отказы и умолчание                                                        #
# --------------------------------------------------------------------------- #


def test_non_dict_body_is_bad_request(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))

    for body in ([], "x", 5):
        res = plugin.cmd_preset_sprites(body)  # type: ignore[arg-type]
        assert res.get("status") == "error" and res.get("code") == "bad_request", (body, res)
    assert plugin.cmd_preset_sprites(None).get("status") == "ok"  # как у соседних команд: None == {}


def test_sprites_dir_that_is_a_file_is_io_error(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    not_a_dir = sprites_dir / "file_zq9.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    plugin = _new_preview(preset_path, sprites_dir=str(not_a_dir))

    res = plugin.cmd_preset_sprites({})

    assert res.get("status") == "error" and res.get("code") == "io_error", res
    assert "file_zq9.txt" in str(res.get("message")), res


def test_default_dir_missing_is_io_error_then_listed_once_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Свежий клон: `data/line_sim` нет (`data/` в .gitignore) -> `io_error`, не исключение; появился
    каталог -> тот же плагин без перенастройки отдаёт список, `dir` = `data/line_sim` от корня репо.
    Корень репо подменён на пустой каталог: настоящий `data/line_sim` на машине не должен влиять на тест."""
    import Plugins.sim.layer_preview.plugin as plugin_module
    import Services.line_sim.core.preset as preset_module

    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(plugin_module, "REPO_ROOT", root.resolve())
    monkeypatch.setattr(preset_module, "REPO_ROOT", root.resolve())
    plugin = _new_preview(None)  # без sprites_dir в конфиге — умолчание

    missing = plugin.cmd_preset_sprites({})
    assert missing.get("status") == "error" and missing.get("code") == "io_error", missing
    assert "line_sim" in str(missing.get("message")), missing

    _write_png(root / "data" / "line_sim" / "a.png")
    res = _sprites_ok(plugin)

    assert res["dir"] == "data/line_sim", res["dir"]
    assert res["files"] == [{"path": "a.png", "sprite_source": "data/line_sim/a.png"}], res["files"]
