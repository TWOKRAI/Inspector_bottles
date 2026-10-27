# -*- coding: utf-8 -*-
"""Приёмка Task 1.1c (C-30): записи через стор по slug не шумят в файле рецепта.

Матрица ``plans/2026-10-26_recipe-save-noise/design.md`` §6 — строки «Дисплеи», «Камера»,
«Устройства», «Раскладка», CRLF. Цепочка настоящая: ``DisplayCatalogFromRecipe`` /
``CameraSettingsPresenter`` / ``RecipeDevicesStore`` -> ``RecipeStoreFromManager`` ->
``RecipeManager`` -> файл в ``tmp_path`` (движок ``FakeEngine``, как в
``adapters/tests/test_recipe_store.py``).

Фикстура A — ``fixtures/letter_robot_sim_pre_c30.yaml`` (600 строк, комментарии T3.7 x2, Task 5.3b, flow-карты).
Байты строит тест: LF-копия = ``fixture.read_bytes().replace(b"\\r\\n", b"\\n")``, CRLF-вариант — из неё.
Сравнение — байты файла до/после; строки диффа — литералы. Новый API (``read_raw_with_rev``, ``RecipeConflict``)
берётся атрибутом внутри тела теста: пока его нет, тест красный, а файл собирается.
"""

from __future__ import annotations

import copy
import dataclasses
import difflib
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_RECIPES_DIR = _HERE.parent
_FIXTURE_A = _HERE / "fixtures" / "letter_robot_sim_pre_c30.yaml"

_SLUG = "letter_robot_sim"
_OLD_MTIME_NS = 1_700_000_000_000_000_000
_ALL_SLUGS = sorted(p.stem for p in _RECIPES_DIR.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Обвязка (импортируется и подпроцессом hash-seed теста)
# ---------------------------------------------------------------------------


class FakeEngine:
    """Минимальный движок рецептов: ``recipes_dir`` + активный slug (как adapters/tests/test_recipe_store.py)."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir
        self._active_name: str | None = None

    def get_active(self) -> str | None:
        return self._active_name

    def set_active(self, name: str) -> bool:
        if not (self.recipes_dir / f"{name}.yaml").exists():
            return False
        self._active_name = name
        return True

    def deactivate(self) -> None:
        self._active_name = None

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.recipes_dir.glob("*.yaml"))

    def load(self, name: str, remap: dict[str, str] | None = None) -> list:
        if not (self.recipes_dir / f"{name}.yaml").exists():
            raise FileNotFoundError(name)
        self._active_name = name
        return []


def fixture_a_lf() -> bytes:
    """LF-байты фикстуры A (checkout мог превратить её в CRLF — нормализуем)."""
    return _FIXTURE_A.read_bytes().replace(b"\r\n", b"\n")


def build_chain(recipes_dir: Path, slug: str) -> Any:
    """Настоящие RecipeManager + RecipeStoreFromManager над ``recipes_dir``; активный рецепт = slug."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

    engine = FakeEngine(recipes_dir)
    engine.set_active(slug)
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    # format_hook добавляет Task 1.1e; без параметра тест обязан краснеть (TypeError), а не идти без хука.
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, format_hook=InspectorRecipeFormatHook())
    return RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)


def build_catalog(store: Any, slug: str) -> Any:
    from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe

    return DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: slug)


def _put(directory: Path, slug: str, data: bytes) -> Path:
    path = directory / f"{slug}.yaml"
    path.write_bytes(data)
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    return path


def run_phone_toggle_pair(directory: Path) -> bytes:
    """Дисплей phone: enabled False -> True -> False через настоящую цепочку; вернуть итоговые байты файла."""
    src = fixture_a_lf()
    path = _put(directory, _SLUG, src)
    catalog = build_catalog(build_chain(directory, _SLUG), _SLUG)
    spec = catalog.resolve("phone")
    assert catalog.update(dataclasses.replace(spec, enabled=True)) is True
    assert catalog.update(spec) is True
    return path.read_bytes()


def _diff(before: bytes, after: bytes, eol: str = "\n") -> list[str]:
    """Строки диффа ('-...'/'+...') без заголовков и @@; строки разбиты по ``eol``."""
    a = before.decode("utf-8").split(eol)
    b = after.decode("utf-8").split(eol)
    out = list(difflib.unified_diff(a, b, lineterm="", n=0))[2:]
    return [line for line in out if not line.startswith("@@")]


