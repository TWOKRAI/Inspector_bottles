# -*- coding: utf-8 -*-
"""Hazard-тесты автора, Task 1.1b (план dataset-sidecar-truth): журнал истины ``scene_source``.

Дополняют слепую приёмку ``test_truth_journal.py`` (её файл не правится) тремя местами, где журнал мог бы
соврать молча:

(a) после сбоя фабрики (``_update_truth_belt`` зовётся и там) нет повторной строки ``spawn`` для id, уже
    записанного;
(b) на ``produce()``, который спавнит, ``_wall()`` зовётся ровно один раз, и ``t_wall`` строки ``spawn``
    равен ``now`` этого вызова (у спавна нет своего чтения часов);
(c) файл открылся, а запись упала ``OSError`` -> одна ошибка в health, кадры идут, повторных попыток записи нет.

Ожидаемые значения — литералы, не пересчёт из кода под тестом.
"""

from __future__ import annotations

import json
import time
import uuid
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


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Any] = []
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
    classes_dir = root / "classes"
    for name, (b, g, r) in {"square": (0, 0, 255), "disc": (0, 255, 0)}.items():
        (classes_dir / name).mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, 0], sprite[:, :, 1], sprite[:, :, 2], sprite[:, :, 3] = b, g, r, 255
        imwrite_unicode(classes_dir / name / "sprite.png", sprite)
    return classes_dir


def _make_plugin(tmp_path: Path, health: Any = None) -> tuple[SceneSourcePlugin, Path, _FakeStateProxy]:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    if health is not None:
        ctx.health = health
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "px_per_mm": 2.0,
        "geometry": {"origin_x_mm": 0.0, "origin_y_mm": 0.0},
        "preset_path": str(_make_catalog(tmp_path)),
        "spawn_interval_s": [0.01, 0.01],
        "scene_length_mm": 1_000_000.0,
        "truth_journal_dir": str(journal_dir),
        # enc не должен мешать счёту записей: период 1 час, пишется только самая первая строка
        "truth_journal_enc_hz": 1.0 / 3600.0,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    state_proxy.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 0, "mm_s": 0.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )
    return plugin, journal_dir, state_proxy


def _lines(journal_dir: Path) -> list[dict[str, Any]]:
    files = list(journal_dir.glob("truth_*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(ln) for ln in files[0].read_text(encoding="utf-8").split("\n") if ln]


def test_factory_failure_path_writes_no_duplicate_spawn_line(tmp_path: Path) -> None:
    """Кадры со сбоем фабрики (и один сбой ПОСЛЕ реального спавна в том же tick) не дают второй `spawn` на id."""
    plugin, journal_dir, _sp = _make_plugin(tmp_path)
    assert plugin._spawner is not None
    real_tick = plugin._spawner.tick
    # «реальный tick, затем исключение» — самый опасный случай: объект уже на сцене, а tick бросил;
    # остальные сбои — без tick (набор активных не меняется)
    plan = ["real_then_raise", "raise", "real", "raise", "real", "raise"]
    state = {"call": 0}

    def tick(**kwargs: Any) -> Any:
        mode = plan[state["call"]]
        state["call"] += 1
        if mode != "raise":
            real_tick(**kwargs)
        if mode != "real":
            raise RuntimeError("фабрика недоступна")
        return None

    plugin._spawner.tick = tick  # type: ignore[method-assign]
    seen_ids: set[str] = set()
    for _ in plan:
        time.sleep(0.03)  # заметно больше spawn_interval_s=0.01: каждый реальный tick спавнит
        plugin.produce()
        seen_ids |= {obj.passport.object_id for obj in plugin._spawner.active_objects()}

    spawn_ids = [rec["passport"]["object_id"] for rec in _lines(journal_dir) if rec["kind"] == "spawn"]
    assert seen_ids, "setup sanity: ни один объект не появился на сцене"
    assert len(spawn_ids) == len(set(spawn_ids)), f"повторная строка spawn для id: {spawn_ids}"
    assert set(spawn_ids) == seen_ids, f"spawn-строки {sorted(spawn_ids)} != появившиеся id {sorted(seen_ids)}"


def test_spawn_frame_reads_wall_once_and_spawn_shares_that_now(tmp_path: Path) -> None:
    """`produce()`, который спавнит: ровно один вызов `_wall()`; `t_wall` строки `spawn` == `now` этого вызова."""
    plugin, journal_dir, _sp = _make_plugin(tmp_path)
    calls: list[float] = []

    def fake_wall() -> float:
        value = 5000.0 + 7.0 * len(calls)
        calls.append(value)
        return value

    plugin._wall = fake_wall  # ПОСЛЕ configure(): header уже записан реальным временем

    spawn_now: float | None = None
    for _ in range(20):
        time.sleep(0.03)
        before = len(calls)
        plugin.produce()
        assert len(calls) - before == 1, f"produce() обязан звать _wall() ровно один раз: {len(calls) - before}"
        spawns = [rec for rec in _lines(journal_dir) if rec["kind"] == "spawn"]
        if spawns:
            spawn_now = calls[-1]
            break
    assert spawn_now is not None, "setup sanity: за 20 кадров не появилось ни одной строки spawn"

    first_spawn = next(rec for rec in _lines(journal_dir) if rec["kind"] == "spawn")
    assert first_spawn["t_wall"] == spawn_now, f"t_wall spawn {first_spawn['t_wall']} != now кадра {spawn_now}"


class _FailingHandle:
    """Дескриптор, у которого запись падает `OSError` (диск полон); считает попытки."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.write_calls = 0
        self.closed_calls = 0

    def write(self, text: str) -> int:
        self.write_calls += 1
        raise OSError(28, "No space left on device")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed_calls += 1
        self._real.close()


def test_write_error_after_open_reports_once_and_stops_writing(tmp_path: Path) -> None:
    """Файл открылся, затем запись -> `OSError`: 1 ошибка health, кадры идут, дальше ни одной попытки записи."""
    health = HealthReporter(HealthState(log_only=True), source="scene_source")
    plugin, _journal_dir, sp = _make_plugin(tmp_path, health=health)
    assert health.error_count == 0, "setup sanity: открытие и header прошли без ошибок"
    assert plugin._journal is not None
    handle = _FailingHandle(plugin._journal)
    plugin._journal = handle  # type: ignore[assignment]

    frames = 0
    for _ in range(6):
        time.sleep(0.03)  # будут и спавны: у них тоже не должно быть попыток записи
        items = plugin.produce()
        frames += 1 if items and isinstance(items[0]["frame"], np.ndarray) else 0

    assert frames == 6, f"кадров выдано {frames} из 6"
    assert health.error_count == 1, f"ошибок в health: {health.error_count}, ожидалась ровно 1"
    assert handle.write_calls == 1, f"попыток записи после отказа: {handle.write_calls}, ожидалась 1 (первая)"
    assert handle.closed_calls == 1, "мёртвый файл должен быть закрыт ровно один раз"
    published = [value for path, value in sp.set_calls if path == "sim.objects"]
    assert published, "setup sanity: сцена продолжила спавнить после отказа журнала"
