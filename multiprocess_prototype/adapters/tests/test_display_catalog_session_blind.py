# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.11 (C-30): каталог дисплеев пишет с базой сессии редактора.

``DisplayCatalogFromRecipe(..., session=TopologySession)``: запись в рецепт идёт с
``expected_rev == session.base_rev_for(slug)``, после успеха база сдвигается на новый ``rev``;
конфликт (файл правили снаружи после захвата базы) -> ``ValueError`` с текстом для пользователя,
файл и база не тронуты; база ``None`` -> запись с ``rev`` собственного чтения, базу не трогаем.

Цепочка настоящая (как в ``recipes/tests/test_save_noise_store.py``): каталог -> ``RecipeStoreFromManager``
-> ``RecipeManager`` (+ ``InspectorRecipeFormatHook``) -> tmp-копия фикстуры A. Ожидаемые значения — литералы.
Новый параметр ``session=`` / поле ``AppServicesDeps.topology_session`` берётся в теле теста: пока их нет,
тест красный (``TypeError``), а файл собирается.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_SLUG = "letter_robot_sim"
_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"
_FIXTURE_DISPLAY_IDS = ["main", "recog", "mask", "phone"]
_FIXTURE_BINDINGS = [
    {"node_id": "draw.overlay_draw.frame", "display_id": "main"},
    {"node_id": "recog.ml_inference.frame", "display_id": "recog"},
    {"node_id": "maskview.mask_to_frame.frame", "display_id": "mask"},
    {"node_id": "phone.phone_camera.frame", "display_id": "phone"},
]
_BINDINGS_WITHOUT_PHONE = _FIXTURE_BINDINGS[:3]


# ---------------------------------------------------------------------------
# Обвязка
# ---------------------------------------------------------------------------


def _probe_spec() -> Any:
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

    return DisplaySpec(display_id="probe_disp", display_name="Проба")


def _chain(tmp_path: Path) -> tuple[Any, Path, Any]:
    """tmp-копия фикстуры A + настоящий стор + сессия с захваченной базой файла."""
    from multiprocess_prototype.domain.topology_session import TopologySession
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain, fixture_a_lf

    path = _put(tmp_path, _SLUG, fixture_a_lf())
    store = build_chain(tmp_path, _SLUG)
    session = TopologySession()
    session.capture_base(_SLUG, store.read_raw_with_rev(_SLUG)[1])
    return store, path, session


def _catalog(store: Any, session: Any) -> Any:
    from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe

    return DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: _SLUG, session=session)


