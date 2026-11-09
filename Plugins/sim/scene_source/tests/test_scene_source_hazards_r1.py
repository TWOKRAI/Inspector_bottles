# -*- coding: utf-8 -*-
"""Task R1 — hazard-тесты автора (H1-H11 из ``plans/line-sim/tasks/R1.md``): подача дисков по списку.

Приёмочные тесты слепого tester — ``test_acceptance_r1_sequence.py`` (там же A1-A11, не дублируются:
H3 «повторная команда» = A7/A8). Здесь — гонки ``DiscSequence`` с воркером, сбои фабрики, потолки.

Каталоги классов — временные (``tmp_path``), ``data/`` не читается. Буквы — кодовыми точками, чтобы
кириллица не смешалась с латиницей-двойником. Потоки — daemon с ``join(timeout)``.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.layer_render.layers import LayerSpec
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.belt import FACTOR_MM
from Services.line_sim.core.spawner import DiscSequence, SequenceBusy

CA = "А"  # А
CE = "Е"  # Е
CR = "Р"  # Р
CYA = "Я"  # Я

_STEP_DT = 1.5
_ENC_STEP = 100.0
_EMPTY_STATUS = {"mode": "random", "total": 0, "fed": 0, "skipped": 0, "remaining": 0}


# --------------------------------------------------------------------------- #
# Каталог и фабрики                                                           #
# --------------------------------------------------------------------------- #


def _write_catalog(root: Path, letters: list[str], name: str = "cat") -> Path:
    catalog = root / name
    for index, letter in enumerate(letters):
        folder = catalog / letter
        folder.mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, :3] = 60 + 20 * index
        sprite[:, :, 3] = 255
        imwrite_unicode(folder / "0.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return catalog


def _preset(catalog: Path, defect_probability: float = 0.0) -> ScenePreset:
    return ScenePreset(
        catalog_dir=str(catalog), angle_range_deg=(0.0, 360.0), defect_probability=defect_probability, layers=[]
    )


class _HookFactory(ObjectFactory):
    """Настоящая фабрика ленты; перед сборкой зовёт одноразовый ``before_make`` (команда посреди сборки /
    сбой фабрики) и считает вызовы."""

    def __init__(self, preset: ScenePreset) -> None:
        super().__init__(preset)
        self.before_make: Callable[[], None] | None = None
        self.make_calls = 0

    def make(self, object_id, spawn_encoder, rng, **kwargs):
        self.make_calls += 1
        hook, self.before_make = self.before_make, None
        if hook is not None:
            hook()
        return super().make(object_id, spawn_encoder, rng, **kwargs)


def _spacing_spawner(factory, sequence, *, max_active: int = 200, spacing=(10.0, 10.0)) -> ObjectSpawner:
    return ObjectSpawner(factory, spacing_mm=spacing, scene_length_mm=1e9, max_active=max_active, sequence=sequence)


def _letters(spawner: ObjectSpawner) -> list[str]:
    return [obj.passport.class_name for obj in spawner.active_objects()]


# --------------------------------------------------------------------------- #
# H1: гонка next -> make -> pop с командой                                    #
# --------------------------------------------------------------------------- #


def test_h1a_pop_after_replace_is_refused_and_new_head_intact():
    """H1(а): ``pop`` с поколением из снимка ДО ``load(replace=True)`` -> ``False``; ``fed 0``, голова нового
    списка цела. Ловит: ``pop`` без проверки поколения (съел бы диск нового списка)."""
    seq = DiscSequence()
    seq.load([(CA, 0.0), (CE, 10.0), (CR, 20.0)])
    head = seq.next()
    assert (head.mode, head.letter, head.angle_deg, head.pos) == ("list", CA, 0.0, 0)

    new = [(CR, 5.0), (CE, 6.0)]
    assert seq.load(new, replace=True) == 3

    assert seq.pop(head.generation) is False
    assert seq.skip(head.generation) is False
    assert seq.snapshot() == {"mode": "list", "total": 2, "fed": 0, "skipped": 0, "remaining": 2}
    after = seq.next()
    assert (after.letter, after.angle_deg, after.pos) == (CR, 5.0, 0)


def test_h1a_pop_after_set_random_is_refused():
    """H1(а): ``set_random`` тоже меняет поколение — устаревший ``pop`` не оживляет режим списка."""
    seq = DiscSequence()
    seq.load([(CA, 0.0), (CE, 10.0)])
    head = seq.next()
    assert seq.set_random() == 2
    assert seq.pop(head.generation) is False
    assert seq.snapshot() == _EMPTY_STATUS


def test_h1b_command_during_make_discards_object_and_keeps_force_defect(tmp_path):
    """H1(б): команда ``load(replace=True)`` пришла посреди ``factory.make()`` -> объект выброшен (не в ``active``),
    ``_next_id_n`` не сдвинут (следующий получает тот же ``object_id``), следующий успешный спавн — голова нового
    списка, и взведённый до этого форс брака достаётся ему. Ловит: ``pop`` без поколения, объект старого списка в
    ``active``, потерянное нажатие оператора."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    seq.load([(CA, 0.0), (CE, 10.0)])
    spawner = _spacing_spawner(factory, seq)
    rng = np.random.default_rng(0)
    new = [(CR, 77.0), (CE, 88.0)]
    factory.before_make = lambda: seq.load(new, replace=True)
    spawner.force_defect_next()

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)

    assert factory.make_calls == 1
    assert spawner.active_objects() == []
    assert spawner._next_id_n == 1
    assert spawner._last_spawn_wall_s is None
    assert factory.force_defect_pending is True, "нажатие оператора съедено выброшенным объектом"
    assert seq.snapshot() == {"mode": "list", "total": 2, "fed": 0, "skipped": 0, "remaining": 2}

    spawner.tick(now_encoder=1000.0, now_wall_s=2.0, rng=rng)  # порог шага (10 мм) пройден

    (obj,) = spawner.active_objects()
    assert (obj.passport.object_id, obj.passport.class_name, obj.passport.angle_deg) == ("obj-1", CR, 77.0)
    assert obj.passport.defect == "damaged"
    assert seq.snapshot() == {"mode": "list", "total": 2, "fed": 1, "skipped": 0, "remaining": 1}


