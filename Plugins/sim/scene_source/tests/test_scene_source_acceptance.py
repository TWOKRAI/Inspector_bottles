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
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.robot_comm.core.registers import FACTOR_MM

# Module-level import НОВОГО модуля — форма RED: ModuleNotFoundError на collection для
# ВСЕГО файла (см. докстринг).
from Plugins.sim.scene_source.plugin import SceneSourcePlugin  # noqa: E402

pytestmark = pytest.mark.timeout(30)

_SPAWN_ENCODER = 0
_PX_PER_MM = 1.0
_STALE_MS = 200

# --------------------------------------------------------------------------- #
# ПРАВКА Task 3.4 (разработчик, не тестер): заглушка-спрайт (SPRITE_BGR,       #
# диффовый детектор) заменена реальным движком line_sim — контракт задачи     #
# требует замены рендера, а этот файл пинил именно старое поведение. Список   #
# изменений — в отчёте разработчика (коммит Task 3.4): убран импорт           #
# SPRITE_BGR (символа больше нет); добавлены хелперы фикстур-каталога и       #
# детерминированного спавна ОДНОГО объекта (interval настолько мал, что ЛЮБОЙ #
# реальный wall-clock зазор между produce() пересекает срок — тот же приём,   #
# что уже используют hazard-тесты Services/line_sim/tests); тела              #
# test_sprite_moves_with_encoder и test_stale_world_freezes_and_warns         #
# переписаны на цвет объекта каталога вместо SPRITE_BGR, с сохранением        #
# точной аналитической формулы смещения там, где она осталась проверяемой     #
# (spawn_encoder теперь внутренний и детерминирован постановкой теста, а не   #
# конфиг-ключом). test_empty_world_frame_no_exception и                       #
# test_no_forbidden_imports не менялись по существу (только убран            #
# неиспользуемый импорт).                                                    #
# --------------------------------------------------------------------------- #

_SPAWN_INTERVAL_S = (1.0, 1.0)  # достаточно мал для одного sleep(1.2), достаточно велик,
# чтобы остаток теста (без sleep + один явный sleep(0.05)) НЕ пересёк срок повторно


def _make_fixture_catalog(tmp_path: Path, color_bgr: tuple[int, int, int]) -> Path:
    """Каталог из одного класса `square` — непрозрачный 16x16 спрайт чистого цвета
    (тот же приём, что Services/line_sim/tests/test_acceptance_3_4.py)."""
    classes_dir = tmp_path / "classes"
    class_dir = classes_dir / "square"
    class_dir.mkdir(parents=True)
    b, g, r = color_bgr
    sprite_bgra = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite_bgra[:, :, 0] = b
    sprite_bgra[:, :, 1] = g
    sprite_bgra[:, :, 2] = r
    sprite_bgra[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite_bgra)
    return classes_dir


def _object_centroid_x(frame: np.ndarray, color_bgr: tuple[int, int, int]) -> float:
    """Центр масс столбцов пикселей цвета объекта (в BGR — `item["frame"]` уже BGR)."""
    mask = np.all(np.abs(frame.astype(int) - np.array(color_bgr)) <= 40, axis=2)
    weights = mask.sum(axis=0).astype(float)
    assert weights.sum() > 0, "объект цвета color_bgr в кадре не найден"
    return float(np.average(np.arange(frame.shape[1]), weights=weights))


def _spawn_one_object_at_encoder_zero(plugin: SceneSourcePlugin, state_proxy: "_FakeStateProxy", t0: float) -> None:
    """Детерминированно заспавнить РОВНО один объект с `spawn_encoder=0`: мир создаётся
    со значением 0 ДО первого produce() (взводит срок), затем produce() ПОСЛЕ
    sleep(1.2) (> `_SPAWN_INTERVAL_S`) спавнит объект на текущем (всё ещё нулевом)
    значении мира — тот же приём, что `test_render_does_not_tick_the_spawner`
    (Services/line_sim/tests/test_acceptance_3_4.py): интервал (1с) заведомо больше
    последующих шагов теста (без sleep + один explicit sleep(0.05)), поэтому второй
    спавн НЕ происходит внутри этих же тестов."""
    _push_creation(state_proxy, {"value": 0, "mm_s": 0.0}, t=t0)
    plugin.produce()  # первый tick() только взводит срок
    time.sleep(1.2)
    plugin.produce()  # второй tick() спавнит объект, spawn_encoder = текущее значение мира (0)


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — только ``subscribe()``, без IPC.

    ``emit()`` — рука теста, играющая роль ``DeltaDispatcher``: доставляет список ``Delta``
    ВСЕМ зарегистрированным колбэкам (в тесте подписка ровно одна — паттерн-матчинг не нужен,
    YAGNI).
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

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

    def set(self, path: str, value: object) -> None:
        """Task 3.4: плагин пишет `sim.objects` через `state_proxy.set()` — фейк просто
        запоминает последнее значение (без реального дерева, без IPC)."""
        self.set_calls.append((path, value))


