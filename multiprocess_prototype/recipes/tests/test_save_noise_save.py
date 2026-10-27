# -*- coding: utf-8 -*-
"""Приёмка Task 1.2 (C-30): Save из Recipes / Pipeline идёт через канонический before/after без шума.

Матрица ``plans/2026-10-26_recipe-save-noise/design.md`` §6 — строки «Recipes «Сохранить»»,
«Pipeline «Сохранить»» (обе жёсткие, на байтах) и «топология не парсится».

Цепочка настоящая: ``save_editor_topology_to_recipe`` / ``PipelinePresenter.save_to_active_recipe`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` -> файл в ``tmp_path`` (движок ``FakeEngine``,
как в ``adapters/tests/test_recipe_store.py``). Реальные рецепты только копируются.

Фикстура A — ``fixtures/letter_robot_sim_pre_c30.yaml`` (LF-копия строится тестом).
Фикстура B — литерал ``_B_RECIPE``: рецепт без ``blueprint.metadata``, два процесса, один провод.

Сигнатуры из ACCEPTANCE: ``save_editor_topology_to_recipe(recipes, slug, topology, *, gui_positions=None,
locked_nodes=None, expected_rev=None) -> str``; ``RecipeConflict`` из ``multiprocess_framework.modules.recipe``;
``RecipeStoreFromManager.read_raw_with_rev(slug)[1]`` — ревизия. Новый API берётся внутри тела теста.
"""

from __future__ import annotations

import difflib
import inspect
import os
import re
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

_HERE = Path(__file__).resolve().parent
_FIXTURE_A = _HERE / "fixtures" / "letter_robot_sim_pre_c30.yaml"
_SLUG = "letter_robot_sim"
_OLD_MTIME_NS = 1_700_000_000_000_000_000

# Строка ``protected: false`` процесса camera_0 в LF-копии фикстуры A (1-based).
_CAMERA_0_PROTECTED_LINE = 154

_B_RECIPE = (
    "name: b_recipe\n"
    "version: 3\n"
    "description: ''\n"
    "blueprint:\n"
    "  name: default\n"
    "  description: ''\n"
    "  processes:\n"
    "    - process_name: camera\n"
    "      plugins:\n"
    "        - plugin_name: capture\n"
    "    - process_name: processor\n"
    "      plugins:\n"
    "        - plugin_name: color_mask\n"
    "  wires:\n"
    "    - source: camera.capture.frame\n"
    "      target: processor.color_mask.frame\n"
    "  displays: []\n"
    "created_at: ''\n"
    "active_services: []\n"
    "display_bindings: []\n"
).encode("utf-8")


# ---------------------------------------------------------------------------
# Обвязка
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


def _fixture_a_lf() -> bytes:
    return _FIXTURE_A.read_bytes().replace(b"\r\n", b"\n")


def _put(directory: Path, slug: str, data: bytes) -> Path:
    path = directory / f"{slug}.yaml"
    path.write_bytes(data)
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    return path


def _build_store(recipes_dir: Path, slug: str, *, yaml_patcher: Any = None) -> tuple[Any, bool]:
    """Настоящие RecipeManager + RecipeStoreFromManager; вернуть (стор, принят ли yaml_patcher)."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager

    engine = FakeEngine(recipes_dir)
    engine.set_active(slug)
    params = inspect.signature(RecipeManager.__init__).parameters
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    # format_hook добавляет Task 1.1e; без параметра тест обязан краснеть (TypeError), а не идти без хука.
    kwargs: dict[str, Any] = {"format_hook": InspectorRecipeFormatHook()}
    patcher_accepted = "yaml_patcher" in params
    if yaml_patcher is not None and patcher_accepted:
        kwargs["yaml_patcher"] = yaml_patcher
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, **kwargs)
    return RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir), patcher_accepted


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


def _diff(before: bytes, after: bytes) -> list[str]:
    """Строки диффа ('-...'/'+...') без заголовков и @@ (LF)."""
    a = before.decode("utf-8").split("\n")
    b = after.decode("utf-8").split("\n")
    out = list(difflib.unified_diff(a, b, lineterm="", n=0))[2:]
    return [line for line in out if not line.startswith("@@")]


def _topology_of_a() -> dict:
    """Топология фикстуры A так, как её отдаёт редактор: ``Topology.from_dict(A.blueprint).to_dict()``."""
    from multiprocess_prototype.domain.entities import Topology

    blueprint = yaml.safe_load(_fixture_a_lf().decode("utf-8"))["blueprint"]
    return Topology.from_dict(blueprint).to_dict()


def _save(store: Any, slug: str, topology: dict, **kwargs: Any) -> Any:
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    return _within(60, save_editor_topology_to_recipe, store, slug, topology, **kwargs)


# ---------------------------------------------------------------------------
# Recipes «Сохранить»
# ---------------------------------------------------------------------------


def test_recipes_save_no_edit_is_byte_identical(tmp_path: Path) -> None:
    """Save топологии A без правок: байты и st_mtime_ns прежние."""
    path = _put(tmp_path, _SLUG, _fixture_a_lf())
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    store, _ = _build_store(tmp_path, _SLUG)

    _save(store, _SLUG, _topology_of_a())

    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


def test_recipes_save_protected_diff_literal(tmp_path: Path) -> None:
    """Save с protected=True у camera_0: дифф ровно ``protected: false`` -> ``protected: true`` в строке camera_0."""
    src = _fixture_a_lf()
    lines = src.split(b"\n")
    assert lines[_CAMERA_0_PROTECTED_LINE - 1] == b"      protected: false"
    expected = b"\n".join(
        [*lines[: _CAMERA_0_PROTECTED_LINE - 1], b"      protected: true", *lines[_CAMERA_0_PROTECTED_LINE:]]
    )
    path = _put(tmp_path, _SLUG, src)
    store, _ = _build_store(tmp_path, _SLUG)
    topology = _topology_of_a()
    camera = next(p for p in topology["processes"] if p["process_name"] == "camera_0")
    assert camera["protected"] is False
    camera["protected"] = True

    _save(store, _SLUG, topology)

    after = path.read_bytes()
    assert _diff(src, after) == ["-      protected: false", "+      protected: true"]
    assert after == expected


# ---------------------------------------------------------------------------
# Pipeline «Сохранить»
# ---------------------------------------------------------------------------


def _silence_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **kw: None))


def _pipeline_presenter(store: Any, blueprint: dict) -> Any:
    """PipelinePresenter на настоящем сторе; модель и раскладка загружены из ``blueprint`` (F8)."""
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests._helpers import make_pipeline_services

    services = make_pipeline_services(topology=blueprint)
    object.__setattr__(services, "recipes", store)
    presenter = PipelinePresenter(services)
    presenter._layout.load_topology_from_config()
    return presenter


def test_pipeline_save_no_edit_is_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pipeline Save фикстуры A без правок (модель из файла, раскладка из load_topology_from_config): байты прежние."""
    _silence_message_boxes(monkeypatch)
    path = _put(tmp_path, _SLUG, _fixture_a_lf())
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    store, _ = _build_store(tmp_path, _SLUG)
    blueprint = yaml.safe_load(raw_before.decode("utf-8"))["blueprint"]
    presenter = _pipeline_presenter(store, blueprint)

    ok = _within(60, presenter.save_to_active_recipe, None)

    assert ok is True
    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


