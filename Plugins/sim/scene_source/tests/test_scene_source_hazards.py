# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 2.2 + Task 3.4 плана line-sim, ``SceneSourcePlugin``.

Про что acceptance-тесты тестера НЕ проверяют, а механизм ломается ровно тут:
гонка старта процессов (сцена поднялась раньше робота), обе формы дельт в
ОДНОЙ последовательности (не по отдельности), де-дублирование предупреждения о
протухшем значении (не спам на каждый кадр) и конкурентность колбэка подписки
против ``produce()`` (два разных потока пишут/читают ``self._world`` под
одним ``Lock``).

**Правка Task 3.4:** ``SPRITE_BGR`` (константа заглушки) убран из импорта — символа
больше нет, заглушка заменена движком ``line_sim``. Ниже добавлен блок hazard-тестов
Task 3.4: воспроизводимость паспортов по seed+последовательности энкодера, падающая
фабрика не роняет кадровый цикл (де-дублированный лог), ``sim.objects`` пишется
только при смене состава, item без ``sim_truth`` с полным набором ключей.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — см. ``tests/test_scene_source_acceptance.py``."""

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


def _make_plugin(cfg_overrides: dict | None = None):
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": 200,
        **(cfg_overrides or {}),
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


# --------------------------------------------------------------------------- #
# (a) Сцена поднялась раньше робота — гонка старта процессов                  #
# --------------------------------------------------------------------------- #


def test_scene_up_before_robot_multiple_produce_no_exception() -> None:
    """Мир пуст на протяжении НЕСКОЛЬКИХ подряд кадров (не одного, как у
    тестера) — реалистичная гонка: `robot` поднимается на несколько тактов
    позже `camera`. Ни один `produce()` не должен бросить, и кадр остаётся
    валидным на каждом тике."""
    plugin, _ctx, _sp = _make_plugin()
    for _ in range(20):
        items = plugin.produce()
        assert isinstance(items, list) and items
        frame = items[0]["frame"]
        assert frame.shape == (480, 640, 3)


# --------------------------------------------------------------------------- #
# (b) Обе формы дельт В ОДНОЙ последовательности — частичная полистовая       #
#     дельта не должна затирать поля, пришедшие дельтой создания             #
# --------------------------------------------------------------------------- #


def test_creation_then_partial_leaf_update_preserves_untouched_fields() -> None:
    """Дельта-целиком кладёт {value, mm_s, t}; следующая полистовая дельта
    обновляет ТОЛЬКО value/t. Исправлено ревью Task 2.2: полистовая форма НЕ
    приходит от повторного вызова живого паблишера (``state_proxy.set()``
    шлёт словарь целиком КАЖДЫЙ раз — см. докстринг ``plugin.py``); в реальном
    процессе она приходит от РЕПЛЕЯ начального состояния при (пере)подписке
    (``_replay_initial_state``). Тест бьёт по самому объединению в
    ``_on_deltas`` независимо от того, кто прислал полистовую форму: mm_s из
    дельты-целиком не должен пропасть из накопителя после частичного
    полистового апдейта."""
    plugin, ctx, sp = _make_plugin()
    t0 = time.monotonic()
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 0, "mm_s": 50.0, "t": t0},
                source="robot",
            )
        ]
    )
    with plugin._lock:
        assert plugin._world.get("mm_s") == 50.0

    # Полистовая дельта только по value/t — синтетическая имитация формы РЕПЛЕЯ
    # подписки (``_replay_initial_state``), НЕ повторного вызова паблишера
    # (тот шлёт словарь целиком каждый раз, см. докстринг ``plugin.py``).
    sp.emit(
        [
            Delta(path="sim.belt.encoder.value", old_value=0, new_value=100, source="robot"),
            Delta(path="sim.belt.encoder.t", old_value=t0, new_value=t0 + 0.05, source="robot"),
        ]
    )
    with plugin._lock:
        assert plugin._world.get("value") == 100
        assert plugin._world.get("mm_s") == 50.0, "mm_s из дельты создания пропал после частичного полистового апдейта"


# --------------------------------------------------------------------------- #
# (c) Де-дублирование предупреждения — не спам на каждый кадр                #
# --------------------------------------------------------------------------- #


def test_stale_warning_deduplicated_by_t_not_spammed_every_frame() -> None:
    """Одно и то же протухшее ``t`` не должно порождать новое предупреждение
    на КАЖДЫЙ ``produce()`` — иначе лог сима зальётся тысячами строк в
    секунду на длинной паузе публикации. Новое (другое) протухшее ``t`` —
    новое предупреждение."""
    plugin, ctx, sp = _make_plugin()
    stale_t = time.monotonic() - 10.0
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": 0, "mm_s": 0.0, "t": stale_t},
                source="robot",
            )
        ]
    )

    for _ in range(5):
        plugin.produce()
    assert ctx.log_warning.call_count == 1, (
        f"ожидалось ровно 1 предупреждение на неизменном t, получено {ctx.log_warning.call_count}"
    )

    stale_t_2 = stale_t - 1.0
    sp.emit([Delta(path="sim.belt.encoder.t", old_value=stale_t, new_value=stale_t_2, source="robot")])
    plugin.produce()
    assert ctx.log_warning.call_count == 2, "новое протухшее значение должно дать новое предупреждение"


# --------------------------------------------------------------------------- #
# (d) Конкурентность: колбэк подписки (чужой поток) против produce()          #
# --------------------------------------------------------------------------- #


def test_callback_vs_produce_concurrency_no_exception() -> None:
    """``_on_deltas`` в реальном процессе зовётся с потока роутера/подписки,
    ``produce()`` — с потока ``SourceProducer``. Гоняем оба конкурентно на
    ``Lock`` и проверяем отсутствие исключений/дедлока (join с дедлайном —
    зависший поток не должен повесить тест, см. project-rules про hangs)."""
    plugin, _ctx, sp = _make_plugin()
    stop = threading.Event()
    errors: list[BaseException] = []

    def _writer() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            t = time.monotonic()
            try:
                sp.emit(
                    [
                        Delta(path="sim.belt.encoder.value", old_value=None, new_value=i, source="robot"),
                        Delta(path="sim.belt.encoder.t", old_value=None, new_value=t, source="robot"),
                    ]
                )
            except BaseException as exc:  # noqa: BLE001 — хотим увидеть ЛЮБОЙ сбой гонки
                errors.append(exc)
                return

    writer = threading.Thread(target=_writer, daemon=True)
    writer.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                plugin.produce()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                break
    finally:
        stop.set()
        writer.join(timeout=5.0)
        assert not writer.is_alive(), "writer-поток не завершился за 5с — подозрение на дедлок"

    assert not errors, f"конкурентный доступ дал исключение: {errors!r}"


# --------------------------------------------------------------------------- #
# (e) УДАЛЕНО Task 3.4: test_sprite_wraps_past_right_edge_instead_of_parking —  #
# пинило "бесконечную ленту по модулю" заглушки-спрайта (_draw_sprite,         #
# SPRITE_BGR), которой в движке line_sim больше нет: SceneCompositor рисует    #
# на КОНЕЧНОЙ camera_rect, объект, уехавший за край, просто не попадает в      #
# кадр (проверено test_acceptance_3_4.py::test_object_outside_camera_rect_    #
# absent), а деспавн — по scene_length_mm (Task 3.3), а не по модулю периода   #
# кадра. Тест автора (не тестера) — снят вместе со стёртым поведением, не      #
# формально "не трогать" (то правило — про независимого тестера). Ниже —      #
# hazard-тесты автора Task 3.4 (движок в плагине).                            #
# --------------------------------------------------------------------------- #


def _make_fixture_catalog(tmp_path: Path, color_bgr: tuple[int, int, int]) -> Path:
    classes_dir = tmp_path / f"classes_{uuid.uuid4().hex}"
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


def _make_plugin_with_engine(tmp_path: Path, cfg_overrides: dict | None = None):
    catalog_dir = _make_fixture_catalog(tmp_path, (0, 0, 255))
    return _make_plugin(
        {
            "preset_path": str(catalog_dir),
            "spawn_interval_s": [0.01, 0.01],
            "scene_length_mm": 1_000_000.0,
            **(cfg_overrides or {}),
        }
    )


def _push_encoder(sp: _FakeStateProxy, value: int, t: float | None = None) -> None:
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": value, "mm_s": 0.0, "t": time.monotonic() if t is None else t},
                source="robot",
            )
        ]
    )


# --------------------------------------------------------------------------- #
# (f) Воспроизводимость: тот же seed + та же последовательность энкодера ->   #
#     та же последовательность паспортов; другой seed -> другая              #
# --------------------------------------------------------------------------- #


def test_same_seed_and_encoder_sequence_gives_identical_passport_sequence(tmp_path) -> None:
    def _run(seed: int) -> list[tuple[str, float, str | None]]:
        plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"seed": seed})
        _push_encoder(sp, 0)
        passports: list[tuple[str, float, str | None]] = []
        for i in range(8):
            plugin.produce()
            time.sleep(0.02)  # безопасно больше interval_s=0.01 -> спавн почти каждый вызов
            _push_encoder(sp, (i + 1) * 100)
            for obj in plugin._spawner.active_objects():
                p = obj.passport
                passports.append((p.class_name, p.angle_deg, p.defect))
        return passports

    run_a = _run(seed=0)
    run_b = _run(seed=0)
    run_c = _run(seed=1)

    assert run_a, "setup sanity: хотя бы один объект должен был заспавниться"
    assert run_a == run_b, "одинаковый seed + одинаковая последовательность энкодера дали разные паспорта"
    assert run_a != run_c, "разный seed дал ТУ ЖЕ последовательность паспортов — rng не влияет на выбор"


# --------------------------------------------------------------------------- #
# (g) Падающая фабрика не роняет кадровый цикл; лог де-дублирован (<= 1/с)    #
# --------------------------------------------------------------------------- #


def test_always_raising_factory_keeps_frames_coming_and_logs_at_most_once_per_second(tmp_path, monkeypatch) -> None:
    plugin, ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_interval_s": [1e-6, 1e-6]})

    def _boom(*_args, **_kwargs):
        raise RuntimeError("каталог моргнул")

    monkeypatch.setattr(plugin._spawner._factory, "make", _boom)
    _push_encoder(sp, 0)

    for _ in range(10):
        items = plugin.produce()
        assert isinstance(items, list) and items and isinstance(items[0]["frame"], np.ndarray)

    assert ctx.log_error.call_count <= 1, (
        f"падающая фабрика залила лог: {ctx.log_error.call_count} вызовов log_error за 10 кадров без sleep"
    )


# --------------------------------------------------------------------------- #
# (h) sim.objects пишется ТОЛЬКО при смене состава активных id                #
# --------------------------------------------------------------------------- #


def test_sim_objects_published_only_on_membership_change(tmp_path) -> None:
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_interval_s": [1.0, 1.0]})
    t0 = time.monotonic()
    _push_encoder(sp, 0, t=t0)

    plugin.produce()  # tick #1 — только взводит срок, объект не создан, set() не зовётся
    assert sp.set_calls == []

    time.sleep(1.2)
    plugin.produce()  # tick #2 — спавнит ровно один объект -> состав ИЗМЕНИЛСЯ -> ровно один set()
    assert len(sp.set_calls) == 1
    path, payload = sp.set_calls[0]
    assert path == "sim.objects"
    assert len(payload) == 1

    for _ in range(5):
        plugin.produce()  # interval=1с, эти вызовы быстрые -> состав не меняется -> set() не зовётся
    assert len(sp.set_calls) == 1, f"sim.objects переписан без смены состава: {len(sp.set_calls)} вызовов set()"


# --------------------------------------------------------------------------- #
# (i) item без sim_truth, все обязательные ключи на месте (с движком)         #
# --------------------------------------------------------------------------- #


def test_item_has_no_sim_truth_and_all_required_keys(tmp_path) -> None:
    """`item` не содержит `sim_truth` (принцип «паспорта едут в мир, не на кадре»,
    ред. 2 плана) и несёт весь набор ключей из acceptance-критерия 4 плана, включая
    `camera_id` (фикс ревью P4 — раньше отсутствовал, тест был написан вокруг
    пропуска вместо того, чтобы его закрыть)."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 0)
    item = plugin.produce()[0]

    assert "sim_truth" not in item
    for key in ("frame", "camera_id", "seq_id", "frame_id", "timestamp", "width", "height", "channels", "dtype"):
        assert key in item, f"обязательный ключ {key!r} отсутствует в item: {sorted(item)}"


