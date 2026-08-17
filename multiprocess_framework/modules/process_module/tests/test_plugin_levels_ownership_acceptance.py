# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.5-fix — владение именем уровня (ADR-PM-038, W-1).

Источник контракта: критерии П1-П11 из ТЗ тестера (не реализация фикса — она ещё
не существует; `heartbeat/process_heartbeat.py` и `heartbeat/telemetry.py` читались
ТОЛЬКО как библиотека для сборки боевого стенда, ровно как это уже делают соседние
тесты модуля, например test_telemetry_levels_poll_acceptance.py).

Стенд — БОЕВАЯ ДОРОГА, а не собранный руками контекст: PluginContext создаётся
конструктором фреймворка (`PluginContext(services).with_config(..., plugin_name=...)`),
``ProcessHeartbeat`` — тот же класс, что несёт тик в проде, и получает ТУ ЖЕ ссылку
на объект сервисов, что и PluginContext (иначе хранилище уровней разъехалось бы —
ровно тот класс дефекта, что нашла независимая проверка в модульном докстринге
project CLAUDE.md: «тест собирал контекст вручную и не трогал реальный конструктор»).
Единственная ручная точка — ``_state_proxy``/``router`` на дальней границе (IPC к
StateStoreManager) и ``FakeClock``/``FakeStop`` для форсирования РОВНО одного тика
без ``time.sleep`` — тот же приём, что в test_telemetry_levels_poll_acceptance.py.

П10 — единственный критерий не про плагинные уровни, а про сам механизм
``StateStoreManager.merge`` (на нём будет держаться П4-рефакторинг «1 merge вместо
3»): стенд для него — настоящий ``StateStoreManager`` + ``SubscriptionManager`` +
``DeltaDispatcher`` без плагинного слоя (``InMemoryRouter`` из
``state_store_module/testing`` оказался сломан для этого случая — эмпирически
проверено: ``send_async`` резолвит хендлер по ``message["type"]`` (всегда
``"command"``), а не по ``message["command"]``, поэтому ``state.merge`` через него
не долетает вовсе; это баг соседнего модуля вне области задачи, обойдён прямым
вызовом ``StateStoreManager.handle_state_merge`` — той же точки входа, в которую
``InMemoryRouter`` целился бы, будь он исправен).

П11 отдельного теста не получил: «отбор по каталогу заменяется, а не дополняется
проверкой владельца» и «второй/третий merge исчезает» — это те же наблюдаемые
свойства, что уже сторожат П1 (чужое имя не побеждает) и П4 (ровно один merge);
отдельный тест на «в коде не осталось строки X» проверял бы форму, а не поведение
(тот же довод, что у «спай на имени API» в project CLAUDE.md).

Предсказания ДО прогона (RED — новое поведение, реализации нет; GREEN — существующее
свойство Task 3.5, фикс обязан его не сломать):

    П1  test_forged_framework_owned_fps_never_wins_the_tree              RED
    П1  test_forged_value_absent_from_every_merge_not_just_the_final_tree RED
    П2  test_never_declared_name_absent_from_every_merge                 GREEN
    П2  test_never_declared_name_absent_from_poll_too                    GREEN
    П2  test_warning_fires_once_and_names_the_metric                     GREEN
    П2  test_warning_names_the_publishing_plugin                         RED
    П2  test_second_tick_same_undeclared_name_stays_silent               GREEN
    П3  test_made_up_name_reaches_the_tree                               GREEN
    П3  test_made_up_name_reaches_the_poll                               GREEN
    П4  test_zero_data_gives_zero_merges                                 GREEN
    П4  test_worker_shm_and_plugin_level_together_produce_exactly_one_merge RED
    П5  test_disabled_plugin_level_excluded_from_payload                 GREEN
    П5  test_all_metrics_disabled_sends_zero_merges                      GREEN
    П5  test_poll_ignores_gate_for_plugin_level                          GREEN
    П6  test_stopped_plugin_level_vanishes_next_tick_sibling_survives    RED
    П6  test_stopped_plugin_level_vanishes_from_poll_sibling_survives    RED
    П7  test_plugin_level_matches_between_push_and_poll                  GREEN
    П8  test_capture_plugin_publishes_under_its_own_name_not_fps         RED
    П8  test_capture_measured_rate_does_not_win_the_tree_fps             RED
    П9  test_forbidden_application_metric_names_absent_from_framework_code GREEN
    П10 test_one_merge_of_ten_leaves_matches_ten_separate_merges         GREEN