def test_h1c_load_storm_keeps_counter_invariant(tmp_path):
    """H1(в): поток команд 200 раз ``load(replace=True)``, воркер тикает; в каждом ``snapshot()`` —
    ``fed + skipped + remaining == total``. Держит ТОЛЬКО инвариант (диск, чей ``pop`` прошёл до ``load``,
    вправе появиться после ответа на него — проверка букв по поколению в H1(а)/(б))."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    spawner = _spacing_spawner(factory, seq, max_active=10**6, spacing=(0.5, 0.5))
    seq.load([(CA, 1.0)] * 7)
    stop = threading.Event()
    violations: list[dict] = []
    errors: list[BaseException] = []

    def check(snap: dict) -> None:
        if snap["fed"] + snap["skipped"] + snap["remaining"] != snap["total"]:
            violations.append(snap)

    def worker() -> None:
        rng = np.random.default_rng(1)
        k = 0
        try:
            while not stop.is_set():
                k += 1
                spawner.tick(now_encoder=float(k * 100), now_wall_s=float(k) * 2.0, rng=rng)
                check(seq.snapshot())
        except BaseException as exc:  # noqa: BLE001 — тест: ошибку воркера вернуть в основной поток
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    for n in range(200):
        seq.load([(CE, float(n % 360))] * (3 + n % 5), replace=True)
        check(seq.snapshot())
    stop.set()
    thread.join(timeout=10.0)

    assert not thread.is_alive(), "воркер завис"
    assert not errors, errors
    assert not violations, violations[:3]


# --------------------------------------------------------------------------- #
# H2: две команды без replace на исчерпанном списке                           #
# --------------------------------------------------------------------------- #


class _BarrierLock:
    """Настоящий лок с двумя швами в КРИТИЧЕСКИХ ТОЧКАХ (не на входе в метод `load`): перед захватом
    (`__enter__`/`acquire`: оба потока встречаются, и только потом идут захватывать) и после отпускания
    (`release`/`__exit__`: «отпустить, затем встретиться» — второй поток уже может войти). Первый шов ловит
    «`remaining` прочитан вне лока», второй — «проверка и замена в двух `with`»."""

    def __init__(self) -> None:
        self._real = threading.Lock()
        self._before = threading.Barrier(2, timeout=0.5)
        self._after = threading.Barrier(2, timeout=0.5)

    @staticmethod
    def _meet(barrier: threading.Barrier) -> None:
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass

    def acquire(self, *args, **kwargs):
        self._meet(self._before)
        return self._real.acquire(*args, **kwargs)

    def release(self) -> None:
        self._real.release()
        self._meet(self._after)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def test_h2_two_loads_without_replace_exactly_one_wins():
    """H2: исчерпанный список, два потока одновременно ``load(..., replace=False)`` -> ровно один ``ok``, второй
    ``SequenceBusy``. Швы — ``acquire()`` и ``release()`` лока: при проверке и замене в двух ``with`` оба потока
    отпускают первый лок, встречаются на барьере и оба входят во второй; при ``remaining``, прочитанном вне лока, оба
    читают 0 до встречи перед захватом -> две ``ok`` -> тест красный."""
    seq = DiscSequence()
    seq.load([(CA, 0.0)])
    assert seq.pop(seq.next().generation) is True  # исчерпан: режим list, remaining 0
    real_lock = seq._lock
    seq._lock = _BarrierLock()
    results: list[object] = []
    start = threading.Barrier(2, timeout=5.0)

    def call(letter: str) -> None:
        start.wait()
        try:
            results.append(seq.load([(letter, 1.0)], replace=False))
        except SequenceBusy as busy:
            results.append(busy)

    threads = [threading.Thread(target=call, args=(letter,), daemon=True) for letter in (CE, CR)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
    seq._lock = real_lock  # снимок ниже — без барьера

    assert all(not t.is_alive() for t in threads), "поток завис"
    oks = [r for r in results if isinstance(r, int)]
    busies = [r for r in results if isinstance(r, SequenceBusy)]
    assert len(oks) == 1 and len(busies) == 1, results
    assert busies[0].remaining == 1
    assert seq.snapshot()["total"] == 1 and seq.snapshot()["remaining"] == 1


# --------------------------------------------------------------------------- #
# Плагин: харнесс                                                             #
# --------------------------------------------------------------------------- #


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


class _Rig:
    """Плагин с реальным движком, фейковым ``state_proxy`` и управляемыми часами (как у acceptance-тестов)."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        letters: list[str],
        *,
        defect_probability: float = 0.0,
        preset_path: Path | None = None,
        extra_config: dict | None = None,
    ) -> None:
        self.clock = [1000.0]
        self.enc = 0.0
        monkeypatch.setattr("time.monotonic", lambda: self.clock[0])
        if preset_path is None:
            preset_path = tmp_path / "preset.yaml"
            _preset(_write_catalog(tmp_path, letters), defect_probability).to_yaml(preset_path)
        self.tmp_path = tmp_path
        self.sp = _FakeStateProxy()
        self.ctx = MagicMock()
        self.ctx.state_proxy = self.sp
        self.ctx.config = {
            "resolution_width": 64,
            "resolution_height": 64,
            "spawn_encoder": 0,
            "px_per_mm": 1.0,
            "stale_ms": 200,
            "spawn_interval_s": [0.1, 0.1],
            "scene_length_mm": 1e9,
            "preset_path": str(preset_path),
            "seed": 0,
            **(extra_config or {}),
        }
        self.plugin = self._boot()

    def _boot(self) -> SceneSourcePlugin:
        plugin = SceneSourcePlugin()
        plugin.configure(self.ctx)
        plugin.start(self.ctx)
        self._push()
        return plugin

    def restart(self) -> None:
        """Перезапуск процесса: новый плагин с тем же конфигом."""
        self.plugin = self._boot()

    def _push(self) -> None:
        self.sp.emit(
            [
                Delta(
                    path="sim.belt.encoder",
                    old_value=object(),
                    new_value={"value": self.enc, "mm_s": 0.0, "t": self.clock[0]},
                    source="robot",
                )
            ]
        )

    def step(self, dt: float = _STEP_DT, enc_step: float = _ENC_STEP) -> None:
        self.clock[0] += dt
        self.enc += enc_step
        self._push()
        self.plugin.produce()

    def passports(self) -> list[dict]:
        seen: dict[str, dict] = {}
        for path, value in self.sp.set_calls:
            if path == "sim.objects":
                for object_id, passport in value.items():  # type: ignore[union-attr]
                    seen.setdefault(object_id, dict(passport))
        return list(seen.values())

    def step_until_fed(self, count: int, limit: int = 40) -> None:
        for _ in range(limit):
            if len(self.passports()) >= count:
                return
            self.step()
        raise AssertionError(f"за {limit} шагов подано {len(self.passports())} из {count}: {self.passports()}")

    def call(self, name: str, data: dict | None = None) -> dict:
        return getattr(self.plugin, self.plugin.commands[name])(data)

    def sequence_status(self) -> dict:
        return self.call("scene.status")["sequence"]


