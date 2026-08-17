# -*- coding: utf-8 -*-
"""Независимая приёмка механизма A — снятие уровня плагина обязано доехать до дерева.

Пишутся ДО реализации, от текста постановки, полученного НАПРЯМУЮ в задании (не из
плана и не из авторских тестов). Этой роли запрещено читать: `plans/QUEUE.md`,
`docs/sessions/2026-08-17.md`, любой `*_hazards.py` в тестах `process_module`/
`frontend_module`. Разрешено и использовано: `heartbeat/telemetry.py`,
`heartbeat/process_heartbeat.py` (уже существующий код, читается как ГОТОВЫЙ
механизм, а не как чужая тестовая модель), `plugins/base.py`, и уже закоммиченные
тесты `test_plugin_levels_ownership_acceptance.py` — как образец сборки стенда
(`_Services`, `FakeClock`, `_tick`, `PluginContext.with_config`).

Контракт (дословно из постановки):
    A1. Уровень опубликован, затем снят, а публикация в дерево на этом такте
        ПРОВАЛИЛАСЬ (``proxy.merge`` бросает исключение) → на следующем такте,
        когда ``merge`` проходит, дерево получает ``None`` по этому имени.
        Сегодня имя теряется навсегда — дефект.
    A2. Переутверждение снятия ОГРАНИЧЕНО: имя повторяется не бесконечно.
        Судится ЧИСЛОМ тактов; предел — именованная константа модуля,
        отдельной строкой проверяется её литерал.
    A3. Живое значение того же имени, появившееся ДО исчерпания предела,
        ОТМЕНЯЕТ переутверждение: идёт число, ``None`` больше не приходит.
    A4. Снимать нечего → пустой merge не отправляется вовсе (контроль,
        существующее поведение).

Что ПРИШЛОСЬ предположить (нет источника правды кроме прочитанного HEAD-кода
`heartbeat/telemetry.py`, где сегодняшний механизм — ОДНОРАЗОВЫЙ дренаж
``take_retracted()``, без какого-либо повтора при отказе ``merge``):

  1. Чтобы A1 вообще стало возможным (повтор ПОСЛЕ неудачи), реализация обязана
     завести какое-то состояние «имя ждёт подтверждённой доставки» — сегодня его
     нет: ``take_retracted()`` дренирует и НАВСЕГДА забывает имя за один вызов,
     до того как ``proxy.merge`` вообще попытается отправить его. Тест A1 не
     угадывает МЕХАНИЗМ хранения — он утверждает НАБЛЮДАЕМЫЙ эффект (дерево
     получает ``None`` на следующем удачном такте).
  3. A3 воспроизводит «плагин поднят заново» republish'ем через ТОТ ЖЕ
     ``PluginContext`` после ``_do_shutdown`` — ``publish_metric`` не привязан к
     жизненному циклу плагина (это подтверждено докстрингом ``PluginLevels.retract``:
     «плагин, поднятый заново, объявится тем же владельцем — это не конфликт»),
     поэтому повторный вызов на том же ``ctx`` — верная модель «владелец публикует
     снова», не обходной путь.

ОБНОВЛЕНО (2026-08-17): координатор закрыл дыру А2 напрямую формой контракта —
имя ``RETRACTION_REASSERT_TICKS``, значение 3, живёт в ``heartbeat/telemetry.py``;
считаются ТОЛЬКО успешные отправки (отказ merge бюджет не тратит). Это больше не
догадка тестера — см. `_retraction_reassert_ticks()` и класс `TestA2ReassertionIsBounded`.
С момента этого обновления файлы `heartbeat/process_heartbeat.py` (реализация уже
пишется параллельно) читать этой роли запрещено — импорт `ProcessHeartbeat` ниже
использует УЖЕ известный из предыдущего чтения публичный контракт (конструктор,
`_loop`, `current_levels_snapshot` и т.д.), новых обращений к файлу нет.

Расхождение предположений с фактом при прогоне — находка, называется в отчёте
тестера, а не тихо переписывается тестом под факт.
"""

from __future__ import annotations

from typing import Any, Optional

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
    ProcessModulePlugin,
)


