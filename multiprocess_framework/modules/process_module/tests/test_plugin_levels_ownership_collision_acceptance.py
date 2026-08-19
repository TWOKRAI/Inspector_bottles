# -*- coding: utf-8 -*-
"""Независимая приёмка S-8 — владение именем уровня при столкновении ДВУХ ПЛАГИНОВ.

Источник контракта: критерии О1-О7 из брифа тестера (не реализация — реализацию
этого файла запрещено читать; см. список запрещённых путей ниже). Заявленное
правило, которое сторожит этот файл: лист берётся по ВЛАДЕНИЮ именем (кто вызвал
``ctx.declare_metric``), а не по факту наличия имени в общем каталоге объявлений
и не по порядку наложения merge'ей за тик.

Предыдущая независимая приёмка (``test_plugin_levels_ownership_acceptance.py``,
критерий П1) сторожила только случай «плагин против ФРЕЙМВОРКА» — там framework
кладёт своё значение поверх подделки на том же тике, и такой тест зелен даже без
проверки владения: подмену закрывает порядок наложения, а не правило. Этот файл
добавляет сторожей на случай, где накладывать поверх НЕЧЕГО: два ПРИКЛАДНЫХ
плагина (ни один — framework), и случай, где заявленный владелец на тике МОЛЧИТ.

Стенд собран по образцу ``test_plugin_levels_ownership_acceptance.py`` (этот файл
разрешено было читать и переиспользовать по брифу): ``PluginContext`` создаётся
конструктором фреймворка (``PluginContext(services).with_config(...)``),
``ProcessHeartbeat`` — тот же класс, что несёт тик в проде, и получает ТУ ЖЕ
ссылку на объект сервисов, что и контекст плагина (иначе хранилище уровней
разъехалось бы). Ручные точки — ``_state_proxy``/``router`` (дальняя граница,
IPC к StateStoreManager) и ``FakeClock``/``FakeStop`` для форсирования ровно
одного тика без ``time.sleep``.

Запрещено читать (соблюдено буквально, значения ниже — из имеющегося доступа к
``test_plugin_levels_ownership_acceptance.py`` и открытых сигнатур, а не из
реализации механизма владения):
    - heartbeat/telemetry.py
    - heartbeat/process_heartbeat.py
    - докстринги declare_metric / publish_metric в plugins/base.py
    - test_plugin_levels_hazards.py, test_plugin_levels_acceptance.py (авторские)
    - DECISIONS.md, README.md модуля
    - plans/telemetry-stage6.md, plans/QUEUE.md
    - git diff/log/show — не звался

Предсказания ДО первого прогона. Бриф утверждает: «механизм, по имеющимся
сведениям, свойства уже держит» — то есть ожидаемая картина зелёная по всем
критериям. Особо неопределённый критерий — О5: предыдущая независимая приёмка
(её П2, test_warning_names_the_publishing_plugin) на МОМЕНТ своего написания
была помечена RED, потому что тогдашнее хранилище уровней помнило только
значение, без автора, и предупреждение физически не могло назвать ни
публикатора, ни тем более владельца. Раз с тех пор прошла реализация и
несколько итераций стенда (ветка feat/telemetry-stage6), по умолчанию
предсказание для О5 тоже GREEN — но это наименее надёжное предсказание в списке,
и если оно окажется RED, это ожидаемый по своей природе, а не сомнительный
результат.

    О1  test_owner_value_wins_the_final_leaf                                   GREEN
    О1  test_impostor_value_absent_from_every_merge                            GREEN
    О2  test_leaf_absent_when_owner_did_not_publish                            GREEN
    О2  test_impostor_value_absent_from_every_merge_when_owner_silent          GREEN
    О3  test_b_then_a_yields_owner_value                                       GREEN
    О3  test_a_then_b_yields_owner_value                                       GREEN
    О4  test_poll_owner_wins_while_alive                                       GREEN
    О4  test_poll_silent_owner_hides_leaf                                      GREEN
    О5  test_warning_names_metric_publisher_and_owner                          GREEN (наименее надёжное)
    О6  test_after_owner_stops_impostor_value_does_not_surface                 GREEN
    О7  test_forged_fps_absent_when_framework_has_no_value_this_tick           GREEN
    О7  test_forged_fps_absent_from_poll_when_framework_has_no_value_this_tick GREEN

Расхождение предсказания с фактом — находка, называется в отчёте, а не тихо
переписывается тестом под факт.
"""

from __future__ import annotations

import threading

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)


# --------------------------------------------------------------------------- #
# Часы и стоп-событие для форсирования ровно ОДНОГО тика (без time.sleep) —
# тот же образец, что в test_plugin_levels_ownership_acceptance.py.
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
    неоткуда, но правило «тест не имеет права зависнуть» соблюдается буквально:
    вызов идёт в отдельном потоке с join(timeout), а не напрямую.
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
# ProcessHeartbeat (иначе хранилище уровней разъезжается).
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