Расхождение предсказания с фактом (если возникнет на прогоне) — находка, называется
в отчёте, а не тихо переписывается тестом под факт.
"""

from __future__ import annotations

import ast
import pathlib
import threading

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declared_metrics,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.state_store_module.core.delta import (
    STATE_ENVELOPE_MARKER,
)
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
    StateStoreManager,
)

# CapturePlugin — реальный прикладной плагин, а не синтетика: П8 сторожит его
# сегодняшнее поведение (Plugins/sources/capture/plugin.py:352 публикует "fps"
# без объявления, полагаясь на порядок наложения — ровно тот дефект, который
# П1 обязан запретить).
from Plugins.sources.capture.plugin import CapturePlugin


# --------------------------------------------------------------------------- #
# Часы и стоп-событие для форсирования ровно ОДНОГО тика (без time.sleep) —
# образец test_telemetry_levels_poll_acceptance.py / test_telemetry_tick.py.
# --------------------------------------------------------------------------- #
class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class FakeStop:
    def __init__(self, clock: FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout=None) -> None:
        self._clock.advance(timeout)


class _NoPauseEvent:
    def is_set(self) -> bool:
        return False


def _tick(hb: ProcessHeartbeat, clock: FakeClock, dt: float = 0.01, timeout: float = 5.0) -> None:
    """Форсировать РОВНО один тик heartbeat в daemon-потоке с дедлайном join.

    Тик детерминирован (FakeClock, без реального sleep/IO) — зависнуть ему
    неоткуда, но правило «тест не имеет права зависнуть» соблюдается буквально,
    а не «по факту, что сегодня не виснет».
    """
    t_end = clock.t + dt
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            hb._loop(FakeStop(clock, t_end), _NoPauseEvent())
        except BaseException as exc:  # noqa: BLE001 — пробросить в основной поток ниже
            errors.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        pytest.fail(f"heartbeat-тик завис дольше {timeout}с")
    if errors:
        raise errors[0]


# --------------------------------------------------------------------------- #
# Фейковые сервисы процесса — ОДИН объект видят и PluginContext, и
# ProcessHeartbeat (иначе хранилище уровней разъезжается — см. докстринг модуля).
# --------------------------------------------------------------------------- #
class _WorkerManager:
    def __init__(self, workers: dict) -> None:
        self._workers = workers

    def get_all_workers_status(self) -> dict:
        return {w: dict(v) for w, v in self._workers.items()}


class _RecordingProxy:
    """Дальняя граница (IPC к StateStoreManager) — считает и запоминает merge."""

    def __init__(self) -> None:
        self.merge_calls = 0
        self.merged: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self.merged.append((path, dict(data)))

    def set(self, path: str, value: object) -> None:  # noqa: D401 — не используется в этих тестах
        pass


class _Router:
    """Ненулевые SHM-счётчики — чтобы группа ``shm`` реально участвовала в тике."""

    def get_shm_stats(self) -> dict:
        return {"frame_pickle_fallbacks": 3}


class _Services:
    """Сервисы процесса — то, что видят и PluginContext, и ProcessHeartbeat.

    Пятёрка ``log_*`` — ПРЯМЫЕ атрибуты (PluginContext читает их без getattr).
    ``state_proxy`` (публичное) и ``_state_proxy`` (приватное) — ОДИН и тот же
    объект: PluginContext.__init__ читает первое, ProcessHeartbeat — второе.
    """

    def __init__(self, name: str = "proc", workers: dict | None = None, proxy: object | None = None) -> None:
        self.name = name
        self.worker_manager = _WorkerManager(workers) if workers is not None else None
        self._state_proxy = proxy if proxy is not None else _RecordingProxy()
        self.state_proxy = self._state_proxy
        self.router_manager: object | None = None
        self.memory_manager: object | None = None
        self.command_manager: object | None = None
        self._health_state = None
        self._current_process_status = "running"
        self._config: dict = {}
        self.logs: list[dict] = []

    def get_config(self, key: str, default: object = None) -> object:
        return self._config.get(key, default)

    def _record(self, level: str, msg: str, kwargs: dict) -> None:
        entry = {"level": level, "msg": msg}
        entry.update(kwargs)
        self.logs.append(entry)

    def log_debug(self, msg: str, **kw) -> None:
        self._record("DEBUG", msg, kw)

    def log_info(self, msg: str, **kw) -> None:
        self._record("INFO", msg, kw)

    def log_warning(self, msg: str, **kw) -> None:
        self._record("WARNING", msg, kw)

    def log_error(self, msg: str, **kw) -> None:
        self._record("ERROR", msg, kw)

    def log_critical(self, msg: str, **kw) -> None:
        self._record("CRITICAL", msg, kw)

    def send_message(self, target: str, message: dict) -> bool:
        return True

    def receive_message(self, timeout: float | None = None) -> dict | None:
        return None


def _warning_entries(svc: _Services) -> list[dict]:
    return [e for e in svc.logs if e["level"] == "WARNING"]


def _plugin_ctx(services: _Services, plugin_name: str) -> PluginContext:
    base = PluginContext(services=services)
    return base.with_config({}, plugin_name=plugin_name)


def _running_worker(hz: float = 23.7, lat: float = 41.3, name: str = "w0") -> dict:
    return {name: {"status": "running", "effective_hz": hz, "cycle_duration_ms": lat}}


def _flatten_keys(obj: object, out: set | None = None) -> set:
    """Собрать ВСЕ ключи произвольно вложенного dict — для проверки «имени нет
    нигде в payload'е», а не только в одной заранее угаданной позиции."""
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _flatten_keys(v, out)
    return out