# --------------------------------------------------------------------------- #
# H3 (random в середине), H4, H5                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_h3_random_mid_list_drops_remaining_and_spawns_random(tmp_path, monkeypatch):
    """H3: ``{"random": true}`` в середине списка -> ``dropped`` = остаток, статус сброшен, дальше спавн снова
    случайный (появляются классы, которых нет в выброшенном остатке)."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    assert rig.call("scene.sequence", {"discs": [[CR, 0], [CR, 0], [CR, 0], [CR, 0], [CR, 0]]})["status"] == "ok"
    rig.step_until_fed(2)
    fed_before = len(rig.passports())
    remaining = rig.sequence_status()["remaining"]

    resp = rig.call("scene.sequence", {"random": True})

    assert resp == {"status": "ok", "mode": "random", "dropped": remaining}, resp
    assert remaining == 5 - fed_before
    assert rig.sequence_status() == _EMPTY_STATUS
    for _ in range(30):
        rig.step()
    after = [p["class_name"] for p in rig.passports()[fed_before:]]
    assert len(after) > remaining, after
    assert {CA, CE} & set(after), f"после random остались только буквы выброшенного остатка: {after}"


@pytest.mark.timeout(60)
def test_h4_restart_forgets_list(tmp_path, monkeypatch):
    """H4: список живёт только в памяти — новый ``configure()`` -> ``sequence`` в режиме random, total 0.
    Контракт (README): скрипт после рестарта шлёт список заново."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    assert rig.call("scene.sequence", {"discs": [[CA, 0], [CE, 0], [CR, 0]]})["status"] == "ok"
    rig.step_until_fed(1)
    assert rig.sequence_status()["mode"] == "list"

    rig.restart()

    assert rig.sequence_status() == _EMPTY_STATUS