def _within(seconds: float, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший лок/запись даёт явный fail, а не вечный прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"{getattr(fn, '__name__', fn)!r} не вернулся за {seconds} с")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _plain(obj: Any) -> Any:
    """ruamel/pydantic-подобные контейнеры -> чистые dict/list/скаляры."""
    return json.loads(json.dumps(obj, default=str))


# ---------------------------------------------------------------------------
# Дисплеи
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["fixture_a", *_ALL_SLUGS], ids=["fixture_a", *_ALL_SLUGS])
def test_displays_persist_no_edit_is_byte_identical(tmp_path: Path, case: str) -> None:
    """persist() без правок не пишет: байты и st_mtime_ns прежние (фикстура A и все 22 живых рецепта)."""
    slug = _SLUG if case == "fixture_a" else case
    src = fixture_a_lf() if case == "fixture_a" else (_RECIPES_DIR / f"{case}.yaml").read_bytes()
    path = _put(tmp_path, slug, src)
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    catalog = build_catalog(build_chain(tmp_path, slug), slug)

    _within(60, catalog.persist)

    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


@pytest.mark.parametrize("eol_name", ["lf", "crlf"], ids=["lf", "crlf"])
def test_displays_toggle_one_line_then_pair_byte_identical(tmp_path: Path, eol_name: str) -> None:
    """update(phone, enabled=True): дифф одна строка; обратный update -> исходные байты; в CRLF нет одиночных LF."""
    eol = "\n" if eol_name == "lf" else "\r\n"
    src = fixture_a_lf()
    if eol_name == "crlf":
        src = src.replace(b"\n", b"\r\n")
    path = _put(tmp_path, _SLUG, src)
    catalog = build_catalog(build_chain(tmp_path, _SLUG), _SLUG)
    spec = catalog.resolve("phone")
    assert spec.enabled is False

    assert _within(60, catalog.update, dataclasses.replace(spec, enabled=True)) is True
    toggled = path.read_bytes()
    assert b"\r\r\n" not in toggled
    if eol_name == "crlf":
        assert toggled.count(b"\n") == toggled.count(b"\r\n")
    assert _diff(src, toggled, eol) == ["-    enabled: false", "+    enabled: true"]

    assert _within(60, catalog.update, spec) is True
    assert path.read_bytes() == src


_PHONE_REMOVED = [
    "-    - node_id: phone.phone_camera.frame",
    "-      display_id: phone",
    "-  - id: phone",
    "-    name: Фото с телефона",
    "-    enabled: false",
    "-    width: 640",
    "-    height: 480",
    "-    format: BGR",
    "-    fps_limit: 30.0",
    "-    ring_buffer_blocks: 3",
    "-    position:",
    "-      x: 700",
    "-      y: 200",
    "-    fit: contain",
    "-    scale: 100",
    "-    rotate: 0",
    "-    flip: none",
    "-    crop:",
]


def test_displays_unregister_phone_diff_literal(tmp_path: Path) -> None:
    """unregister('phone'): удалено ровно 16 строк блока ``- id: phone`` и 2 строки привязки; ничего не добавлено."""
    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    catalog = build_catalog(build_chain(tmp_path, _SLUG), _SLUG)

    assert _within(60, catalog.unregister, "phone") is True

    diff = _diff(src, path.read_bytes())
    assert len(_PHONE_REMOVED) == 18
    assert Counter(line for line in diff if line.startswith("-")) == Counter(_PHONE_REMOVED)
    assert [line for line in diff if line.startswith("+")] == []


# ---------------------------------------------------------------------------
# Камера
# ---------------------------------------------------------------------------

_CAMERA_ANCHOR = "          category: source\n          config:\n            camera_type: stream\n"
_CAMERA_PARAMS = "          fps: 25\n          mjpg: true\n          params:\n            brightness: 128\n"


def _camera_recipe_bytes() -> bytes:
    """Фикстура A, у которой плагин camera_service уже держит fps / mjpg / params.brightness."""
    text = fixture_a_lf().decode("utf-8")
    assert text.count(_CAMERA_ANCHOR) == 1
    return text.replace(
        _CAMERA_ANCHOR,
        "          category: source\n" + _CAMERA_PARAMS + _CAMERA_ANCHOR[len("          category: source\n") :],
    ).encode("utf-8")


def _camera_presenter(store: Any) -> Any:
    from multiprocess_prototype.frontend.widgets.tabs.services.camera.presenter import CameraSettingsPresenter

    return CameraSettingsPresenter(recipes=store)