def _deep_merge_into(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_into(dst[k], v)
        else:
            dst[k] = v


def _apply_merges(merges: list[tuple[str, dict]]) -> dict:
    """Свести упорядоченный список ``proxy.merge`` вызовов в ИТОГОВОЕ дерево —
    та же логика глубокого merge по dot-пути, что у настоящего StateStoreManager
    (см. TestP10 — там она же проверена на реальном движке)."""
    tree: dict = {}
    for path, data in merges:
        node = tree
        for part in path.split("."):
            node = node.setdefault(part, {})
        _deep_merge_into(node, data)
    return tree


def _get_path(tree: dict, dotted: str) -> object:
    node = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@pytest.fixture
def declared_names():
    """Имена, объявленные тестом через ctx.declare_metric — забываются поимённо
    в teardown (project CLAUDE.md: сплошная очистка ломает каталог соседям)."""
    names: list[str] = []
    yield names
    if names:
        forget_declarations(KIND_METRIC, names=names)


# --------------------------------------------------------------------------- #
# П1 — чужое имя не публикуется НИКОГДА (побеждает владелец)
# --------------------------------------------------------------------------- #
class TestP1ForeignNameNeverWins:
    """Плагин публикует "fps" (владелец — фреймворк, объявлен в heartbeat/telemetry.py)
    БЕЗ declare_metric (declare для чужого имени — ValueError реестра; publish_metric
    объявления не требует — см. plugins/base.py). Свойство: значение владельца в
    дереве не подменяется НИ ПРИ КАКИХ обстоятельствах, судим ЗНАЧЕНИЕМ."""

    def test_forged_framework_owned_fps_never_wins_the_tree(self) -> None:
        workers = _running_worker(hz=23.7)
        svc = _Services(name="camF", workers=workers)
        ctx = _plugin_ctx(svc, "forger_plugin")
        ctx.publish_metric("fps", 999.9)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        final_fps = _get_path(tree, "processes.camF.state.fps")
        assert final_fps == pytest.approx(23.7), (
            f"владелец 'fps' — фреймворк (агрегат воркеров 23.7), а в дереве {final_fps!r}"
        )

    def test_forged_value_absent_from_every_merge_not_just_the_final_tree(self) -> None:
        """«Никогда» — это про каждый отдельный merge за тик, не только про итог."""
        workers = _running_worker(hz=23.7)
        svc = _Services(name="camF2", workers=workers)
        ctx = _plugin_ctx(svc, "forger_plugin")
        ctx.publish_metric("fps", 999.9)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        for path, data in svc._state_proxy.merged:
            fps_here = data.get("fps")
            if fps_here is None and isinstance(data.get("state"), dict):
                fps_here = data["state"].get("fps")
            assert fps_here != pytest.approx(999.9), (path, data)


# --------------------------------------------------------------------------- #
# П2 — необъявленное не публикуется, и об этом слышно (один раз, с именами)
# --------------------------------------------------------------------------- #
class TestP2UndeclaredLevelNeverPublished:
    def test_never_declared_name_absent_from_every_merge(self) -> None:
        svc = _Services(name="procU1")
        ctx = _plugin_ctx(svc, "orphan_plugin")
        ctx.publish_metric("mystery_level", 7.5)  # никогда и никем не объявлено

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        for _path, data in svc._state_proxy.merged:
            assert "mystery_level" not in _flatten_keys(data)

    def test_never_declared_name_absent_from_poll_too(self) -> None:
        svc = _Services(name="procU2")
        ctx = _plugin_ctx(svc, "orphan_plugin")
        ctx.publish_metric("mystery_level", 7.5)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot() or {}
        assert "mystery_level" not in _flatten_keys(snap.get("state", {}))

    def test_warning_fires_once_and_names_the_metric(self) -> None:
        svc = _Services(name="procU3")
        ctx = _plugin_ctx(svc, "orphan_plugin")
        ctx.publish_metric("mystery_level", 7.5)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        hits = [e for e in _warning_entries(svc) if "mystery_level" in e["msg"]]
        assert len(hits) == 1, svc.logs

    def test_warning_names_the_publishing_plugin(self) -> None:
        """Критерий: «в нём названы имя И публикатор». Сегодня ``PluginLevels``
        хранит ТОЛЬКО значение (``dict[name] = value``), без автора — предупреждение
        физически не может назвать плагин, которого не помнит."""
        svc = _Services(name="procU4")
        ctx = _plugin_ctx(svc, "orphan_plugin")
        ctx.publish_metric("mystery_level", 7.5)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        hits = [e for e in _warning_entries(svc) if "mystery_level" in e["msg"]]
        assert hits, "должно быть хотя бы одно предупреждение про mystery_level"
        entry = hits[0]
        named = "orphan_plugin" in entry["msg"] or entry.get("module") == "orphan_plugin"
        assert named, entry

    def test_second_tick_same_undeclared_name_stays_silent(self) -> None:
        svc = _Services(name="procU5")
        ctx = _plugin_ctx(svc, "orphan_plugin")
        ctx.publish_metric("mystery_level", 7.5)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)
        first_hits = [e for e in _warning_entries(svc) if "mystery_level" in e["msg"]]
        assert len(first_hits) == 1

        before = len(svc.logs)
        ctx.publish_metric("mystery_level", 7.6)
        _tick(hb, clock)
        new_hits = [e for e in svc.logs[before:] if e["level"] == "WARNING" and "mystery_level" in e["msg"]]
        assert new_hits == []