# --------------------------------------------------------------------------- #
# Часы и стоп-событие для форсирования РОВНО одного тика — образец
# test_plugin_levels_ownership_acceptance.py (сама постановка это разрешает:
# «уже закоммиченные тесты как примеры сборки объектов»).
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

    Тик детерминирован (FakeClock, без реального sleep/IO), но правило «тест не
    имеет права зависнуть» соблюдается буквально: join с таймаутом, явный fail
    вместо тихого повисания.
    """
    import threading

    t_end = clock.t + dt
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            hb._loop(FakeStop(clock, t_end), _NoPauseEvent())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        pytest.fail(f"heartbeat-тик завис дольше {timeout}с")
    if errors:
        raise errors[0]


# --------------------------------------------------------------------------- #
# Сервисы процесса — ОДИН объект видят PluginContext и ProcessHeartbeat.
# --------------------------------------------------------------------------- #
class _Services:
    def __init__(self, name: str = "proc", proxy: object | None = None) -> None:
        self.name = name
        self.worker_manager = None
        self._state_proxy = proxy
        self.state_proxy = proxy
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

    def receive_message(self, timeout: Optional[float] = None) -> Optional[dict]:
        return None


class _StoppableFailProxy:
    """StateProxy-двойник: пока ``failing=True`` — КАЖДЫЙ ``merge`` бросает (но
    попытка запоминается в ``attempts`` ДО броска); ``failing=False`` — коммитит
    в ``merged``. Переключаемый вариант ``_AlwaysFailProxy``/``_FlakyOnceProxy``:
    нужен A3, где число неудачных тактов заранее неизвестно (зависит от
    реализованного предела А2), а проверить нужно именно «ПОКА переутверждение
    ещё идёт — republish его отменяет», а не гадать точное число попыток."""

    def __init__(self) -> None:
        self.attempts: list[tuple[str, dict]] = []
        self.merged: list[tuple[str, dict]] = []
        self.failing = False

    def merge(self, path: str, data: dict) -> None:
        self.attempts.append((path, dict(data)))
        if self.failing:
            raise RuntimeError("injected: proxy.merge fails while failing=True")
        self.merged.append((path, dict(data)))

    def set(self, path: str, value: Any) -> None:  # pragma: no cover
        pass


class _FlakyOnceProxy:
    """StateProxy-двойник: ОДИН явно назначенный вызов ``merge`` бросает,
    остальные — коммитятся в ``merged`` (накопительная лента для сборки дерева)."""

    def __init__(self) -> None:
        self.merged: list[tuple[str, dict]] = []
        self._should_fail_next = False

    def fail_next_merge(self) -> None:
        self._should_fail_next = True

    def merge(self, path: str, data: dict) -> None:
        if self._should_fail_next:
            self._should_fail_next = False
            raise RuntimeError("injected: proxy.merge fails on this tick")
        self.merged.append((path, dict(data)))

    def set(self, path: str, value: Any) -> None:  # pragma: no cover
        pass


def _deep_merge_into(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_into(dst[k], v)
        else:
            dst[k] = v


def _apply_merges(merges: list[tuple[str, dict]]) -> dict:
    """Свести упорядоченный список ПОДТВЕРЖДЁННЫХ ``proxy.merge`` в итоговое
    дерево (та же логика глубокого merge по dot-пути, что у StateStoreManager)."""
    tree: dict = {}
    for path, data in merges:
        node = tree
        for part in path.split("."):
            node = node.setdefault(part, {})
        _deep_merge_into(node, data)
    return tree


def _get_path(tree: dict, dotted: str) -> Any:
    node: Any = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class _MinimalPlugin(ProcessModulePlugin):
    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        pass


@pytest.fixture
def declared_names():
    """Имена, объявленные тестом через ctx.declare_metric — забываются ПОИМЁННО
    в teardown: сплошная очистка каталога метрик ломает соседние тесты модуля
    (см. docstring `forget_declarations`, урок уже учтён соседними файлами)."""
    names: list[str] = []
    yield names
    if names:
        forget_declarations(KIND_METRIC, names=names)


def _boot(name: str, proxy: object) -> tuple[_Services, PluginContext, ProcessHeartbeat, FakeClock]:
    svc = _Services(name=name, proxy=proxy)
    base_ctx = PluginContext(services=svc)
    clock = FakeClock()
    hb = ProcessHeartbeat(svc, clock=clock)
    return svc, base_ctx, hb, clock


# --------------------------------------------------------------------------- #
# A1 — отказ merge на такте снятия не имеет права похоронить имя навсегда
# --------------------------------------------------------------------------- #
class TestA1FailedMergeIsRetried:
    def test_retracted_name_reaches_the_tree_as_none_after_a_failed_merge_is_retried(self, declared_names) -> None:
        NAME = "probe_level_a1"
        proxy = _FlakyOnceProxy()
        svc, base_ctx, hb, clock = _boot("procA1", proxy)
        ctx = base_ctx.with_config({}, plugin_name="probe_plugin_a1")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 12.5)

        plugin = _MinimalPlugin()
        plugin.name = "probe_plugin_a1"
        plugin._do_configure(ctx)

        # Тик 1: значение реально доезжает до дерева (предпосылка, не критерий).
        _tick(hb, clock)
        tree = _apply_merges(proxy.merged)
        assert _get_path(tree, f"processes.procA1.state.{NAME}") == pytest.approx(12.5), (
            "предпосылка теста не выполнена: уровень не попал в дерево до снятия"
        )

        # Снятие: плагин остановлен. Merge на ЭТОМ такте ПРОВАЛИВАЕТСЯ.
        plugin._do_shutdown(ctx)
        proxy.fail_next_merge()
        _tick(hb, clock)  # merge бросает — не должен ронять heartbeat (см. _tick без исключений)

        # Следующий такт: merge проходит штатно.
        _tick(hb, clock)

        tree = _apply_merges(proxy.merged)
        state = _get_path(tree, "processes.procA1.state") or {}
        assert NAME in state, (
            f"дерево так и не получило показание 'нет данных' по '{NAME}' после отказа merge "
            f"на такте снятия — имя потеряно навсегда (дефект А1). Итоговое state={state!r}"
        )
        assert state[NAME] is None, (
            f"ожидали None (снятие подтверждено дереву на повторном такте), получили {state[NAME]!r}"
        )


# --------------------------------------------------------------------------- #
# A2 — переутверждение ограничено, а не бесконечно
#
# ОБНОВЛЕНО (2026-08-17, форма контракта дана координатором напрямую, не
# догадка тестера): константа называется ``RETRACTION_REASSERT_TICKS``, живёт в
# ``heartbeat/telemetry.py``, значение 3. Смысл уточнён координатором: считаются
# только УСПЕШНЫЕ отправки — такт, на котором ``proxy.merge`` провалился, бюджет
# не тратит. Импорт — ленивый (внутри теста, не на уровне модуля): на HEAD
# константы ещё нет, и падение обязано быть ЯВНЫМ ``pytest.fail``, а не голым
# ``ImportError`` при сборе файла (уронил бы ВСЕ тесты файла, а не только эти).
# --------------------------------------------------------------------------- #
def _retraction_reassert_ticks() -> int:
    from multiprocess_framework.modules.process_module.heartbeat import telemetry as telemetry_module

    if not hasattr(telemetry_module, "RETRACTION_REASSERT_TICKS"):
        pytest.fail(
            "Ожидали константу 'RETRACTION_REASSERT_TICKS' в "
            "multiprocess_framework/modules/process_module/heartbeat/telemetry.py "
            "(форма контракта зафиксирована координатором 2026-08-17: имя "
            "RETRACTION_REASSERT_TICKS, значение 3). На HEAD её нет — реализация "
            "ещё не появилась, это ожидаемый КРАСНЫЙ"
        )
    return telemetry_module.RETRACTION_REASSERT_TICKS


class TestA2ReassertionIsBounded:
    def test_retraction_reassert_ticks_constant_equals_three(self) -> None:
        """Литерал константы — отдельной строкой, дословно по контракту координатора."""
        limit = _retraction_reassert_ticks()
        assert limit == 3, (
            f"RETRACTION_REASSERT_TICKS = {limit!r}, контракт координатора (2026-08-17) фиксирует значение 3"
        )

    def test_reassertion_stops_after_exactly_the_retry_limit_successful_ticks(self, declared_names) -> None:
        """Считаются ТОЛЬКО успешные такты (``proxy`` здесь никогда не отказывает) —
        ровно ``RETRACTION_REASSERT_TICKS`` успешных 'None', затем имя исчезает
        из payload вовсе (не просто перестаёт быть None — пропадает как ключ)."""
        LIMIT = _retraction_reassert_ticks()
        NAME = "probe_level_a2a"
        proxy = _StoppableFailProxy()
        svc, base_ctx, hb, clock = _boot("procA2a", proxy)
        ctx = base_ctx.with_config({}, plugin_name="probe_plugin_a2a")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 3.0)

        plugin = _MinimalPlugin()
        plugin.name = "probe_plugin_a2a"
        plugin._do_configure(ctx)
        plugin._do_shutdown(ctx)  # снятие ДО первого тика

        for i in range(LIMIT):
            prev = len(proxy.merged)
            _tick(hb, clock)
            assert len(proxy.merged) > prev, (
                f"такт {i + 1} из {LIMIT}: ожидали успешный merge (proxy не настроен на "
                "отказ в этом тесте) — переутверждение остановилось РАНЬШЕ предела"
            )
            _path, data = proxy.merged[-1]
            state = data.get("state") or {}
            assert NAME in state and state[NAME] is None, (
                f"такт {i + 1} из {LIMIT}: ожидали переутверждение 'None' по '{NAME}', получили state={state!r}"
            )

        # (LIMIT + 1)-й такт: предел исчерпан — имени нет в payload вовсе.
        prev = len(proxy.merged)
        _tick(hb, clock)
        if len(proxy.merged) > prev:
            _path, data = proxy.merged[-1]
            state = data.get("state") or {}
            assert NAME not in state, (
                f"после {LIMIT} успешных переутверждений такт {LIMIT + 1} снова прислал '{NAME}': state={state!r}"
            )

    def test_a_failed_reassertion_tick_does_not_consume_the_retry_budget(self, declared_names) -> None:
        """Уточнение координатора: провал merge НЕ тратит бюджет переутверждений.
        Заваливаем merge заведомо БОЛЬШЕ раз, чем предел, ЗАТЕМ даём ему пройти —
        полный запас из LIMIT успешных попыток обязан быть цел."""
        LIMIT = _retraction_reassert_ticks()
        NAME = "probe_level_a2b"
        proxy = _StoppableFailProxy()
        svc, base_ctx, hb, clock = _boot("procA2b", proxy)
        ctx = base_ctx.with_config({}, plugin_name="probe_plugin_a2b")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 4.0)

        plugin = _MinimalPlugin()
        plugin.name = "probe_plugin_a2b"
        plugin._do_configure(ctx)

        _tick(hb, clock)  # тик 1: значение подтверждено (предпосылка)
        tree = _apply_merges(proxy.merged)
        assert _get_path(tree, f"processes.procA2b.state.{NAME}") == pytest.approx(4.0)

        plugin._do_shutdown(ctx)
        proxy.failing = True
        for _ in range(LIMIT + 5):  # заведомо больше предела провалов подряд
            _tick(hb, clock)
        proxy.failing = False

        successes = 0
        for i in range(LIMIT):
            prev = len(proxy.merged)
            _tick(hb, clock)
            assert len(proxy.merged) > prev, (
                f"такт {i + 1} после {LIMIT + 5} провалов подряд: ожидали успешный merge — "
                "провалы не должны были тратить бюджет переутверждений"
            )
            _path, data = proxy.merged[-1]
            state = data.get("state") or {}
            assert NAME in state and state[NAME] is None, state
            successes += 1

        assert successes == LIMIT, (
            f"после {LIMIT + 5} проваленных тактов подряд получили лишь {successes} "
            f"успешных переутверждений вместо полных {LIMIT} — похоже, провалы ТРАТЯТ "
            "бюджет переутверждений вопреки контракту координатора"
        )


# --------------------------------------------------------------------------- #
# A3 — живое значение до исчерпания предела отменяет переутверждение
# --------------------------------------------------------------------------- #
class TestA3LiveRepublishCancelsReassertion:
    def test_live_republish_before_retry_exhaustion_cancels_the_none_reassertion(self, declared_names) -> None:
        """Предпосылка теста ПРОВЕРЯЕТСЯ явно, а не предполагается: republish
        обязан застать переутверждение РЕАЛЬНО В ПРОЦЕССЕ (несколько неудачных
        тактов подряд, каждый — попытка именно None), иначе тест был бы зелёным
        случайно, «немым детектором» — под дефектом А1 (одна попытка и забыл
        навсегда) экономический эффект «республикация после единственной, уже
        похороненной попытки» неотличим от «отмена сработала», хотя отменять
        уже нечего. Число неудачных тактов перед republish'ем — 2 (нижняя
        граница «нескольких» из критерия А2, не угаданный предел)."""
        NAME = "probe_level_a3"
        proxy = _StoppableFailProxy()
        svc, base_ctx, hb, clock = _boot("procA3", proxy)
        ctx = base_ctx.with_config({}, plugin_name="probe_plugin_a3")
        ctx.declare_metric(NAME)
        declared_names.append(NAME)
        ctx.publish_metric(NAME, 5.0)

        plugin = _MinimalPlugin()
        plugin.name = "probe_plugin_a3"
        plugin._do_configure(ctx)

        _tick(hb, clock)  # тик 1: значение 5.0 подтверждено деревом (предпосылка)
        tree = _apply_merges(proxy.merged)
        assert _get_path(tree, f"processes.procA3.state.{NAME}") == pytest.approx(5.0)

        plugin._do_shutdown(ctx)  # снятие
        proxy.failing = True
        prev_len = 0
        for i in range(2):
            _tick(hb, clock)
            assert len(proxy.attempts) > prev_len, (
                f"такт {i + 2}: снятие не переутверждается вовсе — предпосылка теста А3 не "
                "выполнена (нет активного повтора, который можно было бы отменить republish'ем). "
                "Это симптом дефекта А1/А2: переутверждение либо не реализовано вовсе, либо "
                "предел исчерпан уже за один такт"
            )
            _path, data = proxy.attempts[-1]
            state = data.get("state") or {}
            assert NAME in state and state[NAME] is None, (
                f"такт {i + 2}: ожидали попытку переутверждения None по '{NAME}', получили "
                f"{state!r} — предпосылка теста А3 не выполнена"
            )
            prev_len = len(proxy.attempts)

        # Владелец публикует ЖИВОЕ значение, ПОКА переутверждение ЕЩЁ идёт (по
        # предпосылке выше — предел заведомо не исчерпан за 2 такта).
        ctx.publish_metric(NAME, 9.9)
        proxy.failing = False

        _tick(hb, clock)  # merge теперь проходит — обязан нести ЖИВОЕ 9.9, не None
        tree = _apply_merges(proxy.merged)
        state = _get_path(tree, "processes.procA3.state") or {}
        assert state.get(NAME) == pytest.approx(9.9), (
            f"живая публикация ДО исчерпания предела обязана отменить переутверждение снятия "
            f"и попасть в дерево как число; получили state={state!r}"
        )

        # Несколько тактов ПОСЛЕ — None по этому имени больше не приходит.
        for _ in range(3):
            _tick(hb, clock)
        tree = _apply_merges(proxy.merged)
        state = _get_path(tree, "processes.procA3.state") or {}
        assert state.get(NAME) == pytest.approx(9.9), (
            f"после отменённого переутверждения имя '{NAME}' снова получило 'None' в дереве "
            f"на одном из последующих тактов — отмена не удержалась; state={state!r}"
        )


# --------------------------------------------------------------------------- #
# A4 — контроль: снимать нечего → пустой merge не отправляется вовсе
# --------------------------------------------------------------------------- #
class TestA4NothingToRetractSendsNoMerge:
    def test_no_declared_no_published_no_workers_sends_zero_merges(self) -> None:
        proxy = _FlakyOnceProxy()
        svc, _base_ctx, hb, clock = _boot("procA4", proxy)
        _tick(hb, clock)
        _tick(hb, clock)
        assert proxy.merged == [], (
            f"снимать нечего (нет объявлений/публикаций/воркеров), а merge всё же ушёл: {proxy.merged!r}"
        )