def test_camera_save_no_edit_byte_identical(tmp_path: Path) -> None:
    """save() с pending, равным значениям файла (brightness/fps/mjpg): байты и st_mtime_ns прежние."""
    path = _put(tmp_path, _SLUG, _camera_recipe_bytes())
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    presenter = _camera_presenter(build_chain(tmp_path, _SLUG))
    presenter.apply_param("brightness", 128)
    presenter.apply_fps(25)
    presenter.apply_mjpg(True)

    _within(60, presenter.save)

    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


def test_camera_save_one_param_keeps_flow_style(tmp_path: Path) -> None:
    """save() с одним изменённым параметром: дифф ровно одна строка; flow-карта restart_policy на месте."""
    src = _camera_recipe_bytes()
    path = _put(tmp_path, _SLUG, src)
    presenter = _camera_presenter(build_chain(tmp_path, _SLUG))
    presenter.apply_param("brightness", 130)
    presenter.apply_fps(25)
    presenter.apply_mjpg(True)

    _within(60, presenter.save)

    after = path.read_bytes()
    assert _diff(src, after) == ["-            brightness: 128", "+            brightness: 130"]
    assert b"restart_policy: {enabled: true, max_retries: 3, window_sec: 60}\n" in after


# ---------------------------------------------------------------------------
# Устройства
# ---------------------------------------------------------------------------


def _devices_store(store: Any, slug: str) -> Any:
    from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import RecipeDevicesStore

    return RecipeDevicesStore(store, active_provider=lambda: slug)


def test_devices_upsert_port_one_field_blueprint_untouched(tmp_path: Path) -> None:
    """upsert(robot_main, transport.port=5022): дифф port 5021 -> 5022; оба ``# T3.7`` на месте; blueprint не тронут."""
    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    entry = copy.deepcopy(_plain(store.read_raw(_SLUG)["devices"][0]))
    assert entry["id"] == "robot_main"
    assert entry["transport"]["port"] == 5021
    entry["transport"]["port"] = 5022

    _within(60, _devices_store(store, _SLUG).upsert, entry)

    after = path.read_bytes()
    assert _diff(src, after) == ["-      port: 5021", "+      port: 5022"]
    assert after.count("# T3.7".encode()) == 2
    section = lambda data: data.split(b"\nblueprint:\n", 1)[1].split(b"\ndisplays:\n", 1)[0]  # noqa: E731
    assert section(after) == section(src)


_VFD_REMOVED = [
    "-  - id: vfd_belt",
    "-    name: ПЧ лента",
    "-    kind: vfd",
    "-    protocol: gd20_bridge",
    "-    transport:",
    "-      type: bridge",
    "-      bridge: robot_main",
    "-    params:",
    "-      freq_max_hz: 50.0",
    "-      default_freq_hz: 10.0",
    "-      poll_interval_s: 0.5",
    "-      stale_polls_limit: 6",
]


def test_devices_remove_vfd_belt_diff_literal(tmp_path: Path) -> None:
    """remove('vfd_belt'): удалены ровно 12 строк блока vfd_belt; ничего не добавлено."""
    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)

    _within(60, _devices_store(store, _SLUG).remove, "vfd_belt")

    diff = _diff(src, path.read_bytes())
    assert len(_VFD_REMOVED) == 12
    assert Counter(line for line in diff if line.startswith("-")) == Counter(_VFD_REMOVED)
    assert [line for line in diff if line.startswith("+")] == []


# ---------------------------------------------------------------------------
# Раскладка
# ---------------------------------------------------------------------------


def test_layout_save_one_move_keeps_flow_style_elsewhere(tmp_path: Path) -> None:
    """save_layout(позиции из файла, одна нода сдвинута): дифф одна строка; flow-карты в файле на месте."""
    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    positions = _plain(store.read_raw(_SLUG)["blueprint"]["metadata"]["gui_positions"])
    assert positions["layout.word_layout"][0] == -13.526620798676966
    positions["layout.word_layout"][0] = 100.0

    _within(60, store.save_layout, _SLUG, positions, [])

    after = path.read_bytes()
    assert _diff(src, after) == ["-        - -13.526620798676966", "+        - 100.0"]
    assert b"      restart_policy: {enabled: true, max_retries: 3, window_sec: 60}\n" in after
    assert b"      robot_params: {P_ZONE_MAX: 6000}\n" in after