@pytest.mark.timeout(60)
def test_h5_defect_now_hits_next_list_disc_and_survives_pause(tmp_path, monkeypatch):
    """H5: ``scene.defect_now`` в режиме списка (в том числе на паузе) -> следующий диск СПИСКА дефектный,
    его буква и угол на месте; остальные диски (``defect_probability`` 0) — без дефекта. Нажатие на паузе
    не теряется."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    assert rig.call("scene.pause", {"paused": True})["status"] == "ok"
    assert rig.call("scene.sequence", {"discs": [[CE, 11], [CR, 22], [CA, 33]]})["status"] == "ok"
    assert rig.call("scene.defect_now")["status"] == "ok"
    for _ in range(4):
        rig.step()
    assert rig.passports() == []

    assert rig.call("scene.pause", {"paused": False})["status"] == "ok"
    rig.step_until_fed(3)

    got = [(p["class_name"], p["angle_deg"], p["defect"]) for p in rig.passports()]
    assert got == [(CE, 11.0, "damaged"), (CR, 22.0, None), (CA, 33.0, None)], got


@pytest.mark.timeout(60)
def test_h5_defect_probability_applies_to_list_discs(tmp_path, monkeypatch):
    """H5: ``defect_probability`` пресета действует и на диски списка (скрипт P4 ставит 0 сам)."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR], defect_probability=1.0)
    assert rig.call("scene.sequence", {"discs": [[CE, 11], [CR, 22]]})["status"] == "ok"
    rig.step_until_fed(2)
    assert [p["defect"] for p in rig.passports()] == ["damaged", "damaged"]


# --------------------------------------------------------------------------- #
# H6, H7: сбой фабрики; буква пропала из каталога                             #
# --------------------------------------------------------------------------- #


