# -*- coding: utf-8 -*-
"""Приёмка Task 1.14 (C-30, стадия 1): Save владеет только непротектед-процессами.

Правило: процессы файла с ``protected: true`` (и процессы файла, чьё имя совпадает с protected-процессом
редактора) остаются в файле такими же и на своих местах; protected-процессы редактора, которых в файле нет,
в файл не пишутся; порядок protected относительно непротектед не меняется от вставки/удаления непротектед.

Сессионная топология строится как в ``backend.launch.merge_topologies``: protected-процесс фундамента
``devices`` (форма отличается от файловой) идёт ПЕРВЫМ, затем процессы файла без файлового ``devices``.

Цепочка настоящая (как в ``test_save_noise_save.py``): ``save_editor_topology_to_recipe`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` + ``InspectorRecipeFormatHook`` -> файл в ``tmp_path``.
Фикстура A — ``fixtures/letter_robot_sim_pre_c30.yaml`` (LF-копия). Ожидаемые значения — литералы
(номера строк фикстуры закреплены якорями ``_anchor``), из тестируемого кода ничего не вычисляется.

Фикстура A (1-based): ``devices`` — строки 117..132 (16), ``camera_0`` — 133..161 (29), ``vision`` — с 162;
``protected: true`` внутри devices — строка 130; провод ``camera_0.camera_service.frame -> vision`` —
строки 428..430; определение дисплея ``phone`` — последний блок top-level ``displays`` перед ``created_at``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype.recipes.tests.test_save_noise_store import (
    _diff,
    _put,
    _within,
    build_chain,
    fixture_a_lf,
)

_SLUG = "letter_robot_sim"

# Порядок процессов в фикстуре A (литерал).
_A_ORDER = ["gui", "devices", "camera_0", "vision", "line", "recog", "layout", "draw", "maskview", "phone"]

_DEVICES_FIRST, _DEVICES_LAST = 117, 132  # 1-based включительно
_CAMERA_FIRST, _CAMERA_LAST = 133, 161
_DEVICES_PROTECTED_LINE = 130
_WIRE_FIRST, _WIRE_LAST = 428, 430

_PROBE = {"process_name": "probe_proc", "plugins": [], "protected": False}


# ---------------------------------------------------------------------------
# Обвязка
# ---------------------------------------------------------------------------


def _anchor(lines: list[bytes], number: int, prefix: bytes) -> None:
    """Страховка: строка ``number`` (1-based) фикстуры начинается с ``prefix`` (фикстура не уехала)."""
    assert lines[number - 1].startswith(prefix), (number, lines[number - 1])


def _lines(src: bytes) -> list[bytes]:
    return src.split(b"\n")


def _a_checked() -> tuple[bytes, list[bytes]]:
    src = fixture_a_lf()
    lines = _lines(src)
    _anchor(lines, _DEVICES_FIRST, b"    - process_name: devices")
    _anchor(lines, _CAMERA_FIRST, b"    - process_name: camera_0")
    _anchor(lines, _CAMERA_LAST + 1, b"    - process_name: vision")
    _anchor(lines, _DEVICES_PROTECTED_LINE, b"      protected: true")
    _anchor(lines, _WIRE_FIRST, b"    - source: camera_0.camera_service.frame")
    _anchor(lines, _WIRE_LAST + 1, b"    - source: vision.circle_detector.frame")
    return src, lines


def _join(lines: list[bytes]) -> bytes:
    return b"\n".join(lines)


def a_without_devices() -> bytes:
    """A с вырезанным блоком devices (строки 117..132)."""
    _, lines = _a_checked()
    return _join([*lines[: _DEVICES_FIRST - 1], *lines[_DEVICES_LAST:]])


def a_devices_after_camera() -> bytes:
    """A, где блок devices стоит ПОСЛЕ camera_0: порядок ``gui, camera_0, devices, vision, ...``."""
    _, lines = _a_checked()
    devices = lines[_DEVICES_FIRST - 1 : _DEVICES_LAST]
    camera = lines[_CAMERA_FIRST - 1 : _CAMERA_LAST]
    return _join([*lines[: _DEVICES_FIRST - 1], *camera, *devices, *lines[_CAMERA_LAST:]])


def a_devices_without_protected_key() -> bytes:
    """A, где у файлового devices нет ключа ``protected`` (старый рецепт): строка 130 вырезана."""
    _, lines = _a_checked()
    return _join([*lines[: _DEVICES_PROTECTED_LINE - 1], *lines[_DEVICES_PROTECTED_LINE:]])


def _foundation_devices() -> dict:
    """Фундаментный devices: protected, форма отличается от файловой (там плагин device_hub и process_class)."""
    return {"process_name": "devices", "protected": True, "plugins": [], "workers": []}


def _blueprint(src: bytes) -> dict:
    return yaml.safe_load(src.decode("utf-8"))["blueprint"]


def session_topology(
    src: bytes,
    *,
    foundation: bool = True,
    edit: Callable[[list[dict], list[dict]], None] | None = None,
) -> dict:
    """Топология редактора: [фундаментный devices] + процессы файла БЕЗ файлового devices.

    ``edit(processes, wires)`` правит списки in place (после сборки, фундамент уже первый).
    """
    from multiprocess_prototype.domain.entities import Topology

    blueprint = _blueprint(src)
    processes = [p for p in blueprint["processes"] if p["process_name"] != "devices"]
    if foundation:
        processes.insert(0, _foundation_devices())
    wires = list(blueprint.get("wires") or [])
    if edit is not None:
        edit(processes, wires)
    return Topology.from_dict({**blueprint, "processes": processes, "wires": wires}).to_dict()


def _drop_camera_with_wire(processes: list[dict], wires: list[dict]) -> None:
    """Редактор удалил camera_0 вместе с его проводом (иначе провод повис бы на несуществующий процесс)."""
    processes[:] = [p for p in processes if p["process_name"] != "camera_0"]
    wires[:] = [w for w in wires if not w["source"].startswith("camera_0.")]


def _insert_probe_before_camera(processes: list[dict], wires: list[dict]) -> None:
    index = next(i for i, p in enumerate(processes) if p["process_name"] == "camera_0")
    processes.insert(index, dict(_PROBE))


def _append_probe(processes: list[dict], wires: list[dict]) -> None:
    processes.append(dict(_PROBE))


def _file_order(raw: bytes) -> list[str]:
    return [p["process_name"] for p in _blueprint(raw)["processes"]]


def _start(tmp_path: Path, src: bytes) -> tuple[Path, Any, str | None]:
    """Положить файл, собрать настоящую цепочку и взять «rev чтения» (база Save)."""
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    rev = store.read_raw_with_rev(_SLUG)[1]
    assert rev is not None
    return path, store, rev


def _save(store: Any, topology: dict, **kwargs: Any) -> Any:
    from multiprocess_prototype.recipes.save import save_editor_topology_to_recipe

    return _within(
        60, save_editor_topology_to_recipe, store, _SLUG, topology, foundation=frozenset({"devices"}), **kwargs
    )


def _save_no_edit_unchanged(tmp_path: Path, src: bytes, topology: dict) -> None:
    path, store, rev = _start(tmp_path, src)
    mtime_before = path.stat().st_mtime_ns

    _save(store, topology, expected_rev=rev)

    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# A, B, E, J — Save без правок не трогает файл
# ---------------------------------------------------------------------------


def test_save_no_edit_file_without_devices_keeps_bytes_and_mtime(tmp_path: Path) -> None:
    """A: в файле devices нет, в сессии фундаментный devices; Save без правок -> байты и mtime прежние."""
    src = a_without_devices()
    assert b"process_name: devices" not in src
    _save_no_edit_unchanged(tmp_path, src, session_topology(src))


def test_save_no_edit_author_devices_second_keeps_bytes_and_order(tmp_path: Path) -> None:
    """B: авторский devices вторым, в сессии фундаментный первым; Save без правок -> байты и порядок прежние."""
    src, _ = _a_checked()
    path, store, rev = _start(tmp_path, src)
    mtime_before = path.stat().st_mtime_ns

    _save(store, session_topology(src), expected_rev=rev)

    after = path.read_bytes()
    assert _file_order(after) == _A_ORDER
    assert after == src
    assert path.stat().st_mtime_ns == mtime_before


def test_save_no_edit_editor_lacks_protected_process_keeps_file_devices(tmp_path: Path) -> None:
    """E: devices есть в файле, в топологии редактора его нет вовсе; после Save devices на месте, байты прежние."""
    src, _ = _a_checked()
    topology = session_topology(src, foundation=False)
    assert "devices" not in [p["process_name"] for p in topology["processes"]]
    path, store, rev = _start(tmp_path, src)

    _save(store, topology, expected_rev=rev)

    after = path.read_bytes()
    assert _file_order(after) == _A_ORDER
    assert after == src


def test_save_no_edit_legacy_devices_without_protected_key_keeps_bytes(tmp_path: Path) -> None:
    """J: файловый devices без ключа protected, в сессии фундаментный protected; Save без правок -> байты прежние."""
    src = a_devices_without_protected_key()
    block = _blueprint(src)["processes"][1]
    assert block["process_name"] == "devices"
    assert "protected" not in block
    _save_no_edit_unchanged(tmp_path, src, session_topology(src))


# ---------------------------------------------------------------------------
# C, D — вставка и удаление непротектед при devices на втором месте
# ---------------------------------------------------------------------------


def test_save_added_process_is_only_diff_and_foundation_devices_not_written(tmp_path: Path) -> None:
    """C: файла без devices + probe_proc в конец: дифф ровно одна строка `+`; процесса devices в файле нет."""
    src = a_without_devices()
    path, store, rev = _start(tmp_path, src)

    _save(store, session_topology(src, edit=_append_probe), expected_rev=rev)

    after = path.read_bytes()
    assert _diff(src, after) == ["+    - process_name: probe_proc"]
    assert "devices" not in _file_order(after)
    assert _file_order(after) == [n for n in _A_ORDER if n != "devices"] + ["probe_proc"]


def test_save_removed_process_diff_is_only_its_block_lines(tmp_path: Path) -> None:
    """D: devices вторым, редактор удалил camera_0 (с проводом): дифф только `-` (29 строк блока + 3 провода = 32)."""
    src, lines = _a_checked()
    path, store, rev = _start(tmp_path, src)
    expected_after = _join([*lines[: _CAMERA_FIRST - 1], *lines[_CAMERA_LAST : _WIRE_FIRST - 1], *lines[_WIRE_LAST:]])

    _save(store, session_topology(src, edit=_drop_camera_with_wire), expected_rev=rev)

    after = path.read_bytes()
    diff = _diff(src, after)
    assert [line for line in diff if line.startswith("+")] == []
    assert len(diff) == 32
    assert _file_order(after) == [n for n in _A_ORDER if n != "camera_0"]
    assert after == expected_after


# ---------------------------------------------------------------------------
# H, I — devices стоит после camera_0; вставка/удаление перед ним не двигает protected
# ---------------------------------------------------------------------------


def test_save_insert_before_moved_devices_keeps_protected_block_and_position(tmp_path: Path) -> None:
    """H: файл `gui, camera_0, devices, vision`; probe_proc перед camera_0: порядок сохранён, дифф только вставка."""
    src = a_devices_after_camera()
    assert _file_order(src) == ["gui", "camera_0", "devices", *_A_ORDER[3:]]
    devices_block = _join(_lines(src)[_CAMERA_LAST - 1 : _CAMERA_LAST - 1 + (_DEVICES_LAST - _DEVICES_FIRST + 1)])
    path, store, rev = _start(tmp_path, src)

    _save(store, session_topology(src, edit=_insert_probe_before_camera), expected_rev=rev)

    after = path.read_bytes()
    diff = _diff(src, after)
    assert _file_order(after) == ["gui", "probe_proc", "camera_0", "devices", *_A_ORDER[3:]]
    assert diff and all(line.startswith("+") for line in diff)
    assert "+    - process_name: probe_proc" in diff
    assert devices_block in after


def test_save_remove_before_moved_devices_diff_is_only_removed_block(tmp_path: Path) -> None:
    """I: файл `gui, camera_0, devices, vision`; удалён camera_0 (с проводом): дифф только `-`, devices на месте."""
    src = a_devices_after_camera()
    lines = _lines(src)
    # camera_0 теперь на строках 117..145 (29 строк), провод — на прежних 428..430 (перестановка длину не меняет).
    camera_first, camera_last = _DEVICES_FIRST, _DEVICES_FIRST + (_CAMERA_LAST - _CAMERA_FIRST)
    _anchor(lines, camera_first, b"    - process_name: camera_0")
    _anchor(lines, camera_last + 1, b"    - process_name: devices")
    _anchor(lines, _WIRE_FIRST, b"    - source: camera_0.camera_service.frame")
    expected_after = _join([*lines[: camera_first - 1], *lines[camera_last : _WIRE_FIRST - 1], *lines[_WIRE_LAST:]])
    path, store, rev = _start(tmp_path, src)

    _save(store, session_topology(src, edit=_drop_camera_with_wire), expected_rev=rev)

    after = path.read_bytes()
    diff = _diff(src, after)
    assert [line for line in diff if line.startswith("+")] == []
    assert len(diff) == 32
    assert _file_order(after) == ["gui", "devices", *_A_ORDER[3:]]
    assert after == expected_after


# ---------------------------------------------------------------------------
# F, G — ошибки: конфликт ревизии и валидация
# ---------------------------------------------------------------------------


def test_save_stale_rev_with_dangling_binding_raises_conflict_not_validation(tmp_path: Path) -> None:
    """F: определение дисплея phone вынуто руками после взятия rev, привязка осталась: RecipeConflict, записи нет."""
    import multiprocess_framework.modules.recipe as recipe_pkg
    from multiprocess_prototype.recipes.save import RecipeValidationError

    src, _ = _a_checked()
    start = src.rindex(b"  - id: phone\n")
    end = src.index(b"created_at: ''\n")
    hand_edited = src[:start] + src[end:]
    assert b"  - id: phone\n" not in hand_edited
    assert b"      display_id: phone\n" in hand_edited
    path, store, rev = _start(tmp_path, src)
    path.write_bytes(hand_edited)
    calls: list[tuple] = []
    real_save_raw = store.save_raw

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return real_save_raw(*args, **kwargs)

    store.save_raw = spy

    with pytest.raises(recipe_pkg.RecipeConflict) as info:
        _save(store, session_topology(src), expected_rev=rev)

    assert not isinstance(info.value, RecipeValidationError)
    assert path.read_bytes() == hand_edited
    assert calls == []


def test_save_binding_to_unknown_display_without_rev_raises_validation_error(tmp_path: Path) -> None:
    """G: expected_rev=None, привязка узла к display_id "ghost": RecipeValidationError, байты файла целы."""
    from multiprocess_prototype.recipes.save import RecipeValidationError

    src, _ = _a_checked()
    path = _put(tmp_path, _SLUG, src)
    store = build_chain(tmp_path, _SLUG)
    topology = session_topology(src)
    binding = next(b for b in topology["displays"] if b["node_id"] == "draw.overlay_draw.frame")
    assert binding["display_id"] == "main"
    binding["display_id"] = "ghost"

    with pytest.raises(RecipeValidationError):
        _save(store, topology, expected_rev=None)

    assert path.read_bytes() == src
