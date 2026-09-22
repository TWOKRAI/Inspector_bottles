# -*- coding: utf-8 -*-
"""Task 2.2 — независимый RED (тестер, worktree на 362a319a, ДО реализации).

Контракт — Acceptance criteria + DESIGN брифа lead'а (``plans/line-sim/phase-2-belt-truth.md``,
Task 2.2), НЕ код: ``Plugins/sim/scene_source`` СЕГОДНЯ НЕ СУЩЕСТВУЕТ вообще (ни каталога, ни
файла) — это ``import`` НОВОГО модуля, форма RED здесь по конструкции ``ModuleNotFoundError`` на
collection, для ВСЕХ тестов файла разом (тот же приём, что в
``apps/line_sim/tests/test_f1_task12_acceptance.py`` для ``mjpeg_sink``, Task 1.2), а не поломанный
setup теста.

Источники API (прочитаны, не угаданы):
  - ``multiprocess_framework/modules/process_module/plugins/base.py`` — ``PluginContext``
    (``ctx.config``, ``ctx.state_proxy``, ``ctx.log_warning``), базовый ``ProcessModulePlugin``
    (``configure``/``start``/``produce() -> list[dict]``);
  - ``multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:361`` —
    ``subscribe(pattern, callback: Callable[[list[Delta]], None], exclude_self=True, sync=True)``;
  - ``multiprocess_framework/modules/state_store_module/core/delta.py`` — ``Delta(path, old_value,
    new_value, source, timestamp, revision)``, ``MISSING`` sentinel;
  - ``Plugins/sources/synthetic_frame_source/plugin.py`` — форма source-плагина (``configure`` +
    ``produce() -> list[dict]`` с ключом ``"frame"``, конфиг ``resolution_width``/``resolution_height``);
  - ``Services/robot_comm/core/registers.py:35`` — ``FACTOR_MM = 0.144473``.

Догадки тестера (не факт, помечено ниже по месту):
  - имена конфиг-ключей ``spawn_encoder``/``px_per_mm``/``stale_ms`` — взяты БУКВАЛЬНО из
    формулировки DESIGN брифа lead'а («x_px = (encoder − spawn_encoder) × FACTOR_MM × px_per_mm»,
    «stale value (older than stale_ms)»), не из кода — кода нет;
  - форма дельт, которыми колбэк подписки кормится в тесте, — ОБЕ формы, которые прямо называет
    «Решение ведущего» плана: (а) дельта создания с ``new_value`` = целый dict на путь
    ``sim.belt.encoder``, (б) полистовые дельты на ``sim.belt.encoder.value``/``.t``/``.mm_s``;
  - обнаружение спрайта в кадре — генерический метод «диффа с кадром-эталоном» (не цвет/форма
    спрайта, которых контракт не называет): столбцы, отличающиеся от эталона, взвешенный центр масс.
"""

from __future__ import annotations

import ast
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from Services.robot_comm.core.registers import FACTOR_MM

# Module-level import НОВОГО модуля — форма RED: ModuleNotFoundError на collection для
# ВСЕГО файла (см. докстринг).
from Plugins.sim.scene_source.plugin import SPRITE_BGR, SceneSourcePlugin  # noqa: E402

pytestmark = pytest.mark.timeout(30)

_SPAWN_ENCODER = 0
_PX_PER_MM = 1.0
_STALE_MS = 200


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — только ``subscribe()``, без IPC.

    ``emit()`` — рука теста, играющая роль ``DeltaDispatcher``: доставляет список ``Delta``
    ВСЕМ зарегистрированным колбэкам (в тесте подписка ровно одна — паттерн-матчинг не нужен,
    YAGNI).
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[list[Delta]], None],
        exclude_self: bool = True,
        sync: bool = True,
    ) -> str:
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)


def _make_plugin(cfg_overrides: dict | None = None) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": _SPAWN_ENCODER,
        "px_per_mm": _PX_PER_MM,
        "stale_ms": _STALE_MS,
        **(cfg_overrides or {}),
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