def test_h6_factory_failure_keeps_head(tmp_path):
    """H6: фабрика бросает на первом ``make`` -> исключение наружу, голова не снята (``fed 0``); следующий успех
    даёт ту же букву и тот же угол. Ловит: ``pop`` до ``make`` (диск потерян при транзитном сбое)."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    seq.load([(CE, 42.0), (CR, 43.0)])
    spawner = _spacing_spawner(factory, seq)
    rng = np.random.default_rng(0)

    def boom() -> None:
        raise OSError("каталог моргнул")

    factory.before_make = boom
    with pytest.raises(OSError):
        spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    assert seq.snapshot() == {"mode": "list", "total": 2, "fed": 0, "skipped": 0, "remaining": 2}
    assert spawner.active_objects() == []

    spawner.tick(now_encoder=1000.0, now_wall_s=2.0, rng=rng)

    (obj,) = spawner.active_objects()
    assert (obj.passport.class_name, obj.passport.angle_deg) == (CE, 42.0)
    assert seq.snapshot()["fed"] == 1


def test_h7_letter_missing_from_catalog_is_skipped(tmp_path):
    """H7 (сервис): буквы нет в каталоге фабрики -> ``ValueError`` из ``tick`` (его ловит ``produce``), ``skipped
    += 1``, объект не создан, ``_next_id_n`` цел; следующая буква идёт своим чередом."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    seq.load([(CYA, 1.0), (CE, 2.0)])
    spawner = _spacing_spawner(factory, seq)
    rng = np.random.default_rng(0)

    with pytest.raises(ValueError):
        spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    assert factory.make_calls == 0
    assert spawner.active_objects() == [] and spawner._next_id_n == 1
    assert seq.snapshot() == {"mode": "list", "total": 2, "fed": 0, "skipped": 1, "remaining": 1}

    spawner.tick(now_encoder=1000.0, now_wall_s=2.0, rng=rng)

    (obj,) = spawner.active_objects()
    assert (obj.passport.object_id, obj.passport.class_name, obj.passport.angle_deg) == ("obj-1", CE, 2.0)


@pytest.mark.timeout(60)
def test_h7_plugin_catalog_swap_skips_letter_and_frame_survives(tmp_path, monkeypatch):
    """H7 (плагин): ``preset.commit`` сменил каталог между командой и спавном (тот же механизм —
    ``_pending_factory``) -> буква пропущена (``skipped 1``), кадр не падает, следующая буква подана."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    assert rig.call("scene.sequence", {"discs": [[CA, 1], [CE, 2], [CR, 3]]})["status"] == "ok"
    rig.step_until_fed(1)
    new_catalog = _write_catalog(tmp_path, [CA, CR], name="cat2")
    rig.plugin._pending_factory.append(ObjectFactory(_preset(new_catalog)))

    for _ in range(8):
        rig.step()  # produce() не бросает: ValueError спавнера ловит _warn_factory_error

    assert [(p["class_name"], p["angle_deg"]) for p in rig.passports()] == [(CA, 1.0), (CR, 3.0)]
    assert rig.sequence_status() == {"mode": "list", "total": 3, "fed": 2, "skipped": 1, "remaining": 0}


# --------------------------------------------------------------------------- #
# H8, H9, H10                                                                 #
# --------------------------------------------------------------------------- #


def test_h8_fast_belt_one_second_floor_without_debt(tmp_path):
    """H8: ``spacing_mm [10, 10]`` и лента 500 мм/с -> зазор по ``now_wall_s`` между дисками списка >= 1,0 с;
    порог шага не копит долг: диски идут ровно раз в секунду, а не «пачкой» после паузы."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    seq.load([(CA, 1.0)] * 6)
    spawner = _spacing_spawner(factory, seq)
    rng = np.random.default_rng(0)
    times: list[float] = []
    seen = 0
    dt = 0.1
    for k in range(100):
        now = round(k * dt, 6)
        spawner.tick(now_encoder=now * 500.0 / FACTOR_MM, now_wall_s=now, rng=rng)
        count = len(spawner.active_objects())
        if count > seen:
            times.extend([now] * (count - seen))
            seen = count

    assert len(times) == 6, times
    gaps = [round(b - a, 6) for a, b in zip(times, times[1:])]
    assert all(1.0 <= gap <= 1.1 for gap in gaps), (times, gaps)


def test_h9_max_active_ceiling_holds_list_on_standing_belt(tmp_path):
    """H9: список из 20 на стоящей ленте (``interval_s``) при ``max_active=5`` -> объекты копятся до потолка и не
    больше; остаток ждёт (``fed 5``, ``remaining 15``), исключений нет."""
    factory = _HookFactory(_preset(_write_catalog(tmp_path, [CA, CE, CR])))
    seq = DiscSequence()
    seq.load([(CE, 3.0)] * 20)
    spawner = ObjectSpawner(factory, interval_s=(0.1, 0.1), scene_length_mm=1e9, max_active=5, sequence=seq)
    rng = np.random.default_rng(0)

    for k in range(80):
        spawner.tick(now_encoder=0.0, now_wall_s=float(k), rng=rng)

    assert len(spawner.active_objects()) == 5
    assert seq.snapshot() == {"mode": "list", "total": 20, "fed": 5, "skipped": 0, "remaining": 15}


