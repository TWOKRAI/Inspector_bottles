# -*- coding: utf-8 -*-
"""Независимая приёмка `sim-lateral-offset` Task 1.1 — плагин `scene_source` (слепой тестер, ДО реализации).

Контракт — таблица и Acceptance criteria `plans/sim-lateral-offset.md`, НЕ код реализации.
Всё идёт через публичную поверхность плагина: конфиг-словарь, `produce()`, `sim.objects`
(паспорт `to_dict`), `scene.job_done` -> `scene.status.recent`, пиксели кадра. Ожидаемые числа —
литералы из плана (±16.33 пикс, `px_per_mm=8.163265`, `frame_down=(-1, 0)` -> X на 2.0 мм меньше).

Как проверяется «истина робота» (`object_robot_xy`) без знания сигнатуры: объект спавнится на
энкодере 1000, задание приходит с `ecap=1000` (путь вдоль ленты 0 -> слагаемое `BELT_U * off`
исчезает), координаты задания — литералы `origin ∓ 2.0 мм`; `match_radius_mm=0.05` делает
сопоставление точным (допуск плана ±0.01 мм).

Ожидаемая форма RED сегодня: DID NOT RAISE (ключ молча игнорируется), KeyError/AssertionError на
`lateral_px` в `sim.objects`, `no_object` вместо `matched`. GREEN-контроли (должны быть зелёными и
до, и после) помечены `[GREEN-контроль]`.

Что может блокировать (цикл из 200 `produce()`) — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode

_DEADLINE_S = 90.0
_SPRITE = 25  # нечётный размер: центр масс маски = центр спрайта точно
_RED_BGR = (0, 0, 255)
_NAN = float("nan")
_INF = float("inf")

_FRAME_DOWN_GEOMETRY = {"origin_x_mm": 100.0, "origin_y_mm": 200.0, "frame_down_ux": -1.0, "frame_down_uy": 0.0}


def _run_with_deadline(fn, deadline_s: float = _DEADLINE_S):
    """Выполнить `fn` в daemon-потоке с join-дедлайном: зависание = падение теста."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросить в основной поток как есть
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


class _FakeStateProxy:
    """Минимальная замена `StateProxy`: `subscribe()` + `set()` с журналом (как в соседних тестах)."""

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