# --------------------------------------------------------------------------- #
# (j) Фикс ревью P5: fallback-ветка (без preset_path) должна отдавать кадр в  #
# ТОМ ЖЕ порядке каналов, что движок, и логировать ошибку сборки РОВНО один   #
# раз (не на каждый produce())                                               #
# --------------------------------------------------------------------------- #


def test_fallback_branch_logs_once_and_frame_matches_background_bgr(monkeypatch) -> None:
    """Repro ревью: цвет фона несимметричен по каналам (`(200, 10, 30)` вместо
    дефолтного серого `(60, 60, 60)`, который маскировал баг) — до фикса
    `_background_only_frame()` строила BGR и `produce()` переставляла каналы ЕЩЁ
    РАЗ через `cv2.COLOR_RGB2BGR`, отдавая `[30, 10, 200]` вместо `[200, 10, 30]`.
    Плюс: `configure()` без `preset_path` логирует ОДИН error, дальнейшие 5
    `produce()` кадры не роняют и лог не повторяют."""
    import Plugins.sim.scene_source.plugin as plugin_module

    monkeypatch.setattr(plugin_module, "_BACKGROUND_BGR", (200, 10, 30))
    plugin, ctx, _sp = _make_plugin()  # без preset_path в cfg -> движок недоступен
    assert ctx.log_error.call_count == 1, (
        f"configure() без preset_path должен логировать ровно 1 error: {ctx.log_error.call_args_list}"
    )

    for _ in range(5):
        item = plugin.produce()[0]
        assert isinstance(item["frame"], np.ndarray)
        assert tuple(int(v) for v in item["frame"][0, 0]) == (200, 10, 30), (
            f"item['frame'][0,0]={tuple(int(v) for v in item['frame'][0, 0])} != _BACKGROUND_BGR=(200,10,30)"
        )
    assert ctx.log_error.call_count == 1, "fallback-ветка не должна логировать ошибку повторно на каждый produce()"