# ---------------------------------------------------------------------------
# Конфликт: ручная правка между чтением и записью
# ---------------------------------------------------------------------------


def test_store_conflict_on_hand_edit_between_read_and_write(tmp_path: Path) -> None:
    """Файл правят руками между read_raw_with_rev и save_raw(expected_rev=rev): RecipeConflict, ручная правка цела."""
    import multiprocess_framework.modules.recipe as recipe_pkg

    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    raw, rev = store.read_raw_with_rev(_SLUG)
    hand_edited = src.replace(b"      port: 5021\n", b"      port: 5099\n")
    assert hand_edited != src
    path.write_bytes(hand_edited)
    mine = copy.deepcopy(_plain(raw))
    mine["devices"][0]["transport"]["port"] = 5022

    with pytest.raises(recipe_pkg.RecipeConflict):
        _within(60, store.save_raw, _SLUG, mine, expected_rev=rev)

    assert path.read_bytes() == hand_edited


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------


def test_store_list_matches_sorted_glob_on_all_recipes(tmp_path: Path) -> None:
    """list() на 22 копиях рецептов == tuple(sorted(stem каждого *.yaml)) (ревью F12)."""
    for slug in _ALL_SLUGS:
        shutil.copyfile(_RECIPES_DIR / f"{slug}.yaml", tmp_path / f"{slug}.yaml")
    store = build_chain(tmp_path, _ALL_SLUGS[0])

    result = store.list()

    assert isinstance(result, tuple)
    assert result == tuple(sorted(p.stem for p in tmp_path.glob("*.yaml")))
    assert len(result) == 22


# ---------------------------------------------------------------------------
# Вне лимита REDS (красные до GREEN)
# ---------------------------------------------------------------------------


def test_displays_register_unregister_byte_identical(tmp_path: Path) -> None:
    """register(c30_tmp) затем unregister(c30_tmp): файл возвращается к исходным байтам."""
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

    src = fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    catalog = build_catalog(build_chain(tmp_path, _SLUG), _SLUG)

    _within(60, catalog.register, DisplaySpec(display_id="c30_tmp", display_name="C30 tmp"))
    assert b"c30_tmp" in path.read_bytes()
    assert _within(60, catalog.unregister, "c30_tmp") is True

    assert path.read_bytes() == src


def test_save_raw_fresh_rev_returns_new_noop_returns_same(tmp_path: Path) -> None:
    """save_raw со свежей ревизией возвращает новую ревизию (она же читается из файла); без изменений — ту же."""
    src = fixture_a_lf()
    _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    raw, rev = store.read_raw_with_rev(_SLUG)
    changed = copy.deepcopy(_plain(raw))
    changed["devices"][0]["transport"]["port"] = 5022

    new_rev = _within(60, store.save_raw, _SLUG, changed, expected_rev=rev)

    assert new_rev != rev
    assert store.read_raw_with_rev(_SLUG)[1] == new_rev
    again = _within(60, store.save_raw, _SLUG, copy.deepcopy(changed), expected_rev=new_rev)
    assert again == new_rev


def test_displays_toggle_byte_identical_across_hash_seed(tmp_path: Path) -> None:
    """Пара update(phone) True -> False в подпроцессе при PYTHONHASHSEED 0..3: итоговые байты всегда равны исходным."""
    src = fixture_a_lf()
    code = (
        "import sys, pathlib\n"
        "from multiprocess_prototype.recipes.tests import test_save_noise_store as t\n"
        "out = t.run_phone_toggle_pair(pathlib.Path(sys.argv[1]))\n"
        "sys.stdout.write('RESULT:' + out.hex() + '\\n')\n"
    )
    results: dict[int, str | None] = {}
    for seed in range(4):
        work = tmp_path / f"seed{seed}"
        work.mkdir()
        env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=str(_REPO_ROOT), PYTHONUTF8="1")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code, str(work)],
                cwd=str(_REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"подпроцесс PYTHONHASHSEED={seed} не уложился в 180 с")
        marks = [line for line in proc.stdout.splitlines() if line.startswith("RESULT:")]
        results[seed] = marks[-1][len("RESULT:") :] if marks else None
        assert marks, f"seed {seed}: нет RESULT; rc={proc.returncode}; stderr={proc.stderr[-600:]}"

    assert {seed: bytes.fromhex(h) == src for seed, h in results.items() if h is not None} == dict.fromkeys(
        range(4), True
    )
