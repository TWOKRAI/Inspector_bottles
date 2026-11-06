# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.13 (C-30): Save редактора проверяет ссылки привязок на дисплеи.

Save (``save_editor_topology_to_recipe``) пишет результат одной записью. Если в результате есть привязка
``blueprint.displays[].display_id``, которого нет среди id определений top-level ``displays``, рецепт
становится нечитаемым (``store.read`` -> ValidationError «Ссылка на несуществующий display_id»).
Требуемое поведение: Save бросает ``RecipeValidationError`` с этим ``display_id`` в тексте; запись
(``save_raw``) не вызвана; байты файла прежние.

Цепочка настоящая (как в ``test_save_noise_store.py``): стор -> ``RecipeManager`` (+ ``InspectorRecipeFormatHook``)
-> tmp-копия фикстуры A. Шпион считает вызовы ``save_raw`` стора. Ожидаемые значения — литералы.

Сценарии: A (привязка к неопределённому id), B (корректные привязки и Save без правок), C (сценарий ревью:
несохранённая привязка к дисплею, который потом снят через каталог), D (в файле нет секции ``displays``).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

_SLUG = "letter_robot_sim"
_GHOST = "ghost_disp"
_PROBE = "probe_disp"
_BIND_NODE = "draw.overlay_draw.frame"


# ---------------------------------------------------------------------------
# Обвязка
# ---------------------------------------------------------------------------


class _SpyStore:
    """Обёртка над настоящим стором: считает вызовы ``save_raw`` и пробрасывает всё остальное."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.save_calls = 0

    def save_raw(self, *args: Any, **kwargs: Any) -> Any:
        self.save_calls += 1
        return self._inner.save_raw(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _chain(tmp_path: Path, data: bytes | None = None) -> tuple[Any, Path, Any]:
    """tmp-копия фикстуры A (или ``data``) + настоящий стор + сессия с захваченной базой файла."""
    from multiprocess_prototype.domain.topology_session import TopologySession
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain, fixture_a_lf

    path = _put(tmp_path, _SLUG, fixture_a_lf() if data is None else data)
    store = build_chain(tmp_path, _SLUG)
    session = TopologySession()
    session.capture_base(_SLUG, store.read_raw_with_rev(_SLUG)[1])
    return store, path, session


def _fixture_topology() -> dict:
    """Топология фикстуры A, как её отдаёт редактор (4 привязки: main, recog, mask, phone)."""
    import yaml

    from multiprocess_prototype.domain.entities import Topology
    from multiprocess_prototype.recipes.tests.test_save_noise_store import fixture_a_lf

    blueprint = yaml.safe_load(fixture_a_lf().decode("utf-8"))["blueprint"]
    return Topology.from_dict(blueprint).to_dict()


def _with_binding(topology: dict, display_id: str) -> dict:
    """Копия топологии с добавленной привязкой ``draw.overlay_draw.frame`` -> ``display_id``."""
    out = copy.deepcopy(topology)
    out["displays"] = [*out["displays"], {"node_id": _BIND_NODE, "display_id": display_id}]
    return out


def _save(store: Any, topology: dict, expected_rev: str | None) -> str:
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    return _within(60, save_editor_topology_to_recipe, store, _SLUG, topology, expected_rev=expected_rev)


def _error_text(info: pytest.ExceptionInfo) -> str:
    """Текст исключения: ``str`` плюс ``errors`` (если есть)."""
    exc = info.value
    return str(exc) + " | " + "; ".join(getattr(exc, "errors", []) or [])


def _without_top_level_displays(data: bytes) -> bytes:
    """Фикстура A без top-level секции ``displays`` (от ``\\ndisplays:\\n`` до ``\\ncreated_at:``)."""
    head, rest = data.split(b"\ndisplays:\n", 1)
    tail = rest.split(b"\ncreated_at:", 1)[1]
    return head + b"\ncreated_at:" + tail


# ---------------------------------------------------------------------------
# A. привязка к display_id, которого нет среди определений файла
# ---------------------------------------------------------------------------


def test_a_binding_to_undefined_display_raises_with_id(tmp_path: Path) -> None:
    """Топология с привязкой к ``ghost_disp`` (в файле такого определения нет): RecipeValidationError с id."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    store, _path, session = _chain(tmp_path)

    with pytest.raises(RecipeValidationError) as info:
        _save(store, _with_binding(_fixture_topology(), _GHOST), session.base_rev_for(_SLUG))

    assert _GHOST in _error_text(info)