# --------------------------------------------------------------------------- #
# П3 — универсальность: выдуманное имя доезжает и в дерево, и в опрос
# --------------------------------------------------------------------------- #
class TestP3UniversalityMadeUpName:
    def test_made_up_name_reaches_the_tree(self, declared_names) -> None:
        NAME = "zzz_made_up_level"
        svc = _Services(name="procN1")
        ctx = _plugin_ctx(svc, "novel_plugin")
        assert ctx.declare_metric(NAME) == NAME
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 12.3)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        assert _get_path(tree, f"processes.procN1.state.{NAME}") == pytest.approx(12.3)

    def test_made_up_name_reaches_the_poll(self, declared_names) -> None:
        NAME = "zzz_made_up_level"
        svc = _Services(name="procN2")
        ctx = _plugin_ctx(svc, "novel_plugin")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 12.3)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot()
        assert snap is not None
        assert snap.get("state", {}).get(NAME) == pytest.approx(12.3)


# --------------------------------------------------------------------------- #
# П4 — ОДИН merge на тик (сегодня их три)
# --------------------------------------------------------------------------- #
class TestP4ExactlyOneMergePerTick:
    def test_zero_data_gives_zero_merges(self) -> None:
        svc = _Services(name="procZ")  # без воркеров, без роутера, без уровней
        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)
        assert svc._state_proxy.merge_calls == 0

    def test_worker_shm_and_plugin_level_together_produce_exactly_one_merge(self, declared_names) -> None:
        NAME = "combined_level"
        workers = _running_worker(hz=23.7)
        svc = _Services(name="procM", workers=workers)
        svc.router_manager = _Router()  # ненулевые shm-счётчики — группа участвует
        ctx = _plugin_ctx(svc, "combo_plugin")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 3.3)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        assert svc._state_proxy.merge_calls == 1, svc._state_proxy.merged


