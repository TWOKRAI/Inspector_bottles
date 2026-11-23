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


def _make_ctx(tmp_path: Path, overrides: dict[str, Any] | None = None, health: Any = None) -> tuple[Any, Path, Any]:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
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
        **(overrides or {}),
    }
    return ctx, journal_dir, state_proxy


def _push_encoder(state_proxy: _FakeStateProxy, value: float) -> None:
    state_proxy.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": value, "mm_s": 0.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )


def _make_plugin(
    tmp_path: Path,
    health: Any = None,
    overrides: dict[str, Any] | None = None,
    world: bool = True,
) -> tuple[SceneSourcePlugin, Path, _FakeStateProxy]:
    ctx, journal_dir, state_proxy = _make_ctx(tmp_path, overrides, health)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    if world:
        _push_encoder(state_proxy, 0)
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


# --------------------------------------------------------------------------- #
# Ревью, раунд 1                                                              #
# --------------------------------------------------------------------------- #


def _kinds(journal_dir: Path) -> list[str]:
    return [rec["kind"] for rec in _lines(journal_dir)]


def test_no_world_delta_writes_header_only(tmp_path: Path) -> None:
    """Журнал включён, мира ещё не было: три `produce()` -> в файле ровно `header` (ни `enc`, ни `spawn`)."""
    plugin, journal_dir, _sp = _make_plugin(tmp_path, world=False)
    for _ in range(3):
        time.sleep(0.03)
        plugin.produce()
    assert _kinds(journal_dir) == ["header"]


@pytest.mark.parametrize("bad_hz", [0, -1.0, True, "5", None, float("nan"), float("inf")])
def test_bad_enc_hz_rejected_even_when_journal_off(tmp_path: Path, bad_hz: Any) -> None:
    """Ключ частоты проверяется и при `truth_journal_dir=""`; `true`, строка, `null`, NaN, inf — тоже отказ."""
    ctx, _journal_dir, _sp = _make_ctx(tmp_path, {"truth_journal_dir": "", "truth_journal_enc_hz": bad_hz})
    with pytest.raises(ValueError, match="truth_journal_enc_hz"):
        SceneSourcePlugin().configure(ctx)


def test_missing_journal_dir_is_created(tmp_path: Path) -> None:
    """Каталога `a/b` нет: после `configure()` он существует и в нём лежит файл с `header`."""
    target = tmp_path / "a" / "b"
    assert not target.exists(), "setup sanity: каталог не должен существовать до configure()"
    ctx, _jd, _sp = _make_ctx(tmp_path, {"truth_journal_dir": str(target)})
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    assert target.is_dir()
    assert _kinds(target) == ["header"]
    plugin.shutdown(ctx)


