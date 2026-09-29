# -*- coding: utf-8 -*-
"""Hazard-тесты автора для команд пресета `scene_source` (Task 1.2a, план line-sim-layer-editor).

Что может сломаться в ЭТОМ механизме, как он построен (поток команд пишет файл и кладёт
фабрику в однослотовую передачу, воркер `produce()` забирает её перед `tick()`):
- гонка commit ↔ produce: исключение в кадре, битый кадр, или в силе остаётся НЕ последняя
  фабрика (потерянное обновление между «прочитал слот» и «обнулил слот» в воркере);
- проигравший гонку `rev` всё-таки кладёт свою фабрику в слот — лента живёт по пресету,
  которого нет в файле;
- невыпущенный форс-брак старой фабрики теряется при подмене;
- сбой записи оставляет полфайла или мусорный tmp рядом с пресетом;
- (preview — теперь `Plugins.sim.layer_preview`, свой процесс; его hazard-тесты там);
- `base_dir` из запроса клиента решает, откуда читать картинки.

Своя фикстура (не импорт из `test_acceptance_1_2a_preset_commands.py` тестера): пресет
с ОТНОСИТЕЛЬНЫМИ путями (`cat`, `disk.png`) — иначе тест про `base_dir` вакуумен, — и режим
`spawn_spacing_mm` вместо `spawn_interval_s`, чтобы спавн близнецов зависел только от
энкодера, а не от настенных часов между двумя вызовами `produce()`.
"""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import yaml

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.core.belt import FACTOR_MM

pytestmark = pytest.mark.timeout(60)

FRAME = 64
#: шаг энкодера на кадр = 3 мм пути ленты (шаг спавна 2..4 мм — объект почти каждый кадр)
_ENC_STEP = 3.0 / FACTOR_MM


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit_encoder(self, value: float) -> None:
        delta = Delta(path="sim.belt.encoder", old_value=MISSING, new_value={"value": value}, source="robot")
        for cb in self._callbacks:
            cb([delta])

    def set(self, path: str, value: object) -> None:
        pass