def _entry_text(entry: dict) -> str:
    """Весь текст записи лога (сообщение + именованные аргументы) одной строкой —
    чтобы искать имя/публикатора/владельца независимо от того, попали они в
    ``msg`` или в kwargs структурированного лога."""
    parts = [str(entry.get("msg", ""))]
    for k, v in entry.items():
        if k in ("level", "msg"):
            continue
        parts.append(str(v))
    return " ".join(parts)


def _plugin_ctx(services: _Services, plugin_name: str) -> PluginContext:
    base = PluginContext(services=services)
    return base.with_config({}, plugin_name=plugin_name)


def _running_worker(hz: float = 23.7, lat: float = 41.3, name: str = "w0") -> dict:
    return {name: {"status": "running", "effective_hz": hz, "cycle_duration_ms": lat}}


def _flatten_values(obj: object, out: list | None = None) -> list:
    """Собрать ВСЕ листовые значения произвольно вложенного dict — для проверки
    «значение не встречается нигде в payload'е», а не в одной угаданной позиции."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for v in obj.values():
            _flatten_values(v, out)
    else:
        out.append(obj)
    return out


def _value_absent_everywhere(merges: list[tuple[str, dict]], forbidden: float) -> bool:
    for _path, data in merges:
        for v in _flatten_values(data):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == pytest.approx(forbidden):
                return False
    return True


def _deep_merge_into(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_into(dst[k], v)
        else:
            dst[k] = v


def _apply_merges(merges: list[tuple[str, dict]]) -> dict:
    """Свести упорядоченный список ``proxy.merge`` вызовов в ИТОГОВОЕ дерево —
    та же логика глубокого merge по dot-пути, что у настоящего StateStoreManager."""
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
    в teardown (каталог объявлений глобален на процесс: сплошная очистка ломает
    объявления соседних тестов модуля)."""
    names: list[str] = []
    yield names
    if names:
        forget_declarations(KIND_METRIC, names=names)


class _MinimalPlugin(ProcessModulePlugin):
    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        pass


# --------------------------------------------------------------------------- #
# О1 — владелец побеждает при живом владельце (два ПРИКЛАДНЫХ плагина, не
# framework: накладывать поверх нечего, порядок наложения тут ничего не решает)
# --------------------------------------------------------------------------- #
class TestO1OwnerWinsWhileAlive:
    def test_owner_value_wins_the_final_leaf(self, declared_names) -> None:
        NAME = "collision_x_o1"
        svc = _Services(name="procO1")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a1")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b1")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 11.0)
        ctx_b.publish_metric(NAME, 22.0)  # B имени не объявлял

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        assert _get_path(tree, f"processes.procO1.state.{NAME}") == pytest.approx(11.0)

    def test_impostor_value_absent_from_every_merge(self, declared_names) -> None:
        NAME = "collision_x_o1b"
        svc = _Services(name="procO1b")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a1b")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b1b")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 11.0)
        ctx_b.publish_metric(NAME, 22.0)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        assert _value_absent_everywhere(svc._state_proxy.merged, 22.0), svc._state_proxy.merged


# --------------------------------------------------------------------------- #
# О2 — владелец молчит на этом тике: накладывать поверх нечего, самозванец не
# подменяет лист (главный разделитель по брифу)
# --------------------------------------------------------------------------- #
class TestO2SilentOwnerBlocksImpostor:
    def test_leaf_absent_when_owner_did_not_publish(self, declared_names) -> None:
        NAME = "collision_x_o2"
        svc = _Services(name="procO2")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a2")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b2")

        ctx_a.declare_metric(NAME)  # объявил, но НЕ публиковал на этом тике
        declared_names.append(NAME)
        ctx_b.publish_metric(NAME, 33.0)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        state = _get_path(tree, "processes.procO2.state") or {}
        assert NAME not in state, state

    def test_impostor_value_absent_from_every_merge_when_owner_silent(self, declared_names) -> None:
        NAME = "collision_x_o2b"
        svc = _Services(name="procO2b")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a2b")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b2b")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_b.publish_metric(NAME, 33.0)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        assert _value_absent_everywhere(svc._state_proxy.merged, 33.0), svc._state_proxy.merged


# --------------------------------------------------------------------------- #
# О3 — порядок публикаций ничего не решает: B-затем-A и A-затем-B дают один и
# тот же итоговый лист владельца
# --------------------------------------------------------------------------- #
class TestO3PublishOrderIrrelevant:
    def test_b_then_a_yields_owner_value(self, declared_names) -> None:
        NAME = "collision_x_o3ba"
        svc = _Services(name="procO3ba")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a3ba")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b3ba")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_b.publish_metric(NAME, 44.0)  # B первым
        ctx_a.publish_metric(NAME, 55.0)  # A вторым

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        assert _get_path(tree, f"processes.procO3ba.state.{NAME}") == pytest.approx(55.0)

    def test_a_then_b_yields_owner_value(self, declared_names) -> None:
        NAME = "collision_x_o3ab"
        svc = _Services(name="procO3ab")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a3ab")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b3ab")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 55.0)  # A первым
        ctx_b.publish_metric(NAME, 44.0)  # B вторым

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        assert _get_path(tree, f"processes.procO3ab.state.{NAME}") == pytest.approx(55.0)


