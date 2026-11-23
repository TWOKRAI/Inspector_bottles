# -*- coding: utf-8 -*-
"""Приёмка C-87 (слепой тестер, этап 1, ДО реализации): досчёт энкодера между пачками дельт.

Контракт (из ``reds_final.md`` лида, не из кода плагина): ``SceneSourcePlugin._read_world_encoder()``
возвращает ``value + mm_s * clamp(age_s, 0, stale_ms/1000) / FACTOR_MM``, где
``age_s = clock() - t``, а ``FACTOR_MM = 0.144473`` мм на отсчёт энкодера.

Наблюдаемое: возврат ``_read_world_encoder()`` после того, как ``Delta`` поданы в колбэк, который
плагин зарегистрировал в ``start()`` через ``ctx.state_proxy.subscribe(...)``. Часы — шов
``plugin._clock`` (функция без аргументов -> секунды); подменяется ПОСЛЕ ``configure()``
(патч ``time.monotonic`` после ``configure`` не действует). Предупреждения — ``ctx.log_warning``.

Обе формы дельты законны и проверяются: словарь целиком на пути ``sim.belt.encoder`` и листья
``sim.belt.encoder.value`` / ``.mm_s`` / ``.t``.

Ожидаемые числа — ЛИТЕРАЛЫ (в комментарии показана арифметика; в теле тестов коэффициент не
используется). Допуск по умолчанию 1e-4 (REDS 3 — 1e-3).

Покрытие: REDS 1-6 и 8 здесь; RED 7 (живой стенд) — ``test_acceptance_c87_live_step.py``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

#: Момент публикации первой дельты (литерал, секунды часов плагина).
T = 5000.0

_ENC = "sim.belt.encoder"


class _FakeStateProxy:
    """Двойник ``StateProxy``: ``subscribe`` запоминает колбэк, ``emit`` вызывает его."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:  # плагин может писать sim.objects и т.п.
        pass


def _make_plugin(stale_ms: int = 500) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    """Плагин после ``configure`` + ``start`` на двойнике ``state_proxy`` (без движка)."""
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": stale_ms,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


def _publish_dict(sp: _FakeStateProxy, value, mm_s, t) -> None:
    """Форма «словарь целиком» — один путь ``sim.belt.encoder``."""
    sp.emit([Delta(path=_ENC, old_value=object(), new_value={"value": value, "mm_s": mm_s, "t": t}, source="robot")])


def _publish_leaves(sp: _FakeStateProxy, value, mm_s, t) -> None:
    """Форма «листья» — три дельты ``.value`` / ``.mm_s`` / ``.t`` в одной пачке."""
    sp.emit(
        [
            Delta(path=f"{_ENC}.value", old_value=object(), new_value=value, source="robot"),
            Delta(path=f"{_ENC}.mm_s", old_value=object(), new_value=mm_s, source="robot"),
            Delta(path=f"{_ENC}.t", old_value=object(), new_value=t, source="robot"),
        ]
    )


_FORMS = pytest.mark.parametrize("publish", [_publish_dict, _publish_leaves], ids=["dict", "leaves"])


def _read_at(plugin: SceneSourcePlugin, now: float) -> float:
    """Прочитать энкодер при часах плагина, замороженных на ``now``."""
    plugin._clock = lambda: now
    return plugin._read_world_encoder()


# --------------------------------------------------------------------------- #
# RED 1 — сдвиг равен mm_s * возраст в единицах энкодера                      #
# --------------------------------------------------------------------------- #


@_FORMS
@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (0.06, 1008.30605),  # 1000 + 0.06 * 20 / 0.144473
        (0.12, 1016.61210),  # 1000 + 0.12 * 20 / 0.144473
    ],
)
def test_red1_reading_shifts_by_mm_s_times_age_in_encoder_units(publish, age, expected) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, 20, T)
    assert _read_at(plugin, T + age) == pytest.approx(expected, abs=1e-4)


# --------------------------------------------------------------------------- #
# RED 2 — равный шаг между кадрами, без «ноль, ноль, прыжок»                  #
# --------------------------------------------------------------------------- #


@_FORMS
def test_red2_readings_strictly_increasing_with_equal_step_across_new_delta(publish) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, 20, T)
    before = [_read_at(plugin, T + dt) for dt in (0.00, 0.04, 0.08)]
    # Вторая дельта приходит с целым value (как публикует robot_host), t = T + 0.12.
    publish(sp, 1017, 20, T + 0.12)
    after = [_read_at(plugin, T + dt) for dt in (0.12, 0.16)]
    readings = before + after

    expected = [1000.0, 1005.53737, 1011.07473, 1017.0, 1022.53737]
    assert readings == pytest.approx(expected, abs=1e-4)
    steps = [b - a for a, b in zip(readings, readings[1:])]
    assert all(s > 0 for s in steps), f"чтения не строго растут: {readings}"
    # Шаг 5.53737 = 0.04 * 20 / 0.144473; дельта на стыке даёт 5.925 — в пределах ±1.
    assert all(abs(s - 5.53737) <= 1.0 for s in steps), f"шаги {steps} вне ±1 от 5.53737"