def _push_creation(state_proxy: _FakeStateProxy, value: dict, *, t: float | None = None) -> None:
    """Дельта СОЗДАНИЯ узла целиком (форма «а» решения ведущего) — первый ``set()``."""
    payload = dict(value)
    payload.setdefault("t", time.monotonic() if t is None else t)
    state_proxy.emit([Delta(path="sim.belt.encoder", old_value=MISSING, new_value=payload, source="robot")])


def _push_leaf_update(state_proxy: _FakeStateProxy, *, value: int, mm_s: float, t: float) -> None:
    """Полистовые дельты (форма «б» решения ведущего) — последующие ``set()``."""
    state_proxy.emit(
        [
            Delta(path="sim.belt.encoder.value", old_value=None, new_value=value, source="robot"),
            Delta(path="sim.belt.encoder.mm_s", old_value=None, new_value=mm_s, source="robot"),
            Delta(path="sim.belt.encoder.t", old_value=None, new_value=t, source="robot"),
        ]
    )


def _frame_of(plugin: SceneSourcePlugin) -> np.ndarray:
    items = plugin.produce()
    assert isinstance(items, list) and items, f"produce() вернул не непустой список: {items!r}"
    frame = items[0]["frame"]
    assert isinstance(frame, np.ndarray), f"items[0]['frame'] — не ndarray: {type(frame)!r}"
    return frame


def _sprite_centroid_x(frame: np.ndarray, reference: np.ndarray) -> float:
    """Центр масс столбцов пикселей цвета спрайта (контракт ``SPRITE_BGR``).

    Арбитраж ведущего 2026-09-22: прежний дифф против эталона на spawn давал два
    пятна («ушёл отсюда» + «пришёл сюда») для любого спрайта, видимого на spawn, и
    центр масс ложился между ними (98 px при формуле 144). ``reference`` оставлен в
    сигнатуре, чтобы не трогать вызовы; ассерты и литералы тестов не менялись.
    """
    del reference
    mask = np.all(np.abs(frame.astype(int) - np.array(SPRITE_BGR)) <= 40, axis=2)
    weights = mask.sum(axis=0).astype(float)
    assert weights.sum() > 0, "спрайт цвета SPRITE_BGR в кадре не найден"
    return float(np.average(np.arange(frame.shape[1]), weights=weights))


# --------------------------------------------------------------------------- #
# Критерий: пустой мир -> кадр в исходной позиции, без исключения             #
# --------------------------------------------------------------------------- #


def test_empty_world_frame_no_exception() -> None:
    """Пин: до единой публикации энкодера ``produce()`` не бросает и отдаёт валидный кадр.

    Провал сегодня: ``ModuleNotFoundError`` (нового модуля нет)."""
    plugin, _ctx, _sp = _make_plugin()
    frame = _frame_of(plugin)
    assert frame.shape == (480, 640, 3), f"форма кадра не (480,640,3): {frame.shape!r}"
    assert frame.dtype == np.uint8, f"dtype не uint8: {frame.dtype!r}"


# --------------------------------------------------------------------------- #
# Критерий: спрайт едет вслед за энкодером, монотонно и пропорционально       #
# --------------------------------------------------------------------------- #