@pytest.mark.timeout(60)
def test_h9_plugin_length_limit(tmp_path, monkeypatch):
    """H9: 201 и 300 букв -> ``invalid`` (длина > 200), 200 -> ``ok``; ничего не поставлено при отказе."""
    rig = _Rig(tmp_path, monkeypatch, [CA, CE, CR])
    for size in (201, 300):
        resp = rig.call("scene.sequence", {"discs": [[CA, 0]] * size})
        assert resp["status"] == "error" and resp["code"] == "invalid", (size, resp)
        assert rig.sequence_status() == _EMPTY_STATUS
    assert rig.call("scene.sequence", {"discs": [[CA, 0]] * 200}) == {"status": "ok", "queued": 200, "dropped": 0}


def test_h10_random_mode_unchanged_by_idle_sequence(tmp_path):
    """H10: тот же seed без ``sequence`` и с ``DiscSequence()`` в режиме random -> побайтно одинаковые паспорта
    и состояние rng после 20 объектов. Ловит: розыгрыш или порядок rng, протёкший в обычный путь."""
    catalog = _write_catalog(tmp_path, [CA, CE, CR])

    def run(sequence: DiscSequence | None) -> tuple[list[dict], dict]:
        spawner = ObjectSpawner(
            ObjectFactory(_preset(catalog, defect_probability=0.3)),
            spacing_mm=(10.0, 20.0),
            scene_length_mm=1e9,
            lateral_offset_px=(1.0, 5.0),
            sequence=sequence,
        )
        rng = np.random.default_rng(123)
        for k in range(200):
            spawner.tick(now_encoder=float(k * 400), now_wall_s=float(k), rng=rng)
        passports = [obj.passport.to_dict() for obj in spawner.active_objects()[:20]]
        return passports, rng.bit_generator.state

    without, state_without = run(None)
    with_idle, state_with = run(DiscSequence())

    assert len(without) == 20
    assert without == with_idle
    assert state_without == state_with


# --------------------------------------------------------------------------- #
# H11: без движка и без каталога                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_no_engine_and_no_catalog(tmp_path, monkeypatch):
    """H11: плагин без движка -> ``scene.sequence`` с валидным ``discs`` = ``{"status": "ok", "applied": false}``,
    ``{}`` = ``invalid`` (структура раньше ``applied``), ``scene.status.sequence`` = нули в random. Пресет без
    ``catalog_dir`` -> любая буква ``invalid`` с ``unknown``."""
    (tmp_path / "a").mkdir()
    broken = _Rig(tmp_path / "a", monkeypatch, [], preset_path=tmp_path / "missing.yaml")
    assert broken.plugin._spawner is None, "фикстура: движок не должен собраться"
    assert broken.call("scene.sequence", {"discs": [[CA, 0]]}) == {"status": "ok", "applied": False}
    assert broken.call("scene.sequence", {"random": True}) == {"status": "ok", "applied": False}
    empty = broken.call("scene.sequence", {})
    assert empty["status"] == "error" and empty["code"] == "invalid", empty
    assert broken.sequence_status() == _EMPTY_STATUS

    layer_png = tmp_path / "layer.png"
    sprite = np.zeros((12, 12, 4), dtype=np.uint8)
    sprite[:, :, 0] = 200
    sprite[:, :, 3] = 255
    imwrite_unicode(layer_png, cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    nocat_path = tmp_path / "nocat.yaml"
    ScenePreset(
        catalog_dir=None,
        angle_range_deg=(0.0, 360.0),
        defect_probability=0.0,
        layers=[LayerSpec(name="x", mode="static", sprite_source=str(layer_png))],
    ).to_yaml(nocat_path)
    (tmp_path / "b").mkdir()
    nocat = _Rig(tmp_path / "b", monkeypatch, [], preset_path=nocat_path)
    assert nocat.plugin._spawner is not None and nocat.plugin._live_factory.class_names == []

    resp = nocat.call("scene.sequence", {"discs": [[CA, 0], [CE, 1], [CA, 2]]})

    assert resp["status"] == "error" and resp["code"] == "invalid", resp
    assert resp["unknown"] == [CA, CE], resp
    assert nocat.sequence_status() == _EMPTY_STATUS