def _make_plugin_with_engine(
    tmp_path: Path, color_bgr: tuple[int, int, int], cfg_overrides: dict | None = None
) -> tuple[SceneSourcePlugin, MagicMock, _FakeStateProxy]:
    """`_make_plugin()` + реальный движок line_sim: `preset_path` на фикстур-каталог
    одного класса, `spawn_interval_s=_SPAWN_INTERVAL_S`, огромная `scene_length_mm`
    (объект не деспавнится за время теста)."""
    catalog_dir = _make_fixture_catalog(tmp_path, color_bgr)
    return _make_plugin(
        {
            "preset_path": str(catalog_dir),
            "spawn_interval_s": list(_SPAWN_INTERVAL_S),
            "scene_length_mm": 1_000_000.0,
            **(cfg_overrides or {}),
        }
    )


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


def test_sprite_moves_with_encoder(tmp_path: Path) -> None:
    """Пин (обновлён Task 3.4 — см. блок правки выше файла): центр масс цвета объекта
    растёт монотонно и на литеральный px из ``(encoder - spawn_encoder) * FACTOR_MM *
    px_per_mm``, где ``spawn_encoder=0`` детерминировано постановкой теста
    (``_spawn_one_object_at_encoder_zero`` — мир на нуле в момент, когда спавнер реально
    создаёт объект), ``px_per_mm=1.0`` — из конфига."""
    color_bgr = (0, 0, 255)
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, color_bgr)

    t0 = time.monotonic()
    _spawn_one_object_at_encoder_zero(plugin, sp, t0)

    _push_leaf_update(sp, value=1000, mm_s=50.0, t=time.monotonic())
    frame_1000 = _frame_of(plugin)
    x_1000 = _object_centroid_x(frame_1000, color_bgr)

    _push_leaf_update(sp, value=2000, mm_s=50.0, t=time.monotonic())
    frame_2000 = _frame_of(plugin)
    x_2000 = _object_centroid_x(frame_2000, color_bgr)

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


def test_stale_world_freezes_and_warns(tmp_path: Path) -> None:
    """Пин (обновлён Task 3.4 — см. блок правки выше файла): значение мира старше
    ``stale_ms`` -> позиция объекта НЕ экстраполируется между двумя последовательными
    кадрами (центр масс не двигается), и ``ctx.log_warning`` вызван хотя бы раз (якорь
    существования — не привязываюсь к тексту сообщения, см. память тестера)."""
    color_bgr = (0, 0, 255)
    plugin, ctx, sp = _make_plugin_with_engine(tmp_path, color_bgr)

    t0 = time.monotonic()
    _spawn_one_object_at_encoder_zero(plugin, sp, t0)

    # Значение "протухло" на 10с при stale_ms=200 (мс) — заведомо устарело. value=200
    # (не 5000, как в исходном пине заглушки) — с реальным движком (конечная камера,
    # без бесконечной ленты по модулю) смещение обязано остаться внутри кадра 640 px,
    # иначе объект уезжает за кадр и центроид искать не в чем.
    stale_t = time.monotonic() - 10.0
    _push_leaf_update(sp, value=200, mm_s=50.0, t=stale_t)

    frame_a = _frame_of(plugin)
    time.sleep(0.05)
    frame_b = _frame_of(plugin)

    x_a = _object_centroid_x(frame_a, color_bgr)
    x_b = _object_centroid_x(frame_b, color_bgr)
    assert x_a == pytest.approx(x_b, abs=0.01), (
        f"позиция объекта сместилась между двумя кадрами на устаревшем значении: {x_a} -> {x_b}"
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