def test_second_configure_closes_first_handle_and_keeps_earlier_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Два `configure()` одного экземпляра: первый дескриптор закрыт, строки первого не потеряны.

    Время зафиксировано: имя файла (секундная метка + pid) одинаково, поэтому второй `configure()` открывает
    ТОТ ЖЕ файл — режим "w" затёр бы первый `header`."""
    monkeypatch.setattr(time, "time", lambda: 1_800_000_000.0)
    ctx, journal_dir, _sp = _make_ctx(tmp_path)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    first = plugin._journal
    assert first is not None
    plugin.configure(ctx)
    assert first.closed, "прежний дескриптор должен быть закрыт повторным configure()"
    assert plugin._journal is not first
    assert _kinds(journal_dir) == ["header", "header"]
    plugin.shutdown(ctx)


def test_journal_off_never_reads_wall_clock(tmp_path: Path) -> None:
    """Журнал выключен: `_wall` не вызван ни разу за N `produce()` (ноль стоимости при выключенном)."""
    plugin, _jd, _sp = _make_plugin(tmp_path, overrides={"truth_journal_dir": ""})
    calls: list[float] = []
    plugin._wall = lambda: calls.append(1.0) or 1.0  # type: ignore[assignment]
    for _ in range(5):
        time.sleep(0.03)
        plugin.produce()
    assert calls == [], f"при выключенном журнале _wall() вызван {len(calls)} раз"


def test_shutdown_closes_file_and_later_produce_writes_nothing(tmp_path: Path) -> None:
    """`shutdown()` закрывает файл; `produce()` после него не бросает, не пишет и не плодит ошибок health."""
    health = HealthReporter(HealthState(log_only=True), source="scene_source")
    ctx, journal_dir, sp = _make_ctx(tmp_path, health=health)
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    _push_encoder(sp, 0)
    handle = plugin._journal
    assert handle is not None
    plugin.produce()  # enc + возможно spawn
    before = (journal_dir / next(journal_dir.glob("truth_*.jsonl")).name).read_text(encoding="utf-8")

    plugin.shutdown(ctx)
    assert handle.closed
    for _ in range(3):
        time.sleep(0.03)
        assert plugin.produce(), "кадр после shutdown обязан выдаваться"
    after = next(journal_dir.glob("truth_*.jsonl")).read_text(encoding="utf-8")
    assert after == before, "после shutdown в журнал что-то записано"
    assert health.error_count == 0


def test_shutdown_after_failed_configure_does_not_raise(tmp_path: Path) -> None:
    """Оркестратор зовёт `shutdown()` и после упавшего `configure()`: атрибутов журнала может не быть."""
    ctx, _jd, _sp = _make_ctx(tmp_path, {"truth_journal_enc_hz": 0})
    plugin = SceneSourcePlugin()
    with pytest.raises(ValueError, match="truth_journal_enc_hz"):
        plugin.configure(ctx)
    plugin.shutdown(ctx)


def test_write_to_closed_file_is_reported_once_not_raised(tmp_path: Path) -> None:
    """Запись в закрытый файл — `ValueError`, а не `OSError`: тоже одна ошибка health, кадры идут, журнал выключен."""
    health = HealthReporter(HealthState(log_only=True), source="scene_source")
    plugin, _jd, _sp = _make_plugin(tmp_path, health=health)
    assert plugin._journal is not None
    plugin._journal.close()  # файл закрыт, но атрибут жив: путь «ValueError: I/O operation on closed file»
    for _ in range(3):
        assert plugin.produce()
    assert health.error_count == 1
    assert plugin._journal is None


def test_non_finite_encoder_writes_no_enc_and_null_encoder_in_spawn(tmp_path: Path) -> None:
    """Энкодер мира NaN: строки `enc` нет; `spawn` пишется с `encoder: null`; файл — валидный строгий JSON."""
    plugin, journal_dir, sp = _make_plugin(tmp_path, world=False)
    _push_encoder(sp, float("nan"))
    for _ in range(4):
        time.sleep(0.03)
        plugin.produce()

    def _strict(constant: str) -> Any:
        raise AssertionError(f"в журнале нестрогая константа {constant}")

    text = next(journal_dir.glob("truth_*.jsonl")).read_text(encoding="utf-8")
    records = [json.loads(ln, parse_constant=_strict) for ln in text.split("\n") if ln]
    kinds = [rec["kind"] for rec in records]
    assert "enc" not in kinds
    spawns = [rec for rec in records if rec["kind"] == "spawn"]
    assert spawns, f"setup sanity: ни одного spawn при NaN-энкодере: {kinds}"
    assert all(rec["encoder"] is None and rec["passport"]["spawn_encoder"] is None for rec in spawns)


def test_wall_clock_jump_backward_resyncs_enc(tmp_path: Path) -> None:
    """Часы: 1000.0, затем 900.0, 900.2: после скачка назад `enc` не молчит до 1000.1, а пишется на 900.0."""
    plugin, journal_dir, _sp = _make_plugin(
        tmp_path, overrides={"truth_journal_enc_hz": 10.0, "spawn_interval_s": [3600.0, 3600.0]}
    )
    values = iter([1000.0, 900.0, 900.05, 900.2])
    plugin._wall = lambda: next(values)  # type: ignore[assignment]
    for _ in range(4):
        plugin.produce()
    stamps = [rec["t_wall"] for rec in _lines(journal_dir) if rec["kind"] == "enc"]
    assert stamps == [1000.0, 900.0, 900.2], f"t_wall строк enc: {stamps}"