# --------------------------------------------------------------------------- #
# П5 — гейт накрывает единый payload; опрос гейту НЕ подчиняется (уже так, Task 3.5)
# --------------------------------------------------------------------------- #
class TestP5GateCoversUnifiedPayload:
    def test_disabled_plugin_level_excluded_from_payload(self, declared_names) -> None:
        NAME = "gated_level_a"
        workers = _running_worker(hz=23.7)
        svc = _Services(name="procG1", workers=workers)
        ctx = _plugin_ctx(svc, "gated_plugin_a")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 5.5)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        hb.reconfigure_telemetry({"metrics": {NAME: {"enabled": False}}})
        _tick(hb, clock)

        for _path, data in svc._state_proxy.merged:
            assert NAME not in _flatten_keys(data)

    def test_all_metrics_disabled_sends_zero_merges(self, declared_names) -> None:
        """Без воркеров: ``status`` воркера гейту не подчиняется НАМЕРЕННО
        (инвариант «errors/status always-on» — ADR-PM-035/PC 1.2, публикуется
        ВНЕ гейта даже когда всё остальное выключено), поэтому сценарий «истинно
        нулевой трафик» проверяется без него — иначе тест мерил бы чужой,
        уже названный инвариант, а не гейтируемость уровня плагина."""
        NAME = "gated_level_b"
        svc = _Services(name="procG2")
        ctx = _plugin_ctx(svc, "gated_plugin_b")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 5.5)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        disable_all = {n: {"enabled": False} for n in declared_metrics()}
        hb.reconfigure_telemetry({"metrics": disable_all})
        _tick(hb, clock)
        assert svc._state_proxy.merge_calls == 0

    def test_poll_ignores_gate_for_plugin_level(self, declared_names) -> None:
        NAME = "gated_level_c"
        svc = _Services(name="procG3")
        ctx = _plugin_ctx(svc, "gated_plugin_c")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 5.5)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        hb.reconfigure_telemetry({"metrics": {NAME: {"enabled": False}}})
        snap = hb.current_levels_snapshot()
        assert snap is not None
        assert snap.get("state", {}).get(NAME) == pytest.approx(5.5)


# --------------------------------------------------------------------------- #
# П6 — свежесть жизненным циклом: STOPPED убирает уровни, сосед остаётся
# --------------------------------------------------------------------------- #
class _MinimalPlugin(ProcessModulePlugin):
    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        pass


class TestP6LifecycleFreshness:
    def test_stopped_plugin_level_vanishes_next_tick_sibling_survives(self, declared_names) -> None:
        NAME_A, NAME_B = "life_level_a", "life_level_b"
        svc = _Services(name="procL1")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="plugin_a")
        ctx_b = base_ctx.with_config({}, plugin_name="plugin_b")

        ctx_a.declare_metric(NAME_A)
        ctx_b.declare_metric(NAME_B)
        declared_names.extend([NAME_A, NAME_B])
        ctx_a.publish_metric(NAME_A, 1.1)
        ctx_b.publish_metric(NAME_B, 2.2)

        plugin_a = _MinimalPlugin()
        plugin_a.name = "plugin_a"
        plugin_a._do_configure(ctx_a)
        plugin_a._do_shutdown(ctx_a)
        assert plugin_a.state == PluginState.STOPPED

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        state = _get_path(tree, "processes.procL1.state") or {}
        assert NAME_A not in state, state
        assert state.get(NAME_B) == pytest.approx(2.2), state

    def test_stopped_plugin_level_vanishes_from_poll_sibling_survives(self, declared_names) -> None:
        NAME_A, NAME_B = "life_level_c", "life_level_d"
        svc = _Services(name="procL2")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="plugin_a2")
        ctx_b = base_ctx.with_config({}, plugin_name="plugin_b2")

        ctx_a.declare_metric(NAME_A)
        ctx_b.declare_metric(NAME_B)
        declared_names.extend([NAME_A, NAME_B])
        ctx_a.publish_metric(NAME_A, 1.1)
        ctx_b.publish_metric(NAME_B, 2.2)

        plugin_a = _MinimalPlugin()
        plugin_a.name = "plugin_a2"
        plugin_a._do_configure(ctx_a)
        plugin_a._do_shutdown(ctx_a)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot() or {}
        state = snap.get("state", {})
        assert NAME_A not in state, state
        assert state.get(NAME_B) == pytest.approx(2.2), state