def test_a_binding_to_undefined_display_leaves_bytes_and_skips_write(tmp_path: Path) -> None:
    """Тот же отказ: байты файла прежние, ``save_raw`` не вызывался ни разу."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    store, path, session = _chain(tmp_path)
    spy = _SpyStore(store)
    before = path.read_bytes()

    with pytest.raises(RecipeValidationError):
        _save(spy, _with_binding(_fixture_topology(), _GHOST), session.base_rev_for(_SLUG))

    assert path.read_bytes() == before
    assert spy.save_calls == 0


# ---------------------------------------------------------------------------
# B. корректные привязки и Save без правок — как раньше
# ---------------------------------------------------------------------------


def test_b_save_without_edits_is_byte_identical(tmp_path: Path) -> None:
    """Топология фикстуры A без правок (все 4 display_id определены): Save проходит, байты и mtime прежние."""
    store, path, session = _chain(tmp_path)
    before = path.read_bytes()
    mtime_before = path.stat().st_mtime_ns

    _save(store, _fixture_topology(), session.base_rev_for(_SLUG))

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime_before


def test_b_save_with_defined_display_binding_writes_and_stays_readable(tmp_path: Path) -> None:
    """Правка с корректной привязкой (``draw.overlay_draw.frame`` -> ``phone``, определён): записано и читается."""
    import yaml

    store, path, session = _chain(tmp_path)
    topology = _fixture_topology()
    topology["displays"] = [
        {"node_id": _BIND_NODE, "display_id": "phone"} if b["node_id"] == _BIND_NODE else b
        for b in topology["displays"]
    ]

    _save(store, topology, session.base_rev_for(_SLUG))

    doc = yaml.safe_load(path.read_bytes().decode("utf-8"))
    bound = {b["node_id"]: b["display_id"] for b in doc["blueprint"]["displays"]}
    assert bound[_BIND_NODE] == "phone"
    assert store.read(_SLUG) is not None


# ---------------------------------------------------------------------------
# C. сценарий ревью: register -> несохранённая привязка -> unregister -> Save
# ---------------------------------------------------------------------------


def test_c_review_scenario_unregistered_display_binding_rejected(tmp_path: Path) -> None:
    """register(probe_disp) -> привязка -> unregister (база сдвигается) -> Save: отказ, файл читается, байты прежние."""
    from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
    from multiprocess_prototype.recipes.save import RecipeValidationError
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _within

    store, path, session = _chain(tmp_path)
    spy = _SpyStore(store)
    catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: _SLUG, session=session)
    base_captured = session.base_rev_for(_SLUG)

    _within(60, catalog.register, DisplaySpec(display_id=_PROBE, display_name="Проба"))
    editor_topology = _with_binding(_fixture_topology(), _PROBE)  # несохранённая привязка в модели редактора
    assert _within(60, catalog.unregister, _PROBE) is True
    bytes_after_unregister = path.read_bytes()
    # База сессии = ревизия файла (конфликта ревизий нет, отказ только по ссылке). Запись register+unregister
    # вернула прежние байты, поэтому ревизия может совпасть с захваченной; ``base_captured`` — лишь «база была».
    assert base_captured is not None
    assert session.base_rev_for(_SLUG) == store.read_raw_with_rev(_SLUG)[1]

    with pytest.raises(RecipeValidationError) as info:
        _save(spy, editor_topology, session.base_rev_for(_SLUG))

    assert _PROBE in _error_text(info)
    assert spy.save_calls == 0
    assert path.read_bytes() == bytes_after_unregister
    assert store.read(_SLUG) is not None  # файл читается без ValidationError


# ---------------------------------------------------------------------------
# D. в файле нет top-level displays вовсе
# ---------------------------------------------------------------------------


def test_d_binding_when_file_has_no_displays_section_raises(tmp_path: Path) -> None:
    """Рецепт без top-level ``displays`` + топология с привязкой: RecipeValidationError с display_id; байты прежние."""
    from multiprocess_prototype.recipes.save import RecipeValidationError
    from multiprocess_prototype.recipes.tests.test_save_noise_store import fixture_a_lf

    data = _without_top_level_displays(fixture_a_lf())
    assert b"\ndisplays:\n" not in data and b"\n  displays:\n" in data  # секции нет, blueprint.displays остался
    store, path, _session = _chain(tmp_path, data)
    spy = _SpyStore(store)
    before = path.read_bytes()
    topology = _fixture_topology()  # привязки main/recog/mask/phone, определений в файле нет

    with pytest.raises(RecipeValidationError) as info:
        _save(spy, topology, None)

    assert "main" in _error_text(info)
    assert spy.save_calls == 0
    assert path.read_bytes() == before