_ADDED_LINE = re.compile(
    r"^\+\s*("
    r"metadata:"
    r"|gui_positions:( \{\})?"
    r"|(camera|processor)(\.[A-Za-z_]+)?:( \[.*\])?"
    r"|- -?[0-9]+(\.[0-9]+)?"
    r")$"
)


def test_pipeline_save_without_metadata_adds_positions_not_empty_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline Save на B без metadata: нет удалений и ``locked_nodes``; добавлены лишь metadata/позиции; один patch."""
    _silence_message_boxes(monkeypatch)
    from multiprocess_framework.modules.recipe import yaml_io

    real_patch = getattr(yaml_io, "patch_yaml_preserving", None)
    calls: list[tuple] = []

    def spy(path: Any, before: dict, after: dict) -> bool:
        calls.append((str(path),))
        assert real_patch is not None
        return real_patch(path, before, after)

    path = _put(tmp_path, "b_recipe", _B_RECIPE)
    store, patcher_accepted = _build_store(tmp_path, "b_recipe", yaml_patcher=spy if real_patch else None)
    blueprint = yaml.safe_load(_B_RECIPE.decode("utf-8"))["blueprint"]
    presenter = _pipeline_presenter(store, blueprint)

    ok = _within(60, presenter.save_to_active_recipe, None)

    after = path.read_bytes()
    diff = _diff(_B_RECIPE, after)
    assert ok is True
    assert [line for line in diff if line.startswith("-")] == []
    assert b"locked_nodes" not in after
    assert [line for line in diff if line.startswith("+") and not _ADDED_LINE.match(line)] == []
    assert real_patch is not None, "yaml_io.patch_yaml_preserving ещё не существует"
    assert patcher_accepted, "RecipeManager не принимает yaml_patcher"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Ошибки валидации
# ---------------------------------------------------------------------------

_MARKER = "S3CR3T-MARKER-7f3a9c"


def _unparseable_topology() -> dict:
    """Топология, которую Topology не разбирает: у процесса нет обязательного process_name."""
    return {
        "processes": [{"plugins": [{"plugin_name": "capture", "config": {"password": _MARKER}}]}],
        "wires": [],
        "displays": [],
    }


def test_save_rejects_unparseable_blueprint(tmp_path: Path) -> None:
    """Топология не парсится Topology: RecipeValidationError, байты и st_mtime_ns файла прежние."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    path = _put(tmp_path, _SLUG, _fixture_a_lf())
    raw_before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns
    store, _ = _build_store(tmp_path, _SLUG)

    with pytest.raises(RecipeValidationError):
        _save(store, _SLUG, _unparseable_topology())

    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


def test_validation_error_message_has_no_input_values(tmp_path: Path) -> None:
    """Значение-маркер из config входного dict не попадает в str(RecipeValidationError)."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    _put(tmp_path, _SLUG, _fixture_a_lf())
    store, _ = _build_store(tmp_path, _SLUG)

    with pytest.raises(RecipeValidationError) as info:
        _save(store, _SLUG, _unparseable_topology())

    assert _MARKER not in str(info.value)


# ---------------------------------------------------------------------------
# Устаревшая ревизия
# ---------------------------------------------------------------------------


def test_save_editor_topology_stale_rev_conflict_no_write(tmp_path: Path) -> None:
    """Файл правят руками после чтения ревизии: Save с expected_rev=rev -> RecipeConflict, ручная правка цела."""
    import multiprocess_framework.modules.recipe as recipe_pkg

    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store, _ = _build_store(tmp_path, _SLUG)
    rev = store.read_raw_with_rev(_SLUG)[1]
    hand_edited = src.replace(b"      port: 5021\n", b"      port: 5099\n")
    assert hand_edited != src
    path.write_bytes(hand_edited)
    topology = _topology_of_a()
    next(p for p in topology["processes"] if p["process_name"] == "camera_0")["protected"] = True

    with pytest.raises(recipe_pkg.RecipeConflict):
        _save(store, _SLUG, topology, expected_rev=rev)

    assert path.read_bytes() == hand_edited