def test_sprite_moves_with_encoder() -> None:
    """Пин: центр масс спрайта растёт монотонно и на литеральный px из
    ``(encoder - spawn_encoder) * FACTOR_MM * px_per_mm`` (spawn_encoder=0, px_per_mm=1.0 —
    заданы тестом в конфиге, см. докстринг файла).

    Провал сегодня: ``ModuleNotFoundError``."""
    plugin, _ctx, sp = _make_plugin()

    t0 = time.monotonic()
    _push_creation(sp, {"value": 0, "mm_s": 50.0}, t=t0)
    reference = _frame_of(plugin)

    _push_leaf_update(sp, value=1000, mm_s=50.0, t=t0 + 0.05)
    frame_1000 = _frame_of(plugin)
    x_1000 = _sprite_centroid_x(frame_1000, reference)

    _push_leaf_update(sp, value=2000, mm_s=50.0, t=t0 + 0.10)
    frame_2000 = _frame_of(plugin)
    x_2000 = _sprite_centroid_x(frame_2000, reference)

    assert x_1000 < x_2000, f"центр масс не растёт монотонно: x(1000)={x_1000}, x(2000)={x_2000}"

    expected_1000 = (1000 - _SPAWN_ENCODER) * FACTOR_MM * _PX_PER_MM
    expected_2000 = (2000 - _SPAWN_ENCODER) * FACTOR_MM * _PX_PER_MM
    assert x_1000 == pytest.approx(expected_1000, abs=2.0), (
        f"x(encoder=1000)={x_1000} не совпадает с (1000-0)*{FACTOR_MM}*{_PX_PER_MM}={expected_1000}"
    )
    assert x_2000 == pytest.approx(expected_2000, abs=2.0), (
        f"x(encoder=2000)={x_2000} не совпадает с (2000-0)*{FACTOR_MM}*{_PX_PER_MM}={expected_2000}"
    )


# --------------------------------------------------------------------------- #
# Краевой случай: устаревшее значение -> спрайт замирает и пишет предупреждение #
# --------------------------------------------------------------------------- #


def test_stale_world_freezes_and_warns() -> None:
    """Пин: значение мира старше ``stale_ms`` -> позиция спрайта НЕ экстраполируется между
    двумя последовательными кадрами (центр масс не двигается), и ``ctx.log_warning`` вызван
    хотя бы раз (якорь существования — не привязываюсь к тексту сообщения, см. память тестера).

    Провал сегодня: ``ModuleNotFoundError``."""
    plugin, ctx, sp = _make_plugin()

    t0 = time.monotonic()
    _push_creation(sp, {"value": 0, "mm_s": 50.0}, t=t0)
    reference = _frame_of(plugin)

    # Значение "протухло" на 10с при stale_ms=200 (мс) — заведомо устарело.
    stale_t = time.monotonic() - 10.0
    _push_leaf_update(sp, value=5000, mm_s=50.0, t=stale_t)

    frame_a = _frame_of(plugin)
    time.sleep(0.05)
    frame_b = _frame_of(plugin)

    x_a = _sprite_centroid_x(frame_a, reference)
    x_b = _sprite_centroid_x(frame_b, reference)
    assert x_a == pytest.approx(x_b, abs=0.01), (
        f"позиция спрайта сместилась между двумя кадрами на устаревшем значении: {x_a} -> {x_b}"
    )
    assert ctx.log_warning.called, "ctx.log_warning не был вызван на устаревшем значении мира"


# --------------------------------------------------------------------------- #
# Принцип 5 плана: scene_source не знает о robot_host/прототипе               #
# --------------------------------------------------------------------------- #


def test_no_forbidden_imports() -> None:
    """Пин: ни один файл ``Plugins/sim/scene_source`` (кроме ``tests/``) не импортирует
    ``Plugins.sim.robot_host`` или ``multiprocess_prototype``.

    Провал сегодня: тот же ``ModuleNotFoundError`` на collection файла целиком (см. докстринг) —
    сама проверка тривиально вернула бы 0 нарушений на пустом/несуществующем каталоге, поэтому
    её RED сегодня объясняется исключительно import-строкой выше, не собственной логикой."""
    pkg_dir = Path(SceneSourcePlugin.__module__.replace(".", "/")).parent  # на случай будущего рефакторинга модуля
    pkg_dir = Path(__file__).resolve().parents[1]
    forbidden = ("Plugins.sim.robot_host", "multiprocess_prototype")
    offenders: list[str] = []
    for py_file in pkg_dir.rglob("*.py"):
        if "tests" in py_file.relative_to(pkg_dir).parts:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if any(name.startswith(f) for f in forbidden):
                    offenders.append(f"{py_file}: {name}")
    assert not offenders, f"запрещённые импорты в scene_source: {offenders}"