def _file_doc(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def _display_ids(path: Path) -> list[str]:
    return [d["id"] for d in _file_doc(path)["displays"]]


def _bindings(path: Path) -> list[dict]:
    return [dict(b) for b in _file_doc(path)["blueprint"]["displays"]]


def _hand_edit(path: Path) -> bytes:
    """Ручная правка файла после захвата базы (порт устройства); вернуть новые байты."""
    before = path.read_bytes()
    edited = before.replace(b"      port: 5021\n", b"      port: 5099\n")
    assert edited != before
    path.write_bytes(edited)
    return edited


def _editor_topology() -> dict:
    """Топология фикстуры A, как её отдаёт редактор, с правкой ``camera_0.priority = "normal"`` (маркер записи)."""
    import yaml

    from multiprocess_prototype.domain.entities import Topology
    from multiprocess_prototype.recipes.tests.test_save_noise_store import fixture_a_lf

    blueprint = yaml.safe_load(fixture_a_lf().decode("utf-8"))["blueprint"]
    topology = Topology.from_dict(blueprint).to_dict()
    next(p for p in topology["processes"] if p["process_name"] == "camera_0")["priority"] = "normal"
    return topology


def _editor_save(store: Any, session: Any) -> str:
    """Save редактора: ``save_editor_topology_to_recipe`` с ``expected_rev = база сессии``."""
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    return _within(
        60,
        save_editor_topology_to_recipe,
        store,
        _SLUG,
        _editor_topology(),
        expected_rev=session.base_rev_for(_SLUG),
    )


def _camera_priority(path: Path) -> Any:
    doc = _file_doc(path)
    return next(p for p in doc["blueprint"]["processes"] if p["process_name"] == "camera_0")["priority"]


# ---------------------------------------------------------------------------
# A. register при захваченной базе
# ---------------------------------------------------------------------------


def test_register_moves_base_to_new_file_rev(tmp_path: Path) -> None:
    """register(probe_disp): база сессии = rev файла после записи, и он не равен прежней базе."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)
    assert base_before is not None

    _within(60, _catalog(store, session).register, _probe_spec())

    file_rev = store.read_raw_with_rev(_SLUG)[1]
    assert file_rev is not None and file_rev != base_before
    assert session.base_rev_for(_SLUG) == file_rev


def test_register_writes_probe_display_and_keeps_bindings(tmp_path: Path) -> None:
    """register(probe_disp): id дисплеев в файле = 4 дисплея фикстуры + probe_disp; привязки blueprint целы."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)

    _within(60, _catalog(store, session).register, _probe_spec())

    assert _display_ids(path) == ["main", "recog", "mask", "phone", "probe_disp"]
    assert _bindings(path) == _FIXTURE_BINDINGS


def test_register_then_editor_save_no_false_conflict(tmp_path: Path) -> None:
    """register(probe_disp) -> Save редактора с прежней моделью и базой сессии проходит; дисплей на месте."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    _within(60, _catalog(store, session).register, _probe_spec())

    _editor_save(store, session)

    assert _camera_priority(path) == "normal"
    assert _display_ids(path) == ["main", "recog", "mask", "phone", "probe_disp"]


# ---------------------------------------------------------------------------
# B. register после ручной правки
# ---------------------------------------------------------------------------


def test_register_after_hand_edit_raises_user_text(tmp_path: Path) -> None:
    """База захвачена -> файл правят руками -> register: ValueError ровно с текстом для пользователя."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    _hand_edit(path)

    with pytest.raises(ValueError) as info:
        _within(60, _catalog(store, session).register, _probe_spec())

    assert str(info.value) == _CONFLICT_TEXT


def test_register_after_hand_edit_bytes_and_base_intact(tmp_path: Path) -> None:
    """Конфликт register: байты файла = ручная правка, база сессии прежняя."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)
    edited = _hand_edit(path)

    with pytest.raises(ValueError):
        _within(60, _catalog(store, session).register, _probe_spec())

    assert path.read_bytes() == edited
    assert session.base_rev_for(_SLUG) == base_before


# ---------------------------------------------------------------------------
# C. update (enabled=False)
# ---------------------------------------------------------------------------


def test_update_disabled_writes_file_keeps_bindings_moves_base(tmp_path: Path) -> None:
    """update(main, enabled=False): enabled false только у main, привязки целы, база = rev файла."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)
    catalog = _catalog(store, session)
    spec = catalog.resolve("main")
    assert spec is not None and spec.enabled is True

    assert _within(60, catalog.update, dataclasses.replace(spec, enabled=False)) is True

    enabled = {d["id"]: d["enabled"] for d in _file_doc(path)["displays"]}
    assert enabled == {"main": False, "recog": True, "mask": True, "phone": False}
    assert _bindings(path) == _FIXTURE_BINDINGS
    file_rev = store.read_raw_with_rev(_SLUG)[1]
    assert file_rev != base_before
    assert session.base_rev_for(_SLUG) == file_rev


def test_update_then_editor_save_no_false_conflict(tmp_path: Path) -> None:
    """update(main, enabled=False) -> Save редактора с базой сессии проходит; enabled: false остался."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    catalog = _catalog(store, session)
    _within(60, catalog.update, dataclasses.replace(catalog.resolve("main"), enabled=False))

    _editor_save(store, session)

    assert _camera_priority(path) == "normal"
    assert {d["id"]: d["enabled"] for d in _file_doc(path)["displays"]}["main"] is False


# ---------------------------------------------------------------------------
# D. update после ручной правки
# ---------------------------------------------------------------------------


def test_update_after_hand_edit_raises_and_bytes_intact(tmp_path: Path) -> None:
    """База захвачена -> ручная правка -> update: ValueError с текстом, байты правки и база целы."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)
    catalog = _catalog(store, session)
    spec = catalog.resolve("main")
    edited = _hand_edit(path)

    with pytest.raises(ValueError) as info:
        _within(60, catalog.update, dataclasses.replace(spec, enabled=False))

    assert str(info.value) == _CONFLICT_TEXT
    assert path.read_bytes() == edited
    assert session.base_rev_for(_SLUG) == base_before


# ---------------------------------------------------------------------------
# E. база сброшена
# ---------------------------------------------------------------------------


def test_register_with_reset_base_writes_and_keeps_base_none(tmp_path: Path) -> None:
    """capture_base(slug, None): register проходит с rev собственного чтения, база остаётся None."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    session.capture_base(_SLUG, None)

    _within(60, _catalog(store, session).register, _probe_spec())

    assert _display_ids(path) == ["main", "recog", "mask", "phone", "probe_disp"]
    assert session.base_rev_for(_SLUG) is None


# ---------------------------------------------------------------------------
# F. unregister без привязки
# ---------------------------------------------------------------------------


def test_unregister_unbound_removes_display_and_moves_base(tmp_path: Path) -> None:
    """register -> unregister probe_disp: дисплея нет в файле, база = rev файла (сдвинута с rev после register)."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    catalog = _catalog(store, session)
    _within(60, catalog.register, _probe_spec())
    base_after_register = session.base_rev_for(_SLUG)

    assert _within(60, catalog.unregister, "probe_disp") is True

    assert _display_ids(path) == ["main", "recog", "mask", "phone"]
    assert _bindings(path) == _FIXTURE_BINDINGS
    file_rev = store.read_raw_with_rev(_SLUG)[1]
    assert file_rev != base_after_register
    assert session.base_rev_for(_SLUG) == file_rev


def test_unregister_unbound_then_editor_save_no_false_conflict(tmp_path: Path) -> None:
    """register probe_disp и probe_two -> unregister probe_disp -> Save редактора с базой сессии проходит.

    Второй дисплей нужен, чтобы итоговые байты файла не совпали с исходными: rev — хеш содержимого,
    пара register/unregister одного дисплея возвращает исходный rev, и тест без сдвига базы не краснел бы.
    """
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    catalog = _catalog(store, session)
    _within(60, catalog.register, _probe_spec())
    _within(60, catalog.register, DisplaySpec(display_id="probe_two", display_name="Проба 2"))
    _within(60, catalog.unregister, "probe_disp")

    _editor_save(store, session)

    assert _camera_priority(path) == "normal"
    assert _display_ids(path) == ["main", "recog", "mask", "phone", "probe_two"]


# ---------------------------------------------------------------------------
# G. unregister дисплея с привязкой
# ---------------------------------------------------------------------------


def test_unregister_bound_file_valid_binding_removed_base_not_moved(tmp_path: Path) -> None:
    """unregister(phone): файл читается, привязка phone снята, дисплея нет; база осталась прежней."""
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    base_before = session.base_rev_for(_SLUG)

    _within(60, _catalog(store, session).unregister, "phone")

    assert store.read(_SLUG) is not None
    assert _bindings(path) == _BINDINGS_WITHOUT_PHONE
    assert _display_ids(path) == ["main", "recog", "mask"]
    assert session.base_rev_for(_SLUG) == base_before


def test_unregister_bound_then_editor_save_rejected_binding_not_restored(tmp_path: Path) -> None:
    """unregister(phone) -> Save редактора со старой моделью отказан, привязка phone в файле не вернулась.

    Отказ — RecipeConflict (база устарела) либо RecipeValidationError (1.13: привязка к дисплею без определения
    проверяется раньше записи); правка лида после 1.13, тестер ожидал только RecipeConflict.
    """
    from multiprocess_framework.modules.recipe import RecipeConflict
    from multiprocess_prototype.recipes.save import RecipeValidationError
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    _within(60, _catalog(store, session).unregister, "phone")

    with pytest.raises((RecipeConflict, RecipeValidationError)):
        _editor_save(store, session)

    assert _bindings(path) == _BINDINGS_WITHOUT_PHONE
    assert _camera_priority(path) == "high"


# ---------------------------------------------------------------------------
# I. настоящий build_app_services
# ---------------------------------------------------------------------------


def test_build_app_services_register_moves_session_base(tmp_path: Path) -> None:
    """deps.topology_session -> app_services.displays.register двигает базу этой сессии на rev файла."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook
    from multiprocess_prototype.domain.tests._fakes import FakeEventBus
    from multiprocess_prototype.domain.topology_session import TopologySession
    from multiprocess_prototype.frontend.app_services_factory import AppServicesDeps, build_app_services
    from multiprocess_prototype.recipes.tests.test_save_noise_store import FakeEngine, _put, _within, fixture_a_lf

    path = _put(tmp_path, _SLUG, fixture_a_lf())
    engine = FakeEngine(tmp_path)
    engine.set_active(_SLUG)
    manager = RecipeManager(engine=engine, state_proxy=None, logger=None, format_hook=InspectorRecipeFormatHook())

    event_bus = FakeEventBus()
    registry = MagicMock()
    registry.list.return_value = []
    registry.get.return_value = None
    registers = MagicMock()
    registers.get_fields.return_value = []
    registers.get_register.return_value = None
    auth_state = MagicMock()
    auth_state.is_authenticated = False
    session = TopologySession()

    deps = AppServicesDeps(
        event_bus=event_bus,
        topology_store=TopologyRepositoryStore({"processes": [], "wires": [], "displays": []}, events=event_bus),
        plugin_registry=registry,
        display_registry=registry,
        service_registry=registry,
        registers_manager=registers,
        config={},
        recipe_manager=manager,
        auth_state=auth_state,
        topology_session=session,
    )
    app_services = build_app_services(deps)
    session.capture_base(_SLUG, app_services.recipes.read_raw_with_rev(_SLUG)[1])
    base_before = session.base_rev_for(_SLUG)
    assert base_before is not None

    _within(60, app_services.displays.register, _probe_spec())

    file_rev = app_services.recipes.read_raw_with_rev(_SLUG)[1]
    assert file_rev != base_before
    assert session.base_rev_for(_SLUG) == file_rev
    assert _display_ids(path) == ["main", "recog", "mask", "phone", "probe_disp"]