# --------------------------------------------------------------------------- #
# П7 — push и poll не расходятся (при открытом гейте)
# --------------------------------------------------------------------------- #
class TestP7PushPollAgree:
    def test_plugin_level_matches_between_push_and_poll(self, declared_names) -> None:
        NAME = "agree_level"
        workers = _running_worker(hz=15.5, lat=9.9)
        svc = _Services(name="procA1", workers=workers)
        ctx = _plugin_ctx(svc, "agree_plugin")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 8.8)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        pushed = _get_path(tree, f"processes.procA1.state.{NAME}")
        snap = hb.current_levels_snapshot() or {}
        polled = snap.get("state", {}).get(NAME)

        assert pushed == polled == pytest.approx(8.8)


# --------------------------------------------------------------------------- #
# П8 — CapturePlugin не владеет "fps"; измеренная частота едет как "capture_fps"
# --------------------------------------------------------------------------- #
class TestP8CaptureDoesNotOwnFrameworkNames:
    """Единственный класс файла, поднимающий НАСТОЯЩИЙ плагин, — и потому
    единственный, чей ``configure`` объявляет имена мимо фикстуры ``declared_names``.

    Уборка обязательна и не косметическая: реестр объявлений процессный и общий на
    весь прогон, поэтому оставленные `capture_fps`/`frame_count`/`drops` с владельцем
    ``capture`` роняли соседний ``Plugins/sources/capture/tests/test_plugin.py`` —
    но ТОЛЬКО в полном прогоне, поодиночке оба файла зелены. Класс «второй
    потребитель вскрывает дефект общего состояния»; найдено исполнителем как
    «девятый красный в базе», которого не было в отчёте автора этих тестов.

    Забываем ПОИМЁННО: сплошная очистка плоскости не восстановима — производители
    метрик уже импортированы, и объявить их заново некому.
    """

    @pytest.fixture(autouse=True)
    def _forget_capture_declarations(self):
        yield
        forget_declarations(KIND_METRIC, names=("capture_fps", "frame_count", "drops"))

    def test_capture_plugin_publishes_under_its_own_name_not_fps(self) -> None:
        svc = _Services(name="camera_0")
        ctx = _plugin_ctx(svc, "capture")
        plugin = CapturePlugin()
        plugin.configure(ctx)  # реальный configure(): не открывает камеру
        plugin._actual_fps = 42.5
        plugin._frame_count = 100
        plugin._drops = 3
        plugin._publish_levels()  # реальный метод, публикующий уровни камеры

        store = getattr(svc, PLUGIN_LEVELS_ATTR, None)
        snapshot = store.snapshot() if store is not None else {}
        assert "fps" not in snapshot, snapshot
        assert snapshot.get("capture_fps") == pytest.approx(42.5), snapshot

    def test_capture_measured_rate_does_not_win_the_tree_fps(self) -> None:
        workers = _running_worker(hz=21.0)
        svc = _Services(name="camera_1", workers=workers)
        ctx = _plugin_ctx(svc, "capture")
        plugin = CapturePlugin()
        plugin.configure(ctx)
        plugin._actual_fps = 42.5
        plugin._publish_levels()

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        state = _get_path(tree, "processes.camera_1.state") or {}
        assert state.get("fps") == pytest.approx(21.0), state
        assert state.get("capture_fps") == pytest.approx(42.5), state


# --------------------------------------------------------------------------- #
# П9 — прикладных имён во фреймворке ноль (положительное AST-свойство, не grep)
# --------------------------------------------------------------------------- #
_FORBIDDEN_APPLICATION_NAMES = {"frame_count", "drops", "capture_fps"}


def _iter_framework_source_files():
    root = pathlib.Path(__file__).resolve().parents[3]  # .../multiprocess_framework
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        yield path