# --------------------------------------------------------------------------- #
# RED 3 — потолок stale_ms и предупреждение                                   #
# --------------------------------------------------------------------------- #


@_FORMS
@pytest.mark.parametrize("age", [0.201, 10.0, 100.0])
def test_red3_stale_age_caps_shift_at_stale_ms_and_warns(publish, age) -> None:
    plugin, ctx, sp = _make_plugin(stale_ms=200)
    publish(sp, 1000, 20, T)
    # Потолок: 1000 + 0.2 * 20 / 0.144473 = 1027.68683 при любом возрасте > 0.2 с.
    assert _read_at(plugin, T + age) == pytest.approx(1027.68683, abs=1e-3)
    assert ctx.log_warning.called, f"нет предупреждения для протухшей дельты (возраст {age} с)"


@_FORMS
def test_red3_age_just_below_stale_ms_is_extrapolated_without_warning(publish) -> None:
    plugin, ctx, sp = _make_plugin(stale_ms=200)
    publish(sp, 1000, 20, T)
    # 1000 + 0.199 * 20 / 0.144473 = 1027.54840; порог строгий «>»: 0.199 < 0.2 — без предупреждения.
    assert _read_at(plugin, T + 0.199) == pytest.approx(1027.54840, abs=1e-3)
    assert ctx.log_warning.call_count == 0, f"лишнее предупреждение: {ctx.log_warning.call_args_list}"


# --------------------------------------------------------------------------- #
# RED 4 — mm_s = 0: позиция не движется                                       #
# --------------------------------------------------------------------------- #


@_FORMS
@pytest.mark.parametrize("age", [0.0, 0.06, 10.0])
def test_red4_zero_speed_reading_equals_value(publish, age) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, 0, T)
    assert _read_at(plugin, T + age) == 1000.0


# --------------------------------------------------------------------------- #
# RED 5 — новая дельта с меньшим value: чтение следует за ней                 #
# --------------------------------------------------------------------------- #


@_FORMS
def test_red5_newer_delta_with_smaller_value_replaces_old_trajectory(publish) -> None:
    plugin, _ctx, sp = _make_plugin()
    t2 = T + 0.2
    publish(sp, 1000, 20, T)
    publish(sp, 900, 20, t2)
    # 900 + 0.06 * 20 / 0.144473 = 908.30605. Старая траектория дала бы
    # 1000 + 0.26 * 20 / 0.144473 = 1035.99 (или max(старая, новая)) — это ошибка.
    assert _read_at(plugin, t2 + 0.06) == pytest.approx(908.30605, abs=1e-4)


# --------------------------------------------------------------------------- #
# RED 6 — отрицательный возраст (now < t) даёт сдвиг 0                        #
# --------------------------------------------------------------------------- #


@_FORMS
def test_red6_negative_age_gives_zero_shift(publish) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, 20, T)
    assert _read_at(plugin, T - 0.05) == 1000.0


# --------------------------------------------------------------------------- #
# RED 8 — битые поля: без исключения, чтение равно value                      #
# --------------------------------------------------------------------------- #


def test_red8_dict_with_only_value_returns_value() -> None:
    plugin, _ctx, sp = _make_plugin()
    sp.emit([Delta(path=_ENC, old_value=object(), new_value={"value": 1000}, source="robot")])
    assert _read_at(plugin, T + 0.06) == 1000


def test_red8_value_and_t_without_mm_s_returns_value() -> None:
    plugin, _ctx, sp = _make_plugin()
    sp.emit([Delta(path=_ENC, old_value=object(), new_value={"value": 1000, "t": T}, source="robot")])
    assert _read_at(plugin, T + 0.06) == 1000


@_FORMS
@pytest.mark.parametrize(
    "bad_mm_s",
    [math.nan, math.inf, -math.inf, None, "abc"],
    ids=["nan", "inf", "-inf", "none", "abc"],
)
def test_red8_non_finite_or_non_numeric_mm_s_returns_value(publish, bad_mm_s) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, bad_mm_s, T)
    assert _read_at(plugin, T + 0.06) == 1000


@_FORMS
def test_red8_nan_t_returns_value(publish) -> None:
    plugin, _ctx, sp = _make_plugin()
    publish(sp, 1000, 20, math.nan)
    assert _read_at(plugin, T + 0.06) == 1000
