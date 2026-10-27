# -*- coding: utf-8 -*-
"""Приёмка Task 1.8 (C-30): базовый ``rev`` редактора и сообщение о конфликте при Save.

Редактор помнит ``rev`` рецепта, на котором строилась его правка (``TopologySession``: база со старта или с
активации). Файл правят руками -> Save/автосохранение раскладки не затирают ручную правку и не молчат:
Save показывает «Рецепт изменён снаружи — перезагрузите его», автосохранение пишет предупреждение в лог.

Цепочка настоящая (паттерн ``recipes/tests/test_save_noise_save.py``): ``PipelinePresenter`` /
``RecipesPresenter`` -> ``RecipeStoreFromManager`` -> ``RecipeManager`` + ``InspectorRecipeFormatHook`` -> файл
в ``tmp_path``. Настоящий стор нужен намеренно: ``FakeRecipeStore`` молча принимает ``expected_rev=None``.
Реальные рецепты только копируются. Ожидаемые значения — литералы (байты файла, текст сообщения).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

_FIXTURE_A = Path(__file__).resolve().parents[5] / "recipes" / "tests" / "fixtures" / "letter_robot_sim_pre_c30.yaml"
_SLUG = "letter_robot_sim"
_OLD_MTIME_NS = 1_700_000_000_000_000_000
_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"

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
    """Минимальный движок рецептов: ``recipes_dir`` + активный slug."""

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


def _build_store(recipes_dir: Path, slug: str) -> Any:
    """Настоящие RecipeManager + RecipeStoreFromManager с хуком формата Inspector."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook

    engine = FakeEngine(recipes_dir)
    engine.set_active(slug)
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, format_hook=InspectorRecipeFormatHook())
    return RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)


def _within(seconds: float, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший лок/запись даёт явный fail."""
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


def _hand_edited(src: bytes) -> bytes:
    """Рецепт после правки руками: порт 5021 -> 5099 (одна строка)."""
    edited = src.replace(b"      port: 5021\n", b"      port: 5099\n")
    assert edited != src
    return edited


def _topology_of_a() -> dict:
    """Топология фикстуры A так, как её отдаёт редактор."""
    from multiprocess_prototype.domain.entities import Topology

    blueprint = yaml.safe_load(_fixture_a_lf().decode("utf-8"))["blueprint"]
    return Topology.from_dict(blueprint).to_dict()


def _set_protected(topology: dict, value: bool) -> dict:
    next(p for p in topology["processes"] if p["process_name"] == "camera_0")["protected"] = value
    return topology


class _Repo:
    """Источник топологии для Recipes-Save: ``load() -> Topology`` (контракт TopologyRepository)."""

    def __init__(self, topology: dict) -> None:
        self.topology = topology

    def load(self) -> Any:
        from multiprocess_prototype.domain.entities import Topology

        return Topology.from_dict(self.topology)


@pytest.fixture()
def boxes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """QMessageBox подменён: список (вид окна, текст)."""
    from PySide6.QtWidgets import QMessageBox

    shown: list[tuple[str, str]] = []

    def make(kind: str) -> Any:
        def fake(parent: Any, title: str, text: str, *args: Any, **kwargs: Any) -> None:
            shown.append((kind, text))

        return staticmethod(fake)

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, make(kind))
    return shown


def _session_with_base(store: Any, slug: str) -> Any:
    """Сессия с базой «как после активации»: rev текущего чтения стора."""
    from multiprocess_prototype.domain import TopologySession

    session = TopologySession()
    session.capture_base(slug, store.read_raw_with_rev(slug)[1])
    return session


def _pipeline_presenter(store: Any, session: Any) -> Any:
    """PipelinePresenter на настоящем сторе и сессии; модель и раскладка загружены из файла A."""
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests._helpers import make_pipeline_services

    blueprint = yaml.safe_load(_fixture_a_lf().decode("utf-8"))["blueprint"]
    services = make_pipeline_services(topology=blueprint)
    object.__setattr__(services, "recipes", store)
    presenter = PipelinePresenter(services, topology_session=session)
    presenter._layout.load_topology_from_config()
    return presenter


def _recipes_presenter(store: Any, repo: _Repo, session: Any) -> tuple[Any, MagicMock]:
    from multiprocess_prototype.frontend.widgets.tabs.recipes.presenter import RecipesPresenter
    from multiprocess_prototype.frontend.widgets.tabs.recipes.view import IRecipesView

    view = MagicMock(spec=IRecipesView)
    return RecipesPresenter(store=store, view=view, topology_store=repo, topology_session=session), view


# ---------------------------------------------------------------------------
# 1. База со старта (без события активации)
# ---------------------------------------------------------------------------


def test_startup_loaded_recipe_hand_edit_conflict(tmp_path: Path, boxes: list[tuple[str, str]]) -> None:
    """Рецепт загружен на старте (нет RecipeActivated), файл правят руками, Save -> конфликт, байты целы."""
    from multiprocess_prototype.domain import TopologySession
    from multiprocess_prototype.frontend.app import _capture_boot_base, _read_boot_recipe

    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    # Тот же путь, что app.py на старте: одно чтение байтов -> (topology, rev) -> база сессии.
    _topology, boot_rev = _read_boot_recipe(path)
    session = TopologySession()
    _capture_boot_base(session, path, tmp_path, boot_rev)
    store = _build_store(tmp_path, _SLUG)
    presenter = _pipeline_presenter(store, session)
    session.mark_edited()
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)

    ok = _within(60, presenter.save_to_active_recipe, None)

    assert ok is False
    assert path.read_bytes() == hand_edited
    assert session.dirty is True


# ---------------------------------------------------------------------------
# 2-3. Pipeline «Сохранить» после ручной правки
# ---------------------------------------------------------------------------


def test_pipeline_save_after_hand_edit_conflict_bytes_intact(tmp_path: Path, boxes: list[tuple[str, str]]) -> None:
    """База с активации, файл правят руками, Pipeline Save: файл остаётся ручным, сессия не «сохранена»."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    session.mark_edited()
    presenter = _pipeline_presenter(store, session)
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)

    ok = _within(60, presenter.save_to_active_recipe, None)

    assert ok is False
    assert path.read_bytes() == hand_edited
    assert session.dirty is True