def _make_fixture(tmp_path: Path) -> Path:
    """cat/A/0.png + disk.png + preset.yaml с ОТНОСИТЕЛЬНЫМИ путями; диск белый."""
    class_dir = tmp_path / "cat" / "A"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((20, 20, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    disk = np.full((30, 30, 4), 255, dtype=np.uint8)
    imwrite_unicode(tmp_path / "disk.png", cv2.cvtColor(disk, cv2.COLOR_RGBA2BGRA))
    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump(
            {
                "catalog_dir": "cat",
                "angle_range_deg": [0.0, 0.0],
                "defect_probability": 0.0,
                "layers": [
                    {"name": "disk", "mode": "static", "sprite_source": "disk.png", "color_rgb": [255, 255, 255]},
                    {"name": "letter", "mode": "static", "sprite_source": "class://", "color_rgb": [0, 0, 0]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return preset_path


def _new_plugin(preset_path: Path) -> tuple[SceneSourcePlugin, _FakeStateProxy]:
    sp = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = sp
    ctx.config = {
        "resolution_width": FRAME,
        "resolution_height": FRAME,
        "px_per_mm": 1.0,
        "belt_y_px": FRAME / 2,
        "spawn_spacing_mm": [2.0, 4.0],
        "scene_length_mm": 1_000_000.0,
        "preset_path": str(preset_path),
        "seed": 3,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert plugin._compositor is not None, f"движок не собрался (фикстура): {ctx.log_error.call_args_list}"
    plugin.start(ctx)
    return plugin, sp


def _cmd(plugin: SceneSourcePlugin, name: str, data: dict) -> dict:
    return getattr(plugin, plugin.commands[name])(data)


def _rev(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied_disk_color(plugin: SceneSourcePlugin) -> tuple[int, ...]:
    """Цвет диска у фабрики, которой РЕАЛЬНО пользуется спавнер (белый ящик)."""
    return tuple(plugin._spawner._factory._preset.layers[0].color_rgb)


def _with_color(preset_dict: dict, color: list[int]) -> dict:
    d = copy.deepcopy(preset_dict)
    d["layers"][0]["color_rgb"] = color
    return d


# --------------------------------------------------------------------------- #


def test_commit_racing_produce_last_commit_wins_and_frames_stay_valid(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, sp = _new_plugin(preset_path)
    colors = [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0], [0, 255, 255], [255, 0, 255]] * 3
    errors: list[BaseException] = []
    done = threading.Event()

    def committer() -> None:
        try:
            for color in colors:
                got = _cmd(plugin, "preset.get", {})
                res = _cmd(
                    plugin, "preset.commit", {"preset": _with_color(got["preset"], color), "base_rev": got["rev"]}
                )
                assert res["status"] == "ok", res
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=committer, daemon=True)
    t.start()
    encoder, frames = 0.0, 0
    stop_at = time.monotonic() + 20.0
    while not done.is_set() and time.monotonic() < stop_at:
        encoder += _ENC_STEP
        sp.emit_encoder(encoder)
        frame = plugin.produce()[0]["frame"]
        assert frame.shape == (FRAME, FRAME, 3) and frame.dtype == np.uint8
        frames += 1
    t.join(5)
    assert not t.is_alive(), "committer завис"
    assert not errors, errors
    assert frames > 0, "produce() ни разу не выполнился параллельно с commit'ами — гонки не было"

    plugin.produce()  # воркер забирает последнюю переданную фабрику
    assert _applied_disk_color(plugin) == (255, 0, 255), "в силе не фабрика последнего commit'а"
    assert yaml.safe_load(preset_path.read_text(encoding="utf-8"))["layers"][0]["color_rgb"] == [255, 0, 255]


def test_conflict_loser_leaves_no_pending_factory_sequential(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    base_rev = got["rev"]

    ok = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": base_rev})
    lost = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [0, 255, 0]), "base_rev": base_rev})
    assert ok["status"] == "ok" and lost.get("code") == "conflict", (ok, lost)

    sp.emit_encoder(_ENC_STEP)
    plugin.produce()
    assert _applied_disk_color(plugin) == (255, 0, 0), "в силе фабрика проигравшего commit'а"


def test_conflict_loser_leaves_no_pending_factory_threaded(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, dict] = {}

    def commit(key: str, color: list[int]) -> Callable[[], None]:
        def _run() -> None:
            barrier.wait()
            results[key] = _cmd(
                plugin, "preset.commit", {"preset": _with_color(got["preset"], color), "base_rev": got["rev"]}
            )

        return _run

    threads = [
        threading.Thread(target=commit("red", [255, 0, 0]), daemon=True),
        threading.Thread(target=commit("green", [0, 255, 0]), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
        assert not t.is_alive(), "commit завис"

    winners = [k for k, r in results.items() if r["status"] == "ok"]
    assert len(winners) == 1, results
    expected = (255, 0, 0) if winners[0] == "red" else (0, 255, 0)
    sp.emit_encoder(_ENC_STEP)
    plugin.produce()
    assert _applied_disk_color(plugin) == expected
    assert tuple(yaml.safe_load(preset_path.read_text(encoding="utf-8"))["layers"][0]["color_rgb"]) == expected


def test_forced_defect_pending_survives_commit(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, sp = _new_plugin(preset_path)
    plugin._spawner.force_defect_next()  # нажатие оператора ДО commit, объект ещё не выпущен

    got = _cmd(plugin, "preset.get", {})
    res = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": got["rev"]})
    assert res["status"] == "ok", res

    sp.emit_encoder(_ENC_STEP)
    plugin.produce()  # подмена + первый спавн режима spacing_mm (первый tick спавнит сразу)
    objs = plugin._spawner.active_objects()
    assert len(objs) == 1, "первый tick spacing_mm должен был выпустить объект"
    assert _applied_disk_color(plugin) == (255, 0, 0), "подмена не применилась до tick()"
    assert objs[0].passport.defect == "damaged", "форс-брак потерян при горячей подмене фабрики"


def test_io_error_on_replace_keeps_file_and_leaves_no_tmp(tmp_path, monkeypatch):
    preset_path = _make_fixture(tmp_path)
    plugin, sp = _new_plugin(preset_path)
    before_bytes = preset_path.read_bytes()
    before_files = sorted(p.name for p in tmp_path.iterdir())
    got = _cmd(plugin, "preset.get", {})

    def boom(src, dst):
        raise OSError("диск отвалился")

    monkeypatch.setattr(os, "replace", boom)
    res = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": got["rev"]})
    monkeypatch.undo()

    assert res["status"] == "error" and res["code"] == "io_error", res
    assert preset_path.read_bytes() == before_bytes
    assert sorted(p.name for p in tmp_path.iterdir()) == before_files, "tmp-файл остался рядом с пресетом"
    sp.emit_encoder(_ENC_STEP)
    plugin.produce()
    assert _applied_disk_color(plugin) == (255, 255, 255), "фабрика неудачного commit'а применилась"


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX-права, не root")
def test_io_error_on_read_only_dir(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, _sp = _new_plugin(preset_path)
    before_bytes = preset_path.read_bytes()
    before_files = sorted(p.name for p in tmp_path.iterdir())
    got = _cmd(plugin, "preset.get", {})
    os.chmod(tmp_path, 0o555)
    try:
        res = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": got["rev"]})
    finally:
        os.chmod(tmp_path, 0o755)
    assert res["status"] == "error" and res["code"] == "io_error", res
    assert preset_path.read_bytes() == before_bytes
    assert sorted(p.name for p in tmp_path.iterdir()) == before_files


def test_commit_keeps_file_mode(tmp_path):
    preset_path = _make_fixture(tmp_path)
    os.chmod(preset_path, 0o644)
    # Свойство — «commit не меняет права файла»: сравниваем с правами ДО, а не с литералом.
    # На Windows chmod трогает только бит «только чтение», и st_mode пишемого файла всегда
    # 0o666 (не 0o644) — литерал там недостижим; на POSIX точное 0o644 держит предусловие.
    mode_before = stat.S_IMODE(preset_path.stat().st_mode)
    if os.name == "posix":
        assert mode_before == 0o644, mode_before
    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    res = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": got["rev"]})
    assert res["status"] == "ok", res
    mode_after = stat.S_IMODE(preset_path.stat().st_mode)
    assert mode_after == mode_before, (
        f"commit сменил права пресета: {mode_before:o} -> {mode_after:o} (tmp создаётся 0600)"
    )


def test_client_base_dir_is_ignored(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    elsewhere = tmp_path.parent / f"elsewhere-{uuid.uuid4().hex}"
    assert not elsewhere.exists()
    preset_dict = {**_with_color(got["preset"], [255, 0, 0]), "base_dir": str(elsewhere)}
    assert preset_dict["layers"][0]["sprite_source"] == "disk.png", "фикстура обязана держать относительный путь"

    res = _cmd(plugin, "preset.commit", {"preset": preset_dict, "base_rev": got["rev"]})
    assert res["status"] == "ok", res
    assert res["rev"] == _rev(preset_path)
    written = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    assert written["layers"][0]["sprite_source"] == "disk.png" and written["catalog_dir"] == "cat"
    assert "base_dir" not in written


# --------------------------------------------------------------------------- #
# Ревью 1.2a it.1 -> it.2: S2 (commit без движка),
# S3 (пути клиента — только в корне репозитория или каталоге пресета), S4 (запись
# только изменившихся ключей, комментарии), N3 (файл 0444).
# --------------------------------------------------------------------------- #

_HEADER = "# заголовок пресета — см. README\n"
_ANGLE_COMMENT = "# угол — комментарий нетронутого ключа\n"


def _add_comments(preset_path: Path) -> None:
    text = preset_path.read_text(encoding="utf-8")
    assert "angle_range_deg:" in text
    text = text.replace("angle_range_deg:", _ANGLE_COMMENT + "angle_range_deg:", 1)
    preset_path.write_text(_HEADER + text, encoding="utf-8")


def _outside_png(tmp_path: Path) -> Path:
    """Существующий валидный RGBA-png ВНЕ корня репозитория и ВНЕ каталога пресета (tmp_path)."""
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
    outside.mkdir()
    img = np.full((10, 10, 4), 200, dtype=np.uint8)
    imwrite_unicode(outside / "x.png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA))
    return outside / "x.png"


def test_commit_unchanged_preset_does_not_write_or_change_rev(tmp_path):
    preset_path = _make_fixture(tmp_path)
    _add_comments(preset_path)
    plugin, _sp = _new_plugin(preset_path)
    before = preset_path.read_bytes()
    got = _cmd(plugin, "preset.get", {})
    res = _cmd(plugin, "preset.commit", {"preset": got["preset"], "base_rev": got["rev"]})
    assert res == {"status": "ok", "rev": got["rev"], "changed": False}, res
    assert preset_path.read_bytes() == before
    assert len(plugin._pending_factory) == 0, "commit без изменений подменил фабрику"


def test_commit_keeps_top_level_comments_of_untouched_keys(tmp_path):
    preset_path = _make_fixture(tmp_path)
    _add_comments(preset_path)
    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    new_preset = _with_color(got["preset"], [255, 0, 0])
    res = _cmd(plugin, "preset.commit", {"preset": new_preset, "base_rev": got["rev"]})
    assert res["status"] == "ok" and res["changed"] is True and res["applied"] is True, res
    assert res["rev"] == _rev(preset_path)
    text = preset_path.read_text(encoding="utf-8")
    assert text.startswith(_HEADER), text[:200]
    assert _ANGLE_COMMENT in text, text
    assert yaml.safe_load(text)["angle_range_deg"] == [0.0, 0.0]
    again = _cmd(plugin, "preset.get", {})
    assert again["preset"] == new_preset
    assert again["engine"] is True


def test_client_path_outside_repo_rejected_without_existence_oracle(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    before = preset_path.read_bytes()
    existing = _outside_png(tmp_path)
    missing = existing.parent / "nope.png"
    assert existing.exists() and not missing.exists()

    def with_sprite(src: str) -> dict:
        d = copy.deepcopy(got["preset"])
        d["layers"][0]["sprite_source"] = src
        return d

    variants = {
        "abs-existing": with_sprite(str(existing)),
        "abs-missing": with_sprite(str(missing)),
        "rel-existing": with_sprite(f"../{existing.parent.name}/x.png"),
        "rel-missing": with_sprite(f"../{existing.parent.name}/nope.png"),
        "catalog-existing": {**got["preset"], "catalog_dir": str(existing.parent)},
        "catalog-missing": {**got["preset"], "catalog_dir": str(existing.parent / "nodir")},
    }
    messages = set()
    for label, preset_dict in variants.items():
        res = _cmd(plugin, "preset.commit", {"preset": preset_dict, "base_rev": got["rev"]})
        assert res["status"] == "error" and res["code"] == "invalid", (label, res)
        messages.add(res["message"])
    assert len(messages) == 1, f"сообщение зависит от существования файла: {messages}"
    assert str(existing.parent) not in next(iter(messages))
    assert preset_path.read_bytes() == before

    # Корень репозитория — разрешён: несуществующий путь под ним проходит ограду и падает
    # уже на чтении (другое сообщение); каталог файла пресета — см. test_client_base_dir_is_ignored.
    from Plugins.sim.scene_source.plugin import _REPO_ROOT

    in_repo = with_sprite(str(_REPO_ROOT / f"no-such-{uuid.uuid4().hex}.png"))
    res = _cmd(plugin, "preset.commit", {"preset": in_repo, "base_rev": got["rev"]})
    assert res["status"] == "error" and res["message"] not in messages, res
    assert preset_path.read_bytes() == before


def test_commit_without_engine_writes_file_applied_false(tmp_path):
    preset_path = _make_fixture(tmp_path)
    (tmp_path / "disk.png").rename(tmp_path / "disk2.png")  # опечатка в файле -> движок не собрался
    sp = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = sp
    ctx.config = {"resolution_width": FRAME, "resolution_height": FRAME, "preset_path": str(preset_path), "seed": 3}
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert plugin._spawner is None, "фикстура: движок должен был не собраться"

    got = _cmd(plugin, "preset.get", {})
    assert got["status"] == "ok" and got["engine"] is False, got
    fixed = copy.deepcopy(got["preset"])
    fixed["layers"][0]["sprite_source"] = "disk2.png"
    res = _cmd(plugin, "preset.commit", {"preset": fixed, "base_rev": got["rev"]})
    assert res["status"] == "ok" and res["applied"] is False, res
    assert res["message"] == "движок не запущен — применится после перезапуска"
    assert res["rev"] == _rev(preset_path) != got["rev"]
    assert yaml.safe_load(preset_path.read_text(encoding="utf-8"))["layers"][0]["sprite_source"] == "disk2.png"
    assert len(plugin._pending_factory) == 0
    frame = plugin.produce()[0]["frame"]
    assert frame.shape == (FRAME, FRAME, 3)

    broken = copy.deepcopy(fixed)
    broken["layers"][0]["sprite_source"] = "still-missing.png"
    bad = _cmd(plugin, "preset.commit", {"preset": broken, "base_rev": res["rev"]})
    assert bad["status"] == "error" and bad["code"] == "invalid", "без движка commit обязан валидировать"


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX-права, не root")
def test_commit_read_only_file_io_error(tmp_path):
    preset_path = _make_fixture(tmp_path)
    plugin, _sp = _new_plugin(preset_path)
    got = _cmd(plugin, "preset.get", {})
    before = preset_path.read_bytes()
    os.chmod(preset_path, 0o444)
    try:
        res = _cmd(plugin, "preset.commit", {"preset": _with_color(got["preset"], [255, 0, 0]), "base_rev": got["rev"]})
        mode = preset_path.stat().st_mode & 0o777
    finally:
        os.chmod(preset_path, 0o644)
    assert res["status"] == "error" and res["code"] == "io_error", res
    assert preset_path.read_bytes() == before and mode == 0o444
    assert len(plugin._pending_factory) == 0