# --------------------------------------------------------------------------- #
# О4 — то же самое на дороге опроса (current_levels_snapshot): у опроса своё
# правило про гейт, но правило владения обязано быть тем же
# --------------------------------------------------------------------------- #
class TestO4PollAgreesWithTree:
    def test_poll_owner_wins_while_alive(self, declared_names) -> None:
        NAME = "collision_x_o4a"
        svc = _Services(name="procO4a")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a4a")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b4a")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 66.0)
        ctx_b.publish_metric(NAME, 77.0)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot() or {}
        assert snap.get("state", {}).get(NAME) == pytest.approx(66.0)

    def test_poll_silent_owner_hides_leaf(self, declared_names) -> None:
        NAME = "collision_x_o4b"
        svc = _Services(name="procO4b")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a4b")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b4b")

        ctx_a.declare_metric(NAME)  # объявил, не публиковал
        declared_names.append(NAME)
        ctx_b.publish_metric(NAME, 88.0)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot() or {}
        state = snap.get("state", {})
        assert NAME not in state, state


# --------------------------------------------------------------------------- #
# О5 — голос называет всех троих: имя X, публикатор B и владелец A (а не
# «владельца нет») — ровно один раз за имя
# --------------------------------------------------------------------------- #
class TestO5WarningNamesAllThree:
    def test_warning_names_metric_publisher_and_owner(self, declared_names) -> None:
        NAME = "collision_x_o5"
        svc = _Services(name="procO5")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a5")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b5")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 1.0)
        ctx_b.publish_metric(NAME, 2.0)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        hits = [e for e in _warning_entries(svc) if NAME in _entry_text(e)]
        assert len(hits) == 1, svc.logs

        text = _entry_text(hits[0])
        assert NAME in text, hits[0]
        assert "impostor_b5" in text, ("публикатор не назван", hits[0])
        assert "owner_a5" in text, ("владелец не назван (или назван как 'нет владельца')", hits[0])


# --------------------------------------------------------------------------- #
# О6 — владелец ушёл: перехваченное значение самозванца не всплывает на
# следующем тике после остановки владельца
# --------------------------------------------------------------------------- #
class TestO6OwnerDeparts:
    def test_after_owner_stops_impostor_value_does_not_surface(self, declared_names) -> None:
        NAME = "collision_x_o6"
        svc = _Services(name="procO6")
        base_ctx = PluginContext(services=svc)
        ctx_a = base_ctx.with_config({}, plugin_name="owner_a6")
        ctx_b = base_ctx.with_config({}, plugin_name="impostor_b6")

        ctx_a.declare_metric(NAME)
        declared_names.append(NAME)
        ctx_a.publish_metric(NAME, 9.0)

        plugin_a = _MinimalPlugin()
        plugin_a.name = "owner_a6"
        plugin_a._do_configure(ctx_a)

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)  # тик ПРИ живом владельце — устанавливает предпосылку

        plugin_a._do_shutdown(ctx_a)
        assert plugin_a.state == PluginState.STOPPED

        ctx_b.publish_metric(NAME, 999.0)  # B продолжает публиковать после ухода A
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        state = _get_path(tree, "processes.procO6.state") or {}
        assert state.get(NAME) != pytest.approx(999.0), state


# --------------------------------------------------------------------------- #
# О7 — фреймворковое имя без фреймворкового значения на этом тике (процесс без
# воркеров: framework "fps" не считает вовсе) — подделка листа не даёт
# --------------------------------------------------------------------------- #
class TestO7FrameworkNameWithoutFrameworkValue:
    def test_forged_fps_absent_when_framework_has_no_value_this_tick(self) -> None:
        svc = _Services(name="procO7")  # БЕЗ воркеров => framework fps не считает
        ctx = _plugin_ctx(svc, "impostor_fps_o7")
        ctx.publish_metric("fps", 999.9)  # прикладной плагин, имени не объявлял

        clock = FakeClock()
        hb = ProcessHeartbeat(svc, clock=clock)
        _tick(hb, clock)

        tree = _apply_merges(svc._state_proxy.merged)
        state = _get_path(tree, "processes.procO7.state") or {}
        assert "fps" not in state, state

    def test_forged_fps_absent_from_poll_when_framework_has_no_value_this_tick(self) -> None:
        svc = _Services(name="procO7b")  # БЕЗ воркеров
        ctx = _plugin_ctx(svc, "impostor_fps_o7b")
        ctx.publish_metric("fps", 999.9)

        hb = ProcessHeartbeat(svc, clock=FakeClock())
        snap = hb.current_levels_snapshot() or {}
        state = snap.get("state", {})
        assert "fps" not in state, state
