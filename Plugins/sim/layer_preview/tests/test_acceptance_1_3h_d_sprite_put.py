# -*- coding: utf-8 -*-
"""RED-приёмка Task 1.3h-d (бэкенд) — команда `preset.sprite_put` на `LayerPreviewPlugin`.

Слепой прогон независимого tester, worktree `d-tester-be` на коммите `b2103448` (коммит
спецификации, реализации нет). Единственный источник ожидаемых значений — раздел «Команда
`preset.sprite_put`» плана `plans/line-sim-layer-editor/task-1.3h-d-upload.md`:

- тело `{name, png_b64}`; девять проверок -> коды (`bad_request`, `io_error`, `conflict`, `invalid`);
- успех `{status: "ok", file: {path, sprite_source}}`, `file` — та же форма, что элемент `files`
  у `preset.sprites`; сохранённое имя — ОЧИЩЕННОЕ (символы вне Unicode `[\\w.-]` -> `_`);
- потолок декодированных байт `SPRITE_PUT_MAX_BYTES = 6_291_456`; `.uploading` не остаётся никогда;
- после любого отказа `sprites_dir` побайтно прежний и НИЧЕГО не записано вне него.

Механизм записи (mkstemp/os.link/fsync) НЕ закреплён: тесты смотрят на наблюдаемое (что лежит на
диске после вызова), а не на имена вызовов. «Ничего не записано» проверяется снимком всего
`tmp_path` (байты каждого файла + каталоги) до и после: `../x.png` иначе мог бы тихо лечь в `work/`.

Фикстура — копия паттерна `test_acceptance_1_3h_c_sprites.py` (не импорт из чужого теста): конфиг
с `sprites_dir` в `tmp_path` и файлом пресета `.yaml`, поэтому `base_dir` — каталог пресета, ограда —
корень репозитория + каталог пресета. Всё во временном каталоге вне репозитория. Ожидаемые значения
— литералы.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import CLASS_SPRITE_SOURCE, LayerSpec, ScenePreset

SPRITE_PUT_MAX_BYTES = 6_291_456  # литерал из контракта: 6 МиБ декодированных байт

# --------------------------------------------------------------------------- #
# Фикстура                                                                    #
# --------------------------------------------------------------------------- #


def _rgba_png(w: int = 8, h: int = 8, fill: int = 128) -> bytes:
    """Настоящий RGBA PNG `w x h`, непрозрачный, серый уровня `fill` (разные `fill` — разные байты)."""
    arr = np.full((h, w, 4), fill, dtype=np.uint8)
    arr[:, :, 3] = 255
    ok, buf = cv2.imencode(".png", arr)
    assert ok
    return buf.tobytes()


def _rgb_png() -> bytes:
    """PNG без альфа-канала (3 канала) — для контракта п.8 это `invalid`."""
    ok, buf = cv2.imencode(".png", np.full((8, 8, 3), 90, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _gray_png() -> bytes:
    ok, buf = cv2.imencode(".png", np.full((8, 8), 90, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _write_png(path: Path, w: int = 8, h: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = 128
    rgba[:, :, 3] = 255
    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def _make_world(tmp_path: Path) -> tuple[Path, Path]:
    """`work/p.yaml` + `work/cat/<A|B>/0.png` + пустой `work/sprites/`. Вернёт `(preset_path, sprites_dir)`."""
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


def _put(plugin, name: Any, png_b64: Any) -> dict:
    return plugin.cmd_preset_sprite_put({"name": name, "png_b64": png_b64})


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Всё под `root`: файл -> его байты, каталог -> None. Ключи — относительные, прямые слэши."""
    snap: dict[str, bytes | None] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for dirname in dirnames:
            snap[(Path(dirpath, dirname).relative_to(root)).as_posix()] = None
        for filename in filenames:
            file = Path(dirpath, filename)
            snap[file.relative_to(root).as_posix()] = file.read_bytes()
    return snap


def _assert_refused(res: dict, code: str, tmp_path: Path, before: dict[str, bytes | None]) -> None:
    assert isinstance(res, dict) and res.get("status") == "error" and res.get("code") == code, (
        f"ждали error/{code}, получили {res!r}"
    )
    after = _snapshot(tmp_path)
    assert after == before, (
        f"после отказа {code} диск изменился: добавлено {sorted(set(after) - set(before))}, "
        f"пропало {sorted(set(before) - set(after))}, изменено "
        f"{sorted(k for k in before.keys() & after.keys() if before[k] != after[k])}"
    )