# --------------------------------------------------------------------------- #
# (k) Закрытие инъекций лида Q3/Q4 (Task 3.4): обе правки ревью пережили      #
# поломку кода на всём наборе тестов — свойства были заявлены в README и      #
# докстрингах, но не закреплены ни одним тестом                               #
# --------------------------------------------------------------------------- #


def test_camera_id_comes_from_config_not_hardcoded_default(tmp_path) -> None:
    """Инъекция Q3: `self._camera_id = _DEFAULT_CAMERA_ID` (конфиг проигнорирован)
    не уронила ни одного теста — проверка ключа `camera_id` в item требовала лишь
    НАЛИЧИЯ ключа, а дефолт 0 совпадал с ожиданием. Стенд с двумя камерами получил
    бы оба потока под `camera_id=0` и молча склеил их."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, cfg_overrides={"camera_id": 7})
    _push_encoder(sp, 0)
    assert plugin.produce()[0]["camera_id"] == 7


def test_relative_preset_path_resolves_from_repo_root_not_cwd(tmp_path, monkeypatch) -> None:
    """Инъекция Q4: `return preset_path` (резолюция от корня репо убрана) не уронила
    ничего — все тесты движка передают АБСОЛЮТНЫЙ `tmp_path`, а живой стенд ловил
    ровно этот баг: относительный `preset_path` из `pipeline.yaml` резолвился против
    CWD процесса, и движок молча уходил в fallback на фон."""
    from Plugins.sim.scene_source.plugin import _REPO_ROOT

    expected = str((_REPO_ROOT / "data/line_sim/demo_catalog").resolve())
    monkeypatch.chdir(tmp_path)
    assert SceneSourcePlugin._resolve_preset_path("data/line_sim/demo_catalog") == expected
    assert SceneSourcePlugin._resolve_preset_path(None) is None
    assert SceneSourcePlugin._resolve_preset_path(str(tmp_path)) == str(tmp_path)