def test_pipeline_save_after_hand_edit_shows_reload_message(tmp_path: Path, boxes: list[tuple[str, str]]) -> None:
    """Конфликт при Pipeline Save: одно окно с текстом «перезагрузите его», окна «сохранён» нет."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    path.write_bytes(_hand_edited(src))

    _within(60, presenter.save_to_active_recipe, None)

    assert boxes == [("critical", _CONFLICT_TEXT)]


# ---------------------------------------------------------------------------
# 4. Recipes «Сохранить» после ручной правки
# ---------------------------------------------------------------------------


def test_recipes_save_after_hand_edit_conflict_bytes_intact(tmp_path: Path) -> None:
    """База с активации, файл правят руками, Recipes Save: ручная правка цела, пользователю — текст конфликта."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    session.mark_edited()
    presenter, view = _recipes_presenter(store, _Repo(_set_protected(_topology_of_a(), True)), session)
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)

    ok = _within(60, presenter.on_save, _SLUG)

    assert ok is False
    assert path.read_bytes() == hand_edited
    assert session.dirty is True
    view.show_error.assert_called_once_with(_CONFLICT_TEXT)


# ---------------------------------------------------------------------------
# 5. Автосохранение раскладки после ручной правки
# ---------------------------------------------------------------------------


def test_layout_autosave_after_hand_edit_no_write(
    tmp_path: Path, boxes: list[tuple[str, str]], caplog: pytest.LogCaptureFixture
) -> None:
    """Файл правят руками, срабатывает автосохранение раскладки: файл не тронут, окна нет, в логе — предупреждение."""
    src = _fixture_a_lf()
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    presenter = _pipeline_presenter(store, session)
    # Позиция заведомо отличается от записанной в файле: без базового rev запись бы прошла.
    presenter._layout.gui_positions["camera_0"] = (987.0, 654.0)
    hand_edited = _hand_edited(src)
    path.write_bytes(hand_edited)

    with caplog.at_level(logging.WARNING):
        _within(60, presenter._layout._persist_layout_to_recipe)

    assert path.read_bytes() == hand_edited
    assert boxes == []
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [_CONFLICT_TEXT]


# ---------------------------------------------------------------------------
# 6. Повторный Save идёт на ревизии, которую вернула прошлая запись
# ---------------------------------------------------------------------------


def test_save_then_save_again_uses_returned_rev(tmp_path: Path) -> None:
    """Два Recipes Save подряд без внешних правок: оба проходят, второй возвращает файл к исходным байтам."""
    src = _fixture_a_lf()
    lines = src.split(b"\n")
    assert lines[_CAMERA_0_PROTECTED_LINE - 1] == b"      protected: false"
    protected_true = b"\n".join(
        [*lines[: _CAMERA_0_PROTECTED_LINE - 1], b"      protected: true", *lines[_CAMERA_0_PROTECTED_LINE:]]
    )
    path = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    repo = _Repo(_set_protected(_topology_of_a(), True))
    presenter, view = _recipes_presenter(store, repo, session)

    first = _within(60, presenter.on_save, _SLUG)
    after_first = path.read_bytes()
    repo.topology = _set_protected(_topology_of_a(), False)
    second = _within(60, presenter.on_save, _SLUG)

    assert first is True
    assert after_first == protected_true
    assert second is True
    assert path.read_bytes() == src
    view.show_error.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Save в другой рецепт: своя ревизия чтения, база редактора не трогается
# ---------------------------------------------------------------------------


def test_recipes_save_into_other_slug_uses_own_read_rev(tmp_path: Path) -> None:
    """База — рецепт A; Recipes Save в рецепт B (другие байты): запись проходит, база A прежняя."""
    _put(tmp_path, _SLUG, _fixture_a_lf())
    other = _put(tmp_path, "b_recipe", _B_RECIPE)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    base_before = session.base_rev_for(_SLUG)
    session.mark_edited()
    presenter, view = _recipes_presenter(store, _Repo(_topology_of_a()), session)

    ok = _within(60, presenter.on_save, "b_recipe")

    assert ok is True
    assert b"camera_0" in other.read_bytes()
    assert session.dirty is False
    assert session.base_rev_for(_SLUG) == base_before
    view.show_error.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Создание нового рецепта идёт без базового rev
# ---------------------------------------------------------------------------


def test_on_create_new_recipe_without_base_rev(tmp_path: Path) -> None:
    """При базе на A создание нового рецепта проходит (файла не было), база A и файл A не тронуты."""
    src = _fixture_a_lf()
    path_a = _put(tmp_path, _SLUG, src)
    store = _build_store(tmp_path, _SLUG)
    session = _session_with_base(store, _SLUG)
    base_before = session.base_rev_for(_SLUG)
    presenter, view = _recipes_presenter(store, _Repo(_topology_of_a()), session)

    _within(60, presenter.on_create, "fresh_recipe", "создан тестом")

    created = tmp_path / "fresh_recipe.yaml"
    assert created.exists()
    assert yaml.safe_load(created.read_bytes().decode("utf-8"))["name"] == "fresh_recipe"
    assert path_a.read_bytes() == src
    assert session.base_rev_for(_SLUG) == base_before
    view.show_error.assert_not_called()
