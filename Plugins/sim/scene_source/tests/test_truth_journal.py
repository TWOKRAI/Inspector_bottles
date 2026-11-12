# -*- coding: utf-8 -*-
"""Приёмка вслепую, Task 1.1b (план dataset-sidecar-truth): журнал истины ``scene_source``.

Источник правды — ``plans/2026-11-11_dataset-sidecar-truth/design.md`` §3 и §8; тест не читает ``plugin.py``.
Журнал — JSONL-файл ``truth_<%Y%m%d_%H%M%S>_<pid>.jsonl`` в ``truth_journal_dir``; запись = строка, ``flush()``
после каждой, поэтому тесты читают файл, НЕ останавливая плагин (сброс буфера — часть проверки).

Шов времени — ``plugin._wall`` (``time.time``); тесты подменяют его ПОСЛЕ ``configure()``: заголовок берёт своё
время внутри ``configure()`` и шаг подмены не съедает. Ожидаемые значения — литералы из ТЗ, не пересчёт
из кода под тестом.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import pathlib
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health.state import HealthReporter, HealthState
from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

pytestmark = pytest.mark.timeout(60)

# Геометрия нарочно не дефолтная: журнал, подставивший BeltGeometry() вместо dict из конфига, не пройдёт.
_GEOMETRY: dict[str, float] = {
    "origin_x_mm": 12.5,
    "origin_y_mm": -3.25,
    "frame_down_ux": -1.0,
    "frame_down_uy": 0.0,
}
_PX_PER_MM = 2.0
_CAMERA_ID = 7
_CLASSES: dict[str, tuple[int, int, int]] = {"square": (0, 0, 255), "disc": (0, 255, 0), "ring": (255, 0, 0)}


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` (как в ``test_scene_source_hazards.py``)."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, Any]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: Any) -> None:
        self.set_calls.append((path, value))


def _make_catalog(root: Path) -> Path:
    """Каталог из трёх классов с разными цветами: совпадение ``class_name`` не должно быть тривиальным."""
    classes_dir = root / f"classes_{uuid.uuid4().hex}"
    for name, (b, g, r) in _CLASSES.items():
        class_dir = classes_dir / name
        class_dir.mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, 0], sprite[:, :, 1], sprite[:, :, 2], sprite[:, :, 3] = b, g, r, 255
        imwrite_unicode(class_dir / "sprite.png", sprite)
    return classes_dir


def _config(catalog: Path, journal_dir: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": _PX_PER_MM,
        "stale_ms": 200,
        "camera_id": _CAMERA_ID,
        "geometry": dict(_GEOMETRY),
        "preset_path": str(catalog),
        "spawn_interval_s": [0.01, 0.01],
        "scene_length_mm": 1_000_000.0,
        "truth_journal_dir": journal_dir,
        **(overrides or {}),
    }


def _make_plugin(
    catalog: Path,
    journal_dir: str,
    overrides: dict[str, Any] | None = None,
    health: Any = None,
) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    if health is not None:
        ctx.health = health
    ctx.config = _config(catalog, journal_dir, overrides)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


def _push_encoder(sp: _FakeStateProxy, value: int) -> None:
    """Мир «готов» после одной дельты ``sim.belt.encoder`` (как в соседних тестах)."""
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": value, "mm_s": 0.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )


def _journal_lines(journal_dir: Path) -> list[dict[str, Any]]:
    """Ровно один файл ``truth_*.jsonl``; каждая строка — JSON-объект. Нет файла — AssertionError."""
    files = sorted(journal_dir.glob("truth_*.jsonl"))
    assert len(files) == 1, f"в {journal_dir} ожидался ровно один truth_*.jsonl, найдено: {[f.name for f in files]}"
    text = files[0].read_text(encoding="utf-8")
    lines = [ln for ln in text.split("\n") if ln]
    return [json.loads(ln) for ln in lines]


@pytest.fixture
def journal_dir(tmp_path: Path) -> Path:
    path = tmp_path / "journal"
    path.mkdir()
    return path


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    # Каталог спрайтов — вне каталога журнала.
    root = tmp_path / "catalog_root"
    root.mkdir()
    return _make_catalog(root)


# --------------------------------------------------------------------------- #
# 1. Заголовок                                                                #
# --------------------------------------------------------------------------- #


def test_header_first_line(journal_dir: Path, catalog: Path) -> None:
    """Строка 1 — ``header``: ``schema == 1``, ``geometry`` == dict конфига, ``camera_id``/``px_per_mm`` из конфига."""
    _make_plugin(catalog, str(journal_dir))

    files = list(journal_dir.glob("truth_*.jsonl"))
    assert len(files) == 1, f"configure() обязан создать ровно один файл журнала в {journal_dir}: {files}"
    assert re.fullmatch(rf"truth_\d{{8}}_\d{{6}}_{os.getpid()}\.jsonl", files[0].name), (
        f"имя файла не по шаблону truth_<%Y%m%d_%H%M%S>_<pid>.jsonl: {files[0].name!r}"
    )

    first = _journal_lines(journal_dir)[0]
    assert first["kind"] == "header"
    assert first["schema"] == 1
    assert first["geometry"] == _GEOMETRY
    assert first["camera_id"] == _CAMERA_ID
    assert first["px_per_mm"] == _PX_PER_MM
    assert isinstance(first["t_wall"], float)


# --------------------------------------------------------------------------- #
# 2. Запись о появлении объекта совпадает с миром                             #
# --------------------------------------------------------------------------- #


def test_spawn_line_matches_world(journal_dir: Path, catalog: Path) -> None:
    """После спавна каждый ключ ``sim.objects`` имеет строку ``spawn`` с тем же ``class_name`` и ``angle_deg``.

    Сравнивается ``object_id``, не дробный ``spawn_encoder`` (design.md §8: он зависит от часов).
    """
    plugin, _ctx, sp = _make_plugin(catalog, str(journal_dir))
    _push_encoder(sp, 0)
    plugin.produce()
    time.sleep(0.03)  # заметно больше spawn_interval_s=0.01
    plugin.produce()

    published = [value for path, value in sp.set_calls if path == "sim.objects"]
    assert published and published[-1], f"setup sanity: сцена не опубликовала ни одного объекта: {sp.set_calls}"
    world = published[-1]

    spawns = [rec for rec in _journal_lines(journal_dir) if rec["kind"] == "spawn"]
    by_id = {rec["passport"]["object_id"]: rec for rec in spawns}
    for object_id, passport in world.items():
        assert object_id in by_id, f"объекта {object_id!r} из sim.objects нет среди spawn-строк: {sorted(by_id)}"
        rec = by_id[object_id]
        assert rec["passport"]["class_name"] == passport["class_name"]
        assert rec["passport"]["angle_deg"] == passport["angle_deg"]
        assert isinstance(rec["t_wall"], float)
        assert "encoder" in rec


# --------------------------------------------------------------------------- #
# 3. Дроссель enc                                                             #
# --------------------------------------------------------------------------- #


def test_enc_throttle(journal_dir: Path, catalog: Path) -> None:
    """``enc_hz=10``, ``t_wall = 1000.0 + 0.03*k`` (k=0..33): ровно 9 строк ``enc``, t-1000 = 0, 0.12, ..., 0.96.

    Арифметика: период 0.1 с; шаг 0.03 -> 3 шага = 0.09 < 0.1, 4 шага = 0.12 >= 0.1, поэтому строка идёт на
    каждом 4-м вызове от ПРЕДЫДУЩЕЙ строки: k = 0, 4, 8, ..., 32 (последняя 32*0.03 = 0.96; k=36 за пределом).
    Запас до границы ±0.01 с на ошибке float ~1e-13, так что порядок сравнения (``>=``/``>``) не влияет.
    """
    plugin, _ctx, sp = _make_plugin(
        catalog, str(journal_dir), {"truth_journal_enc_hz": 10.0, "spawn_interval_s": [3600.0, 3600.0]}
    )
    _push_encoder(sp, 0)

    calls: list[float] = []

    def _fake_wall() -> float:
        value = 1000.0 + 0.03 * len(calls)
        calls.append(value)
        return value

    plugin._wall = _fake_wall  # ПОСЛЕ configure(): шаг заголовка не съедается

    for _ in range(34):
        plugin.produce()
    assert len(calls) == 34, f"produce() обязан звать _wall() ровно один раз за вызов: 34 вызова -> {len(calls)}"

    enc = [rec for rec in _journal_lines(journal_dir) if rec["kind"] == "enc"]
    offsets = [round(rec["t_wall"] - 1000.0, 6) for rec in enc]
    assert offsets == pytest.approx([0.0, 0.12, 0.24, 0.36, 0.48, 0.60, 0.72, 0.84, 0.96], abs=1e-6), (
        f"строк enc: {len(enc)}, смещения t_wall-1000: {offsets}"
    )
    assert all("encoder" in rec for rec in enc)


# --------------------------------------------------------------------------- #
# 4. Выключено = ноль файловых операций                                       #
# --------------------------------------------------------------------------- #


def test_disabled_no_file(tmp_path: Path, catalog: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой ``truth_journal_dir``: в ``tmp_path`` нет ``truth_*``/``*.jsonl`` и ни одного открытия на запись.

    Подмена: ``builtins.open``, ``io.open``, ``pathlib.Path.open`` (режимы w/a/x/+) и ``os.open`` (флаги записи) —
    ставится ПОСЛЕ создания каталога спрайтов и ДО ``configure()``; чтения плагином (каталог, пресеты) не считаются.
    Рабочий каталог — внутри ``tmp_path``: ``Path("")`` == «текущий каталог» поймал бы файл, созданный по ошибке рядом.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    write_opens: list[tuple[str, Any]] = []
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def _is_write(mode: Any) -> bool:
        return isinstance(mode, str) and any(ch in mode for ch in "wax+")

    real_builtin_open, real_io_open, real_path_open, real_os_open = builtins.open, io.open, pathlib.Path.open, os.open

    def _spy_open(file, mode="r", *args, **kwargs):
        if _is_write(mode):
            write_opens.append(("builtins.open", file))
        return real_builtin_open(file, mode, *args, **kwargs)

    def _spy_io_open(file, mode="r", *args, **kwargs):
        if _is_write(mode):
            write_opens.append(("io.open", file))
        return real_io_open(file, mode, *args, **kwargs)

    def _spy_path_open(self, mode="r", *args, **kwargs):
        if _is_write(mode):
            write_opens.append(("Path.open", self))
        return real_path_open(self, mode, *args, **kwargs)

    def _spy_os_open(path, flags, *args, **kwargs):
        if flags & write_flags:
            write_opens.append(("os.open", path))
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy_open)
    monkeypatch.setattr(io, "open", _spy_io_open)
    monkeypatch.setattr(pathlib.Path, "open", _spy_path_open)
    monkeypatch.setattr(os, "open", _spy_os_open)

    plugin, _ctx, sp = _make_plugin(catalog, "")
    _push_encoder(sp, 0)
    for _ in range(5):
        plugin.produce()

    assert write_opens == [], f"при выключенном журнале были открытия на запись: {write_opens}"
    stray = [p for p in tmp_path.rglob("*") if p.is_file() and (p.name.startswith("truth_") or p.suffix == ".jsonl")]
    assert stray == [], f"при выключенном журнале появились файлы: {stray}"
    assert list(cwd.iterdir()) == [], f"в рабочем каталоге появились файлы: {list(cwd.iterdir())}"


# --------------------------------------------------------------------------- #
# 5. Ошибка записи не роняет кадры                                            #
# --------------------------------------------------------------------------- #


def test_journal_write_error_keeps_frames(tmp_path: Path, catalog: Path) -> None:
    """Каталог без права записи: 3 кадра из 3, в ``health`` ровно одна ошибка (``error_count`` реального health).

    Счётчик РЕАЛЬНЫЙ, не MagicMock: ``report_error`` учитывает каждый вызов независимо от окна голоса (``throttle``),
    поэтому «ровно 1» значит: отказ создания/записи заявлен один раз, дальше журнал молчит (а не ``3`` по числу кадров).
    """
    ro_dir = tmp_path / "readonly_journal"
    ro_dir.mkdir()
    ro_dir.chmod(0o500)
    try:
        probe = ro_dir / "probe"
        try:
            probe.write_text("x")
        except OSError:
            pass
        else:
            probe.unlink()
            pytest.skip("процесс обходит права каталога (root?): отказ записи не воспроизвести chmod'ом")

        health = HealthReporter(HealthState(log_only=True), source="scene_source")
        plugin, _ctx, sp = _make_plugin(catalog, str(ro_dir), health=health)
        _push_encoder(sp, 0)

        frames = []
        for _ in range(3):
            items = plugin.produce()
            if items and isinstance(items[0]["frame"], np.ndarray):
                frames.append(items[0])

        assert len(frames) == 3, f"кадров выдано {len(frames)} из 3"
        assert health.error_count == 1, f"ошибок в health: {health.error_count}, ожидалась ровно 1"
        assert list(ro_dir.iterdir()) == [], "в каталоге без прав что-то появилось"
    finally:
        ro_dir.chmod(0o700)


# --------------------------------------------------------------------------- #
# 6. Неверная частота enc                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_hz", [0, -5.0])
def test_bad_enc_hz_rejected(journal_dir: Path, catalog: Path, bad_hz: float) -> None:
    """``truth_journal_enc_hz <= 0`` -> ``ValueError`` из ``configure()`` с именем ключа в тексте."""
    ctx = MagicMock()
    ctx.state_proxy = _FakeStateProxy()
    ctx.config = _config(catalog, str(journal_dir), {"truth_journal_enc_hz": bad_hz})
    plugin = SceneSourcePlugin()

    with pytest.raises(ValueError, match="truth_journal_enc_hz"):
        plugin.configure(ctx)