def _code_identifiers_and_strings(path: pathlib.Path) -> tuple[set, set]:
    """Идентификаторы и строковые литералы КОДА — БЕЗ докстрингов (документация
    исключается по AST-роли — «первый Expr(Constant(str)) в теле модуля/класса/
    функции», а не по regex/эвристике над текстом строки)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_ids.add(id(body[0].value))

    identifiers: set = set()
    strings: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.arg):
            identifiers.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            identifiers.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue  # документация, не код
            strings.add(node.value)
    return identifiers, strings


class TestP9NoApplicationNamesInFrameworkCode:
    def test_forbidden_application_metric_names_absent_from_framework_code(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in _iter_framework_source_files():
            try:
                identifiers, strings = _code_identifiers_and_strings(path)
            except SyntaxError:
                continue
            for name in _FORBIDDEN_APPLICATION_NAMES:
                if name in identifiers or name in strings:
                    offenders.append((str(path), name))
        assert offenders == []


# --------------------------------------------------------------------------- #
# П10 — один укрупнённый merge даёт те же per-leaf дельты, что N раздельных
# --------------------------------------------------------------------------- #
class _CapturingRouter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        self.sent.append(msg)

    def register_message_handler(self, key, handler, expects_full_message=True) -> None:
        pass


def _leaf_deltas_for(router: _CapturingRouter, subscriber: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for msg in router.sent:
        if msg.get("targets") == [subscriber]:
            for d in msg["data"]["deltas"]:
                out.append((d["path"], d["new_value"]))
    return out


def _merge_direct(mgr: StateStoreManager, path: str, data: dict, source: str) -> dict:
    """Вызвать handle_state_merge НАПРЯМУЮ — та же точка входа, в которую бил бы
    IPC-конверт StateProxy.merge (см. докстринг модуля про сломанный InMemoryRouter)."""
    msg = {"path": path, "data": data, "source": source, STATE_ENVELOPE_MARKER: True}
    return mgr.handle_state_merge(msg)


class TestP10SingleMergeMatchesSeparateMerges:
    def test_one_merge_of_ten_leaves_matches_ten_separate_merges(self) -> None:
        leaves = {
            "fps": 10.0,
            "latency_ms": 5.0,
            "effective_hz": 12.0,
            "cycle_duration_ms": 7.0,
            "l1": 1.0,
            "l2": 2.0,
            "l3": 3.0,
            "l4": 4.0,
            "l5": 5.0,
            "l6": 6.0,
        }
        assert len(leaves) == 10
        path = "processes.camX.state"
        expected = sorted((f"{path}.{k}", v) for k, v in leaves.items())

        # Сценарий А: один merge с десятью листьями.
        # try/finally + shutdown() обязателен: autouse-фикстура conftest.py
        # (_no_leaked_state_flushers) роняет ЛЮБОЙ тест, оставивший поток
        # StateCoalesceFlusher живым после initialize() без парного shutdown().
        router_a = _CapturingRouter()
        mgr_a = StateStoreManager(router=router_a)
        mgr_a.initialize()
        try:
            mgr_a.subscription_manager.subscribe("processes.camX.state.**", "watcher")
            result = _merge_direct(mgr_a, path, dict(leaves), "hbA")
            assert result["status"] == "ok"
            mgr_a.dispatcher._flush_once()
            deltas_a = sorted(_leaf_deltas_for(router_a, "watcher"))
        finally:
            mgr_a.shutdown()

        # Сценарий Б: три отдельных merge с теми же листьями (произвольная разбивка).
        items = list(leaves.items())
        groups = [items[0:3], items[3:7], items[7:10]]
        router_b = _CapturingRouter()
        mgr_b = StateStoreManager(router=router_b)
        mgr_b.initialize()
        try:
            mgr_b.subscription_manager.subscribe("processes.camX.state.**", "watcher")
            for i, group in enumerate(groups):
                r = _merge_direct(mgr_b, path, dict(group), f"hbB{i}")
                assert r["status"] == "ok"
                mgr_b.dispatcher._flush_once()
            deltas_b = sorted(_leaf_deltas_for(router_b, "watcher"))
        finally:
            mgr_b.shutdown()

        assert deltas_a == expected, deltas_a
        assert deltas_b == expected, deltas_b
        assert deltas_a == deltas_b