def _fs_is_case_insensitive(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    (probe_dir / "CaseProbe.tmp").write_bytes(b"x")
    return (probe_dir / "caseprobe.tmp").exists()


# --------------------------------------------------------------------------- #
# Регистрация                                                                 #
# --------------------------------------------------------------------------- #


def test_command_registered_under_convention_name() -> None:
    from Plugins.sim.layer_preview.plugin import LayerPreviewPlugin

    assert LayerPreviewPlugin.commands.get("preset.sprite_put") == "cmd_preset_sprite_put", LayerPreviewPlugin.commands


# --------------------------------------------------------------------------- #
# Успех                                                                       #
# --------------------------------------------------------------------------- #


def test_success_saves_exact_bytes_returns_entry_and_leaves_nothing_else(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    data = _rgba_png(12, 7, fill=77)
    before = _snapshot(tmp_path)

    res = _put(plugin, "cap.png", _b64(data))

    assert res.get("status") == "ok", res
    assert res.get("file") == {"path": "cap.png", "sprite_source": "sprites/cap.png"}, res
    after = _snapshot(tmp_path)
    assert set(after) - set(before) == {"work/sprites/cap.png"}, (
        "на диске должен добавиться ровно один файл (ни .uploading, ни чего-то вне sprites_dir): "
        f"{sorted(set(after) - set(before))}"
    )
    assert after["work/sprites/cap.png"] == data, "сохранённый файл не побайтно равен присланному"
    assert {k: v for k, v in after.items() if k in before} == before, "существующее содержимое изменилось"


def test_success_is_visible_to_preset_sprites_and_loads_in_layout(tmp_path: Path) -> None:
    """`preset.sprites` сразу видит файл ровно с тем же `file`, и `sprite_source` из ответа вписывается
    в слой `preset.layout` -> ok с размером ИМЕННО этого файла (12x7)."""
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    res = _put(plugin, "cap.png", _b64(_rgba_png(12, 7)))
    assert res.get("status") == "ok", res

    listing = plugin.cmd_preset_sprites({})
    preset = ScenePreset.from_yaml(preset_path).to_dict()
    preset["layers"] = [{"name": "up", "mode": "static", "sprite_source": res["file"]["sprite_source"]}]
    layout = plugin.cmd_preset_layout({"preset": preset})

    assert listing["files"] == [res["file"]], (listing["files"], res)
    assert layout.get("status") == "ok", layout
    assert {layer["name"]: layer["size_px"] for layer in layout["layers"]}["up"] == [12, 7], layout["layers"]


def test_success_at_size_ceiling_and_name_length_boundary(tmp_path: Path) -> None:
    """Обе границы «принято»: декодированные ровно 6_291_456 байт (валидный PNG + хвост нулей — декодер
    хвост игнорирует) и имя ровно из 128 символов."""
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    png = _rgba_png()
    big = png + b"\x00" * (SPRITE_PUT_MAX_BYTES - len(png))
    assert len(big) == SPRITE_PUT_MAX_BYTES
    name_128 = "n" * 124 + ".png"
    assert len(name_128) == 128

    res_big = _put(plugin, "big.png", _b64(big))
    res_128 = _put(plugin, name_128, _b64(png))

    assert res_big.get("status") == "ok", f"ровно {SPRITE_PUT_MAX_BYTES} байт должны приниматься: {str(res_big)[:200]}"
    assert res_128.get("status") == "ok", f"имя из 128 символов должно приниматься: {str(res_128)[:200]}"
    assert (sprites_dir / "big.png").read_bytes() == big
    assert (sprites_dir / name_128).read_bytes() == png


@pytest.mark.parametrize(
    ("given", "saved"),
    [
        ("мой файл!.png", "мой_файл_.png"),
        ("a b(1).png", "a_b_1_.png"),
        ("a-b.c.png", "a-b.c.png"),
        ("Big.PNG", "Big.PNG"),
    ],
    ids=["cyrillic_space_bang", "space_parens", "dash_dot_kept", "upper_suffix_kept"],
)
def test_saved_name_is_the_cleaned_one(tmp_path: Path, given: str, saved: str) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    data = _rgba_png(fill=55)
    before = _snapshot(tmp_path)

    res = _put(plugin, given, _b64(data))

    assert res.get("status") == "ok", res
    assert res.get("file") == {"path": saved, "sprite_source": f"sprites/{saved}"}, res
    after = _snapshot(tmp_path)
    assert set(after) - set(before) == {f"work/sprites/{saved}"}, sorted(set(after) - set(before))
    assert after[f"work/sprites/{saved}"] == data


# --------------------------------------------------------------------------- #
# п.1-3: тело и имя -> bad_request                                            #
# --------------------------------------------------------------------------- #

_BAD_NAMES = [
    "../x.png",
    "..\\x.png",
    "/abs.png",
    "\\abs.png",
    "C:evil.png",
    "C:\\evil.png",
    "a/b.png",
    "a\\b.png",
    "..",
    ".",
    "",
    "x.txt",
    "x",
    "x.png.txt",
    "___.png",
    "...png",
    ".png",
    "CON.png",
    "nul.PNG",
    "a" * 125 + ".png",  # 129 символов
]


@pytest.mark.parametrize("name", _BAD_NAMES, ids=[repr(n)[:24] for n in _BAD_NAMES])
def test_bad_name_is_bad_request_and_writes_nothing(tmp_path: Path, name: str) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "existing.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)

    res = _put(plugin, name, _b64(_rgba_png()))

    _assert_refused(res, "bad_request", tmp_path, before)


_MALFORMED_BODIES = [
    None,
    [],
    "text",
    {},
    {"name": "a.png"},
    {"png_b64": "AAAA"},
    {"name": 5, "png_b64": "AAAA"},
    {"name": "a.png", "png_b64": 5},
    {"name": "a.png", "png_b64": None},
    {"name": None, "png_b64": "AAAA"},
]


@pytest.mark.parametrize("body", _MALFORMED_BODIES, ids=[repr(b)[:30] for b in _MALFORMED_BODIES])
def test_malformed_body_is_bad_request_and_writes_nothing(tmp_path: Path, body: Any) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)

    res = plugin.cmd_preset_sprite_put(body)

    _assert_refused(res, "bad_request", tmp_path, before)


# --------------------------------------------------------------------------- #
# п.4: base64 и потолок                                                       #
# --------------------------------------------------------------------------- #

_BAD_B64 = [
    "not base64!!",
    "AAA",  # неверный паддинг
    "AAAA AAAA",  # пробел — вне алфавита при validate=True
    "AAAA\nAAAA",
    "data:image/png;base64," + _b64(_rgba_png()),  # префикс data-URL, который страница обязана срезать
]


@pytest.mark.parametrize("png_b64", _BAD_B64, ids=["garbage", "padding", "space", "newline", "data_url"])
def test_not_base64_is_bad_request_and_writes_nothing(tmp_path: Path, png_b64: str) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "existing.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)

    res = _put(plugin, "a.png", png_b64)

    _assert_refused(res, "bad_request", tmp_path, before)


def test_one_byte_over_decoded_ceiling_is_bad_request_and_writes_nothing(tmp_path: Path) -> None:
    """6_291_456 + 1 декодированных байт (валидный PNG + хвост) -> `bad_request`; парный тест успеха
    ровно на потолке — `test_success_at_size_ceiling_and_name_length_boundary`."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "existing.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    png = _rgba_png()
    over = png + b"\x00" * (SPRITE_PUT_MAX_BYTES + 1 - len(png))
    assert len(over) == SPRITE_PUT_MAX_BYTES + 1
    before = _snapshot(tmp_path)

    res = _put(plugin, "over.png", _b64(over))

    _assert_refused(res, "bad_request", tmp_path, before)


# --------------------------------------------------------------------------- #
# п.5-6: каталог                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("dir_exists", [False, True], ids=["absent", "present"])
def test_dir_outside_fence_is_bad_request_before_existence(tmp_path: Path, dir_exists: bool) -> None:
    """Ограда — РАНЬШЕ существования: `outside/` (брат `work/`) вне ограды и отсутствует -> `bad_request`
    (а не `io_error`); и существует -> тоже `bad_request`, ничего в него не пишется."""
    preset_path, _ = _make_world(tmp_path)
    outside = tmp_path / "outside"
    if dir_exists:
        outside.mkdir()
    plugin = _new_preview(preset_path, sprites_dir=str(outside))
    before = _snapshot(tmp_path)

    res = _put(plugin, "a.png", _b64(_rgba_png()))

    _assert_refused(res, "bad_request", tmp_path, before)


def test_absent_sprites_dir_inside_fence_is_io_error_and_not_created(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    missing = sprites_dir.parent / "sprites_missing_zq7"
    plugin = _new_preview(preset_path, sprites_dir=str(missing))
    before = _snapshot(tmp_path)

    res = _put(plugin, "a.png", _b64(_rgba_png()))

    _assert_refused(res, "io_error", tmp_path, before)
    assert not missing.exists(), "команда не должна создавать отсутствующий sprites_dir"


def test_sprites_dir_that_is_a_file_is_io_error(tmp_path: Path) -> None:
    preset_path, sprites_dir = _make_world(tmp_path)
    not_a_dir = sprites_dir.parent / "sprites_is_a_file"
    not_a_dir.write_bytes(b"i am a file")
    plugin = _new_preview(preset_path, sprites_dir=str(not_a_dir))
    before = _snapshot(tmp_path)

    res = _put(plugin, "a.png", _b64(_rgba_png()))

    _assert_refused(res, "io_error", tmp_path, before)


# --------------------------------------------------------------------------- #
# п.7: конфликт                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("existing", "uploaded"),
    [("a.png", "a.png"), ("a_b.png", "a b.png")],
    ids=["same_name", "cleaned_name_collides"],
)
def test_existing_file_is_conflict_and_untouched(tmp_path: Path, existing: str, uploaded: str) -> None:
    """Существующий файл (другие байты) не перезаписан. Конфликт проверяется по ОЧИЩЕННОМУ имени:
    `a b.png` -> `a_b.png` уже занят."""
    preset_path, sprites_dir = _make_world(tmp_path)
    (sprites_dir / existing).write_bytes(_rgba_png(fill=10))
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)

    res = _put(plugin, uploaded, _b64(_rgba_png(fill=200)))

    _assert_refused(res, "conflict", tmp_path, before)
    assert (sprites_dir / existing).read_bytes() == _rgba_png(fill=10), "существующий файл перезаписан"


def test_name_differing_only_by_case_follows_the_filesystem(tmp_path: Path) -> None:
    """`A.png` против существующего `a.png`: на ФС без учёта регистра (Windows) — `conflict`, файл не
    тронут, `A.png` не появился; на ФС с учётом регистра — успех, оба файла на месте. Ветка — по пробе ФС."""
    preset_path, sprites_dir = _make_world(tmp_path)
    insensitive = _fs_is_case_insensitive(tmp_path / "probe")
    (sprites_dir / "a.png").write_bytes(_rgba_png(fill=10))
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)
    upload = _rgba_png(fill=200)

    res = _put(plugin, "A.png", _b64(upload))

    if insensitive:
        _assert_refused(res, "conflict", tmp_path, before)
        assert (sprites_dir / "a.png").read_bytes() == _rgba_png(fill=10)
    else:
        assert res.get("status") == "ok", res
        assert (sprites_dir / "A.png").read_bytes() == upload
        assert (sprites_dir / "a.png").read_bytes() == _rgba_png(fill=10)


# --------------------------------------------------------------------------- #
# п.8: байты не RGBA-картинка                                                 #
# --------------------------------------------------------------------------- #


def _invalid_payloads() -> dict[str, bytes]:
    good = _rgba_png()
    ok, jpg = cv2.imencode(".jpg", np.full((8, 8, 3), 90, dtype=np.uint8))
    assert ok
    return {
        "rgb_no_alpha": _rgb_png(),
        "gray": _gray_png(),
        "jpeg_named_png": jpg.tobytes(),
        "garbage": b"this is not an image at all",
        "truncated_png": good[: len(good) // 2],
        "empty": b"",
    }


_INVALID = _invalid_payloads()


@pytest.mark.parametrize("payload", list(_INVALID.values()), ids=list(_INVALID))
def test_not_an_rgba_image_is_invalid_and_leaves_no_trace(tmp_path: Path, payload: bytes) -> None:
    """Не RGBA-картинка -> `invalid`; в `sprites_dir` не остаётся ничего (ни файла под финальным именем,
    ни `.uploading`); пустой декодированный буфер (валидный base64) — тоже `invalid`, а не сбой."""
    preset_path, sprites_dir = _make_world(tmp_path)
    _write_png(sprites_dir / "existing.png")
    plugin = _new_preview(preset_path, sprites_dir=str(sprites_dir))
    before = _snapshot(tmp_path)

    res = _put(plugin, "up.png", _b64(payload))

    _assert_refused(res, "invalid", tmp_path, before)