def _make_preset(tmp_path: Path, *, fixed_angle: bool = True) -> Path:
    """Каталог из одного класса (красный ДИСК диаметром 25 (BGR (0,0,255)) на прозрачном фоне) + YAML-пресет к нему.

    Возвращает путь к YAML-пресету с `angle_range_deg: [0, 0]`: по умолчанию пресет вращает объекты
    случайным углом 0..360, и центр масс повёрнутого спрайта плывёт на ±2 пикс (измерено на коде до
    задачи) — это съело бы допуск ±1 px критерия «центр спрайта по Y»."""
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True, exist_ok=True)
    sprite = np.zeros((_SPRITE, _SPRITE, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:_SPRITE, 0:_SPRITE]
    inside = (xx - _SPRITE // 2) ** 2 + (yy - _SPRITE // 2) ** 2 <= (_SPRITE // 2) ** 2
    b, g, r = _RED_BGR
    sprite[inside] = (b, g, r, 255)
    imwrite_unicode(class_dir / "sprite.png", sprite)
    preset = tmp_path / ("preset_fixed.yaml" if fixed_angle else "preset_random.yaml")
    preset.write_text(
        "catalog_dir: catalog\n"
        + ("angle_range_deg: [0.0, 0.0]\n" if fixed_angle else "angle_range_deg: [0.0, 360.0]\n")
        + "layers: []\ndefect_probability: 0.0\n",
        encoding="utf-8",
    )
    return preset


def _base_cfg(tmp_path: Path, **overrides) -> dict:
    cfg = {
        "resolution_width": 320,
        "resolution_height": 240,
        "px_per_mm": 1.0,
        "belt_y_px": 120,
        "spawn_spacing_mm": [1.0, 1.0],
        "scene_length_mm": 1e9,
        "preset_path": str(_make_preset(tmp_path)),
        "seed": 0,
        "geometry": dict(_FRAME_DOWN_GEOMETRY),
    }
    cfg.update(overrides)
    return cfg


def _build(cfg: dict) -> tuple[SceneSourcePlugin, _FakeStateProxy, MagicMock]:
    """configure + start. ValueError конфигурации обязан вылететь ЗДЕСЬ (не проглочен try/except движка)."""
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = cfg
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, state_proxy, ctx


def _push_creation(sp: _FakeStateProxy, value: int) -> None:
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=MISSING,
                new_value={"value": value, "mm_s": 0.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )


def _push_value(sp: _FakeStateProxy, value: int) -> None:
    sp.emit(
        [
            Delta(path="sim.belt.encoder.value", old_value=None, new_value=value, source="robot"),
            Delta(path="sim.belt.encoder.mm_s", old_value=None, new_value=0.0, source="robot"),
            Delta(path="sim.belt.encoder.t", old_value=None, new_value=time.monotonic(), source="robot"),
        ]
    )


def _all_published_passports(sp: _FakeStateProxy) -> dict[str, dict]:
    """Объединение всех публикаций `sim.objects` по id (последняя запись объекта побеждает)."""
    seen: dict[str, dict] = {}
    for path, value in sp.set_calls:
        if path == "sim.objects":
            seen.update(value)  # type: ignore[arg-type]
    return seen


# --------------------------------------------------------------------------- #
# Валидация ключа `lateral_offset_px`                                         #
# --------------------------------------------------------------------------- #

_BAD_VALUES = [
    pytest.param([-1.0, 5.0], id="lo<0"),
    pytest.param([-0.001, 20.0], id="lo<0-tiny"),
    pytest.param([20.0, 10.0], id="lo>hi"),
    pytest.param([10.5, 10.4], id="lo>hi-close"),
    pytest.param([10.0], id="non-pair-one"),
    pytest.param([10.0, 20.0, 30.0], id="non-pair-three"),
    pytest.param([], id="non-pair-empty"),
    pytest.param("10-20", id="non-pair-string"),
    pytest.param(15, id="non-pair-scalar"),
    pytest.param(["a", "b"], id="non-number-strings"),
    pytest.param([None, 5.0], id="non-number-none"),
    pytest.param([_NAN, 20.0], id="nan-lo"),
    pytest.param([10.0, _NAN], id="nan-hi"),
    pytest.param([10.0, _INF], id="inf-hi"),
    pytest.param([_INF, _INF], id="inf-both"),
]


@pytest.mark.parametrize("bad", _BAD_VALUES)
def test_bad_lateral_offset_raises_value_error_naming_the_key(tmp_path: Path, bad) -> None:
    """Кривой `lateral_offset_px` -> `ValueError` на старте плагина, текст называет ключ.

    `frame_down` в `geometry` есть — отказ не может быть списан на его отсутствие."""
    with pytest.raises(ValueError, match="lateral_offset_px"):
        _build(_base_cfg(tmp_path, lateral_offset_px=bad))


def test_bad_lateral_offset_message_names_the_offending_value(tmp_path: Path) -> None:
    """Текст ошибки для `[20, 10]` называет и значение: в нём есть и 20, и 10 (контракт: «ключ и значение»)."""
    with pytest.raises(ValueError) as info:
        _build(_base_cfg(tmp_path, lateral_offset_px=[20, 10]))
    text = str(info.value)
    assert "lateral_offset_px" in text
    assert "20" in text and "10" in text, text


@pytest.mark.parametrize("ok", [[0, 0], [0, 5], [15, 15], [10, 20], [10.5, 10.5]], ids=str)
def test_valid_lateral_offset_is_accepted(tmp_path: Path, ok) -> None:
    """[GREEN-контроль] Корректные диапазоны (в т.ч. границы `lo = 0`, `lo == hi`) принимаются без ошибки."""
    plugin, _sp, _ctx = _build(_base_cfg(tmp_path, lateral_offset_px=ok))
    assert plugin._spawner is not None, "движок должен собраться"


def test_offset_enabled_without_frame_down_in_geometry_raises(tmp_path: Path) -> None:
    """`[10, 20]` и `geometry` только с origin (без `frame_down_*`) -> `ValueError`, текст называет ключ."""
    cfg = _base_cfg(tmp_path, lateral_offset_px=[10, 20], geometry={"origin_x_mm": 0.0, "origin_y_mm": 0.0})
    with pytest.raises(ValueError, match="lateral_offset_px"):
        _build(cfg)


def test_offset_enabled_without_geometry_at_all_raises(tmp_path: Path) -> None:
    """`[10, 20]` и вовсе без `geometry` в конфиге -> `ValueError`, текст называет ключ."""
    cfg = _base_cfg(tmp_path, lateral_offset_px=[10, 20])
    del cfg["geometry"]
    with pytest.raises(ValueError, match="lateral_offset_px"):
        _build(cfg)


def test_zero_offset_without_frame_down_is_fine(tmp_path: Path) -> None:
    """[GREEN-контроль] `[0, 0]` без `frame_down` — ошибки нет (смещения нет, истина не врёт)."""
    cfg = _base_cfg(tmp_path, lateral_offset_px=[0, 0], geometry={"origin_x_mm": 0.0, "origin_y_mm": 0.0})
    plugin, _sp, _ctx = _build(cfg)
    assert plugin._spawner is not None


def test_absent_key_without_frame_down_is_fine(tmp_path: Path) -> None:
    """[GREEN-контроль] Ключа нет и `frame_down` нет — прежнее поведение, ошибки нет."""
    cfg = _base_cfg(tmp_path, geometry={"origin_x_mm": 0.0, "origin_y_mm": 0.0})
    plugin, _sp, _ctx = _build(cfg)
    assert plugin._spawner is not None


# --------------------------------------------------------------------------- #
# Паспорт в `sim.objects`, диапазон и знак на 200 объектах                    #
# --------------------------------------------------------------------------- #


def _spawn_many(tmp_path: Path, n: int, **overrides) -> dict[str, dict]:
    """Тикать лентой (+100 счётов = 14.4 мм > шага 1 мм): n спавнов, вернуть опубликованные паспорта."""
    plugin, sp, _ctx = _build(
        _base_cfg(tmp_path, resolution_width=160, resolution_height=120, belt_y_px=60, **overrides)
    )

    def go() -> None:
        _push_creation(sp, 0)
        for i in range(1, n + 1):
            _push_value(sp, i * 100)
            plugin.produce()

    _run_with_deadline(go)
    return _all_published_passports(sp)


def test_sim_objects_carries_lateral_px_within_10_20_and_both_signs(tmp_path: Path) -> None:
    """Критерий «стенд»/«диапазон»: с `[10, 20]` каждый из 200 объектов в `sim.objects` несёт `lateral_px`,
    `10 <= |lateral_px| <= 20`, и среди 200 встречаются оба знака."""
    passports = _spawn_many(tmp_path, 205, lateral_offset_px=[10, 20])
    assert len(passports) == 200, f"ожидали 200 объектов (потолок max_active), получено {len(passports)}"
    laterals = [p["lateral_px"] for p in passports.values()]
    mags = [abs(v) for v in laterals]
    assert min(mags) >= 10.0, f"минимум модуля {min(mags)} < 10"
    assert max(mags) <= 20.0, f"максимум модуля {max(mags)} > 20"
    assert {math.copysign(1.0, v) for v in laterals} == {-1.0, 1.0}, "знак залип"


def test_sim_objects_lateral_px_is_a_float(tmp_path: Path) -> None:
    """`lateral_px` в публикуемом словаре — нативный float (JSON-совместимо, не numpy-скаляр)."""
    passports = _spawn_many(tmp_path, 5, lateral_offset_px=[10, 20])
    assert passports
    assert all(type(p["lateral_px"]) is float for p in passports.values())


def test_sim_objects_lateral_px_is_zero_without_key(tmp_path: Path) -> None:
    """Без ключа `sim.objects` всё равно несёт поле, и оно ровно `0.0` у каждого объекта."""
    passports = _spawn_many(tmp_path, 10)
    assert len(passports) == 10
    assert [p["lateral_px"] for p in passports.values()] == [0.0] * 10


def test_sim_objects_zero_range_gives_zero_lateral(tmp_path: Path) -> None:
    """Явный `[0, 0]`: `lateral_px == 0.0` у каждого, без `-0.0`."""
    passports = _spawn_many(tmp_path, 10, lateral_offset_px=[0, 0])
    laterals = [p["lateral_px"] for p in passports.values()]
    assert laterals == [0.0] * 10
    assert not any(math.copysign(1.0, v) < 0 for v in laterals), "найден -0.0"


def test_degenerate_range_gives_exact_magnitude_in_plugin(tmp_path: Path) -> None:
    """Граница `lo == hi == 15`: модуль ровно 15 у всех объектов (знак случаен)."""
    passports = _spawn_many(tmp_path, 40, lateral_offset_px=[15, 15])
    assert len(passports) == 40
    assert {abs(p["lateral_px"]) for p in passports.values()} == {15.0}


# --------------------------------------------------------------------------- #
# Кадр: центр спрайта по Y = belt_y_px + lateral_px                           #
# --------------------------------------------------------------------------- #


def _single_object_frame(tmp_path: Path, seed: int, lateral_offset_px) -> tuple[np.ndarray, dict]:
    """Один объект (шаг спавна 1e6 мм), сдвинут вдоль ленты на ~144 мм; вернуть BGR-кадр и паспорт-словарь."""
    extra = {} if lateral_offset_px is None else {"lateral_offset_px": lateral_offset_px}
    plugin, sp, _ctx = _build(_base_cfg(tmp_path, seed=seed, spawn_spacing_mm=[1e6, 1e6], **extra))
    _push_creation(sp, 0)
    plugin.produce()  # первый тик спавнера создаёт объект на энкодере 0
    _push_value(sp, 1000)  # 1000 * 0.144473 мм * 1 пикс/мм = 144.5 пикс вдоль ленты
    frame = plugin.produce()[0]["frame"]
    passports = _all_published_passports(sp)
    assert len(passports) == 1, f"ожидали ровно один объект, получено {len(passports)}"
    return frame, next(iter(passports.values()))


def _red_centroid(frame: np.ndarray) -> tuple[float, float]:
    mask = (frame[:, :, 2] > 150) & (frame[:, :, 0] < 100) & (frame[:, :, 1] < 100)  # кадр BGR, фон серый 60
    ys, xs = np.nonzero(mask)
    assert ys.size > 0, "красный спрайт не найден в кадре"
    return float(xs.mean()), float(ys.mean())


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_frame_sprite_centre_y_is_belt_y_plus_lateral(tmp_path: Path, seed: int) -> None:
    """Критерий «кадр»: центр спрайта по Y = `belt_y_px + lateral_px` (±1 px округления), где `lateral_px` —
    значение из паспорта объекта. Знак любой — сверка идёт с паспортом, так что перевёрнутый знак тоже падает.

    Отсчёт — от того же спрайта БЕЗ смещения (`cy0`): конвейер рендера до задачи кладёт центр масс этого диска
    на 119.0 при `belt_y_px = 120` (измерено на коде до задачи; смещение −1 к функции не относится), и
    допуск ±1 нужен только под округление `cy`."""
    frame0, _ = _single_object_frame(tmp_path / "base", seed, None)
    _cx0, cy0 = _red_centroid(frame0)
    frame, passport = _single_object_frame(tmp_path / "shifted", seed, [10, 20])
    lateral = passport["lateral_px"]
    assert 10.0 <= abs(lateral) <= 20.0, f"паспорт вне диапазона: {lateral}"
    _cx, cy = _red_centroid(frame)
    assert cy - cy0 == pytest.approx(lateral, abs=1.0), f"cy={cy}, cy0={cy0}, lateral_px={lateral}"


def test_frame_sprite_x_is_not_shifted_by_lateral(tmp_path: Path) -> None:
    """Поперечное смещение не двигает спрайт по X: cx при `[16, 16]` совпадает с cx без ключа (±0.5)."""
    frame_off, _ = _single_object_frame(tmp_path / "off", 0, None)
    frame_on, _ = _single_object_frame(tmp_path / "on", 0, [16, 16])
    cx_off, _ = _red_centroid(frame_off)
    cx_on, _ = _red_centroid(frame_on)
    assert cx_on == pytest.approx(cx_off, abs=0.5)


def test_frame_without_key_keeps_sprite_on_belt_y(tmp_path: Path) -> None:
    """[GREEN-контроль] Без ключа центр спрайта по Y = `belt_y_px = 120` (±1.5 px: конвейер рендера кладёт
    центр масс диска на 119.0 — см. докстринг теста выше), как до задачи."""
    frame, _ = _single_object_frame(tmp_path, 0, None)
    _cx, cy = _red_centroid(frame)
    assert cy == pytest.approx(120.0, abs=1.5)


# --------------------------------------------------------------------------- #
# Истина робота: `object_robot_xy` += (lateral_px / px_per_mm) * frame_down   #
# --------------------------------------------------------------------------- #

_PX_PER_MM = 8.163265
_LATERAL = 16.33  # 16.33 / 8.163265 = 2.0004 мм


def _truth_setup(tmp_path: Path, seed: int = 0) -> tuple[SceneSourcePlugin, _FakeStateProxy, str, float]:
    """Один объект с `lateral_px = ±16.33` на энкодере 1000; вернуть (плагин, прокси, object_id, lateral_px)."""
    cfg = _base_cfg(
        tmp_path,
        seed=seed,
        px_per_mm=_PX_PER_MM,
        belt_y_px=120,
        spawn_spacing_mm=[1e6, 1e6],
        lateral_offset_px=[_LATERAL, _LATERAL],
        match_radius_mm=0.05,
    )
    plugin, sp, _ctx = _build(cfg)
    _push_creation(sp, 1000)
    plugin.produce()
    passports = _all_published_passports(sp)
    assert len(passports) == 1
    object_id, passport = next(iter(passports.items()))
    assert abs(passport["lateral_px"]) == pytest.approx(_LATERAL, abs=1e-9)
    return plugin, sp, object_id, passport["lateral_px"]


def _send_job(plugin: SceneSourcePlugin, x_mm: float, y_mm: float, ecap: int) -> dict:
    reply = plugin.cmd_job_done({"index": 1, "x_mm": x_mm, "y_mm": y_mm, "ecap": ecap, "t": 0.0})
    assert reply == {"status": "ok"}, reply
    plugin.produce()  # разбор очереди заданий — в начале следующего produce()
    recent = plugin.cmd_status()["recent"]
    assert recent, "исход задания не записан"
    return recent[-1]


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_truth_x_shifted_by_two_mm_against_frame_down_y_unchanged(tmp_path: Path, seed: int) -> None:
    """Критерий «истина»: `lateral_px=±16.33`, `px_per_mm=8.163265`, `frame_down=(-1, 0)`, origin (100, 200),
    `ecap = spawn_encoder`: объект лежит в (100 − 2.0·sign, 200.0) (±0.01 мм) — задание ровно туда сопоставляется
    (`matched`, невязка < 0.01), хотя радиус всего 0.05 мм."""
    plugin, _sp, object_id, lateral = _truth_setup(tmp_path, seed)
    sign = 1.0 if lateral > 0 else -1.0
    outcome = _send_job(plugin, x_mm=100.0 - 2.0 * sign, y_mm=200.0, ecap=1000)
    assert outcome["outcome"] == "matched", outcome
    assert outcome["object_id"] == object_id
    assert outcome["residual_mm"] < 0.01, outcome


def test_truth_is_not_where_the_unshifted_object_would_be(tmp_path: Path) -> None:
    """Задание в (100, 200) — где объект лежал бы без смещения — НЕ сопоставляется (до объекта 2.0 мм > 0.05)."""
    plugin, _sp, _oid, _lateral = _truth_setup(tmp_path)
    outcome = _send_job(plugin, x_mm=100.0, y_mm=200.0, ecap=1000)
    assert outcome["outcome"] == "no_object", outcome
    assert outcome["residual_mm"] == pytest.approx(2.0, abs=0.01), outcome


def test_truth_shift_has_the_right_sign(tmp_path: Path) -> None:
    """Зеркальная точка (100 + 2.0·sign, 200) — сторона, противоположная `frame_down` для `lateral > 0` — не
    сопоставляется, невязка ≈ 4.0 мм (ловит перепутанный знак слагаемого)."""
    plugin, _sp, _oid, lateral = _truth_setup(tmp_path, seed=1)
    sign = 1.0 if lateral > 0 else -1.0
    outcome = _send_job(plugin, x_mm=100.0 + 2.0 * sign, y_mm=200.0, ecap=1000)
    assert outcome["outcome"] == "no_object", outcome
    assert outcome["residual_mm"] == pytest.approx(4.0, abs=0.01), outcome


def test_truth_lateral_term_is_orthogonal_to_belt_travel(tmp_path: Path) -> None:
    """Поперечное слагаемое не смешивается с ходом ленты: через 1000 счётов объект на (100 − 2.0·sign,
    200 + 144.473) — X сдвинут только поперечным слагаемым, Y — только путём вдоль ленты (BELT_U = (0, 1))."""
    plugin, _sp, object_id, lateral = _truth_setup(tmp_path, seed=2)
    sign = 1.0 if lateral > 0 else -1.0
    outcome = _send_job(plugin, x_mm=100.0 - 2.0 * sign, y_mm=200.0 + 144.473, ecap=2000)
    assert outcome["outcome"] == "matched", outcome
    assert outcome["object_id"] == object_id
    assert outcome["residual_mm"] < 0.01, outcome


def test_truth_without_lateral_is_unchanged_control(tmp_path: Path) -> None:
    """[GREEN-контроль] Без ключа объект в (100, 200 + путь): задание ровно туда — `matched` (прежнее поведение)."""
    cfg = _base_cfg(tmp_path, px_per_mm=_PX_PER_MM, spawn_spacing_mm=[1e6, 1e6], match_radius_mm=0.05)
    plugin, _sp, _ctx = _build(cfg)
    _push_creation(_sp, 1000)
    plugin.produce()
    outcome = _send_job(plugin, x_mm=100.0, y_mm=200.0, ecap=1000)
    assert outcome["outcome"] == "matched", outcome
    assert outcome["residual_mm"] < 0.01, outcome


# --------------------------------------------------------------------------- #
# Дефолт: «байт в байт как до задачи»                                         #
# --------------------------------------------------------------------------- #


def _golden_run(tmp_path: Path, lateral_offset_px) -> tuple[str, str]:
    """12 шагов ленты (seed 7, шаг спавна 60 мм): sha256 всех кадров + JSON паспортов БЕЗ ключа `lateral_px`
    (его до задачи не было — сравнивается всё прежнее содержимое словарей)."""
    extra = {} if lateral_offset_px is None else {"lateral_offset_px": lateral_offset_px}
    cfg = _base_cfg(
        tmp_path,
        seed=7,
        resolution_width=160,
        resolution_height=120,
        belt_y_px=60,
        spawn_spacing_mm=[60.0, 60.0],
        # случайный угол 0..360: каждый спавн тянет из rng, так что лишний/сдвинутый розыгрыш виден в паспортах
        preset_path=str(_make_preset(tmp_path, fixed_angle=False)),
        **extra,
    )
    plugin, sp, _ctx = _build(cfg)
    digest = hashlib.sha256()
    _push_creation(sp, 0)
    for step in range(1, 13):
        _push_value(sp, step * 500)
        digest.update(plugin.produce()[0]["frame"].tobytes())
    passports = _all_published_passports(sp)
    cleaned = {oid: {k: v for k, v in p.items() if k != "lateral_px"} for oid, p in passports.items()}
    return digest.hexdigest(), json.dumps(cleaned, sort_keys=True, ensure_ascii=False)


# Литералы сняты с кода ДО задачи (коммит плана ce29455a) — см. `_golden_run`.
_GOLDEN_FRAMES_SHA256 = "f722e937321a1c2b94f077d1117e7f752e9627165734d62d458173cd1f7a8e3f"
_GOLDEN_PASSPORTS_SHA256 = "5060aac6584557026dfbdb5340be3890570a7f0115a094be670d33f74fe9fb0b"


def test_default_frames_and_passports_are_byte_identical_to_pre_task(tmp_path: Path) -> None:
    """[GREEN-контроль, обязан остаться зелёным] Без ключа: тот же seed -> тот же кадр (sha256 12 кадров) и те же
    паспорта (кроме нового ключа) — литералы сняты с кода до задачи."""
    frames_sha, passports_json = _golden_run(tmp_path, None)
    assert frames_sha == _GOLDEN_FRAMES_SHA256
    assert hashlib.sha256(passports_json.encode("utf-8")).hexdigest() == _GOLDEN_PASSPORTS_SHA256


def test_explicit_zero_range_is_byte_identical_to_absent_key(tmp_path: Path) -> None:
    """`[0, 0]` даёт те же кадры и те же паспорта, что отсутствие ключа (rng не сдвигается)."""
    absent = _golden_run(tmp_path / "absent", None)
    zero = _golden_run(tmp_path / "zero", [0, 0])
    assert zero == absent


def test_nonzero_range_does_change_the_frames(tmp_path: Path) -> None:
    """Контрпроверка на пустоту: `[10, 20]` кадры МЕНЯЕТ (иначе сравнение «байт в байт» выше ничего не доказывает)."""
    absent_frames, _ = _golden_run(tmp_path / "absent", None)
    shifted_frames, _ = _golden_run(tmp_path / "shifted", [10, 20])
    assert shifted_frames != absent_frames
