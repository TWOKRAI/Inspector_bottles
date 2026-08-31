# -*- coding: utf-8 -*-
"""Независимая приёмка Task 3.2 — опрос уровней телеметрии: пакетный снимок.

Источник контракта: текст требования Task 3.2 (не реализация — она не читалась).
Команда ``introspect.telemetry`` уже существует (readback publisher-гейта, Ф4.1) и
по требованию ДОПОЛНЯЕТСЯ двумя полями:

  - ``levels``      — текущий пакетный снимок уровней процесса (то, что процесс
                       знает о себе на этот момент, а не то, что он согласился
                       публиковать push'ем);
  - ``snapshot_ts``  — момент снятия снимка.

Харнесс подсмотрен (как ОБРАЗЕЦ, не источник контракта) в соседних тестах модуля:
test_introspect_telemetry.py (как поднимается фейковый CommandManager + реальный
ProcessHeartbeat поверх фейковых сервисов, как зовётся команда) и test_telemetry_tick.py
(FakeClock/FakeStop — форсирование ровно одного тика без time.sleep). Сама
реализация (builtin_commands.py, heartbeat/telemetry.py, heartbeat/process_heartbeat.py)
НЕ читалась — импортируется только как библиотека для конструирования фикстур,
как это уже делают существующие тесты модуля.

Решения по неоднозначным местам требования (см. также отчёт тестера):

  - п.4 snapshot_ts: сторожу «не убывает» (>=), НЕ «строго растёт» — на Windows
    разрешение monotonic ~15.6 мс делает строгий рост между двумя быстрыми вызовами
    ненадёжным сигналом (см. project-память). Часы не подменяю для этого свойства
    намеренно — гоняю несколько опросов подряд и проверяю отсутствие УБЫВАНИЯ.
  - п.5 сверка чисел: сравниваю МНОЖЕСТВО числовых листьев ``levels`` с МНОЖЕСТВОМ
    числовых листьев payload'а, реально смерженного в дерево на тике (через тот же
    RecordingProxy) — не пришпиливаю точную форму ``levels`` (dict shape), чтобы не
    зафиксировать чужую внутреннюю структуру как контракт. Фикстурные числа заведомо
    нецелые и невстречающиеся среди дефолтов (23.5/42.0/31.25/17.5), чтобы совпадение
    не было случайным (см. feedback_coinciding_constants_hide_opposite_implementations).
  - п.7 «пуст или None»: развожу ДВЕ разные причины пустоты раздельно — «нет
    ProcessHeartbeat вовсе» (сенсора нет физически) фиксирую как ``None``; «heartbeat
    есть, но воркеров нет/пусто» — допускаю И None, И пустой контейнер (решение
    реализации), но требую, чтобы ключ ``levels`` в любом случае ПРИСУТСТВОВАЛ в
    ответе (иначе тест тривиально «зелёный» уже сегодня — поля просто нет вообще).

Ожидание к концу RED-прогона: тесты классов TestBatchSnapshot,
TestSnapshotDespiteGateClosed, TestSnapshotTsPresentAndMonotonic,
TestLevelsMatchPushedNumbers, TestNoWorkersOrHeartbeat — КРАСНЫЕ (новое поведение,
поля levels/snapshot_ts ещё не существуют). Тесты TestPollDoesNotPublish и
TestExistingSectionsUnaffected проверяют уже существующее поведение и ожидаются
ЗЕЛЁНЫМИ уже сегодня.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)

# gated_metrics импортируется из heartbeat.telemetry (не из configs.telemetry_publish_config,
# как в соседнем test_introspect_telemetry.py) — характеризацией подтверждено, что каталог
# наполняется побочным эффектом импорта heartbeat/telemetry.py (declare_metric на уровне
# модуля); импорт из configs даёт неполный каталог (['shm']) при отсутствии этого импорта
# где-то ещё в цепочке. Тот же импорт использует test_telemetry_gate.py (образец-харнесс).
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    gated_metrics,
)


# --------------------------------------------------------------------------- #
# Часы и стоп-событие для форсирования ровно ОДНОГО тика (без time.sleep)
# --------------------------------------------------------------------------- #
class FakeClock:
    """Управляемый монотонный источник времени (образец — test_telemetry_tick.py)."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class FakeStop:
    """Останавливает цикл при достижении ``t_end``; ``wait`` двигает фейк-часы."""

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


# --------------------------------------------------------------------------- #
# Фейковые сервисы процесса
# --------------------------------------------------------------------------- #
class _WorkerManager:
    def __init__(self, workers: dict) -> None:
        self._workers = workers

    def get_all_workers_status(self) -> dict:
        return {w: dict(v) for w, v in self._workers.items()}


class _RecordingProxy:
    """Прокси дерева состояния: считает обращения merge/set — сторож п.3."""

    def __init__(self) -> None:
        self.merge_calls = 0
        self.set_calls = 0
        self.merged: list[tuple[str, dict]] = []
        self.sets: list[tuple[str, object]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self.merged.append((path, dict(data)))

    def set(self, path: str, value: object) -> None:
        self.set_calls += 1
        self.sets.append((path, value))


class _HeartbeatServices:
    """Сервисы, которые видит сам ProcessHeartbeat (второй слой — как в образце)."""

    def __init__(self, *, name: str = "camera_0", workers: dict | None = None, proxy=None, router=None) -> None:
        self.name = name
        self.worker_manager = _WorkerManager(workers) if workers is not None else None
        self._state_proxy = proxy if proxy is not None else _RecordingProxy()
        self.router_manager = router
        self._health_state = None
        self._current_process_status = "running"
        self._config: dict = {}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...

    def send_message(self, target: str, message: dict) -> bool:
        return True


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeServices:
    """Процесс-адресат для BuiltinCommands: свой CommandManager + опционально heartbeat."""

    def __init__(
        self,
        *,
        heartbeat: bool = True,
        workers: dict | None = None,
        proxy=None,
        router=None,
        clock=None,
        name: str = "camera_0",
    ) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = name
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        self._state_store_manager = None
        self.hb_services = (
            _HeartbeatServices(name=name, workers=workers, proxy=proxy, router=router) if heartbeat else None
        )
        self._heartbeat = ProcessHeartbeat(self.hb_services, clock=clock) if heartbeat else None

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    """И introspect.*, И observability.* в одном CommandManager — приёмка ходит
    парами (telemetry.reconfigure пишет гейт → introspect.telemetry читает), как
    в образце test_introspect_telemetry.py."""
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_introspect_commands()
    bc._register_observability_commands()
    return svc, svc.command_manager


def _distinct_workers() -> dict:
    """Значения заведомо не нули и не дефолты — иначе тест мерил бы дефолт.

    Значения намеренно ОДНОЗНАЧНОГО одного знака после запятой: характеризацией
    (см. отчёт) подтверждено, что существующий push-путь округляет телеметрию до
    1 знака (``round(x, 1)``) — например, 31.25 на push-пути превращается в 31.2
    (round-half-to-even двоичного float). Величина с ровно одним знаком после
    запятой проходит через ``round(x, 1)`` без потери — сравнение push vs poll
    остаётся однозначным независимо от того, округляет ли будущая реализация
    опроса так же.
    """
    return {
        "w0": {"status": "running", "effective_hz": 23.7, "cycle_duration_ms": 41.3},
        "w1": {"status": "running", "effective_hz": 31.9, "cycle_duration_ms": 17.6},
    }


_FIXTURE_NUMBERS = {23.7, 41.3, 31.9, 17.6}


def _flatten_numbers(obj) -> set:
    """Собирает все числовые листья (кроме bool) из произвольно вложенной структуры.

    Намеренно не привязывается к конкретной форме ``levels`` (dict/list вложенность
    может быть любой) — свойство "числа совпадают" проверяется через множество
    значений, а не через путь до них.
    """
    out: set = set()

    def walk(o):
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            out.add(float(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                walk(v)

    walk(obj)
    return out


# --------------------------------------------------------------------------- #
# п.1 — пакетность: один вызов отдаёт уровни ВСЕХ метрик и ВСЕХ воркеров сразу
# --------------------------------------------------------------------------- #
class TestBatchSnapshot:
    def test_single_call_yields_multiple_workers_and_metrics(self) -> None:
        """Свойство: ОДИН dispatch → в levels видны оба воркера одновременно.

        Наблюдаемый эффект: числа обоих воркеров (effective_hz/cycle_duration_ms
        w0 И w1) присутствуют в ОДНОМ ответе — не по отдельному вызову на воркера
        или метрику.
        """
        svc, cm = _make(workers=_distinct_workers())
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert "levels" in res
        numbers = _flatten_numbers(res["levels"])
        assert _FIXTURE_NUMBERS.issubset(numbers), numbers


# --------------------------------------------------------------------------- #
# п.2 — снимок доступен при ВЫКЛЮЧЕННОЙ публикации (все метрики enabled=False)
# --------------------------------------------------------------------------- #
class TestSnapshotDespiteGateClosed:
    def test_levels_present_when_all_metrics_disabled_for_publish(self) -> None:
        """Свойство: levels не зависит от publisher-гейта — гейт про push, не про то,
        что процесс знает о себе.

        Наблюдаемый эффект: даже когда ``resolved[*]['enabled']`` ложно для ВСЕХ
        метрик каталога (гейт закрыл публикацию целиком), levels всё равно содержит
        числа фикстуры воркеров.
        """
        svc, cm = _make(workers=_distinct_workers())
        disable_all = {name: {"enabled": False} for name in gated_metrics()}
        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": disable_all}})

        gated = cm.dispatch("introspect.telemetry")
        assert gated["gate_active"] is True
        assert all(v["enabled"] is False for v in gated["resolved"].values()), gated["resolved"]

        assert "levels" in gated
        numbers = _flatten_numbers(gated["levels"])
        assert _FIXTURE_NUMBERS.issubset(numbers), numbers


# --------------------------------------------------------------------------- #
# п.3 — опрос НЕ публикует (существующее свойство readback'а; ожидается зелёным)
# --------------------------------------------------------------------------- #
class TestPollDoesNotPublish:
    def test_zero_proxy_calls_during_poll(self) -> None:
        """Свойство: наблюдение не мутирует систему.

        Наблюдаемый эффект: счётчик merge+set у state-proxy НЕ меняется за время
        команды — используется тот же счётчик, что видит push-путь при обычной
        публикации (см. TestLevelsMatchPushedNumbers).
        """
        proxy = _RecordingProxy()
        svc, cm = _make(workers=_distinct_workers(), proxy=proxy)
        before = proxy.merge_calls + proxy.set_calls
        cm.dispatch("introspect.telemetry")
        after = proxy.merge_calls + proxy.set_calls
        assert after == before == 0

    def test_repeated_polls_stay_at_zero(self) -> None:
        """Повтор опроса (не только первый вызов) тоже не пишет в дерево."""
        proxy = _RecordingProxy()
        svc, cm = _make(workers=_distinct_workers(), proxy=proxy)
        for _ in range(3):
            cm.dispatch("introspect.telemetry")
        assert proxy.merge_calls == 0
        assert proxy.set_calls == 0


# --------------------------------------------------------------------------- #
# п.4 — snapshot_ts присутствует и не убывает между опросами
# --------------------------------------------------------------------------- #
class TestSnapshotTsPresentAndMonotonic:
    def test_snapshot_ts_present_and_numeric(self) -> None:
        svc, cm = _make(workers=_distinct_workers())
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert "snapshot_ts" in res
        assert isinstance(res["snapshot_ts"], (int, float))

    def test_snapshot_ts_does_not_decrease_across_repeated_polls(self) -> None:
        """Не полагаюсь на разрешение системного monotonic (Windows ~15.6 мс) —
        сторожу «не убывает» (>=), а не строгий рост между соседними быстрыми
        вызовами. Часы не подменяю намеренно: реальные повторные опросы без сна."""
        svc, cm = _make(workers=_distinct_workers())
        values = []
        for _ in range(5):
            res = cm.dispatch("introspect.telemetry")
            assert "snapshot_ts" in res
            values.append(res["snapshot_ts"])
        assert values == sorted(values), values


# --------------------------------------------------------------------------- #
# п.5 — числа в levels совпадают с тем, что реально ушло в push (тот же сборщик)
# --------------------------------------------------------------------------- #
class TestLevelsMatchPushedNumbers:
    def test_levels_agree_with_the_values_pushed_on_a_tick(self) -> None:
        """Свойство: опрос не пересчитывает вторым способом — берёт тот же снимок,
        что уходит в дерево на обычном тике публикации.

        Наблюдаемый эффект: множество числовых листьев push-payload'а (реально
        смерженного в RecordingProxy на форсированном тике) — подмножество
        числовых листьев poll-ответа (levels). Форма ``levels`` не фиксируется
        (см. докстринг модуля) — сравнение идёт по множеству значений.
        """
        proxy = _RecordingProxy()
        clock = FakeClock()
        svc, cm = _make(workers=_distinct_workers(), proxy=proxy, clock=clock)

        # Гейт с дефолтами (все метрики enabled) — форсируем ровно один тик.
        cm.dispatch("telemetry.reconfigure", {"publish": {}})
        svc._heartbeat._loop(FakeStop(clock, t_end=0.01), _NoPauseEvent())

        assert proxy.merge_calls >= 1, "форсированный тик обязан был опубликовать хотя бы раз"
        pushed_numbers: set = set()
        for _path, data in proxy.merged:
            pushed_numbers |= _flatten_numbers(data)
        # фикстура точно ушла в push — иначе сам тест не годится для сравнения.
        assert _FIXTURE_NUMBERS.issubset(pushed_numbers), pushed_numbers

        res = cm.dispatch("introspect.telemetry")
        assert "levels" in res
        levels_numbers = _flatten_numbers(res["levels"])
        assert pushed_numbers.issubset(levels_numbers), (pushed_numbers, levels_numbers)


# --------------------------------------------------------------------------- #
# п.6 — существующие секции ответа не сломаны (дополнение, не замена)
# --------------------------------------------------------------------------- #
class TestExistingSectionsUnaffected:
    def test_all_legacy_keys_present(self) -> None:
        svc, cm = _make(workers=_distinct_workers())
        res = cm.dispatch("introspect.telemetry")
        for key in ("gate_active", "publish", "resolved", "unknown_metrics", "gated_metrics", "throttle_rules"):
            assert key in res, key

    def test_gate_off_by_default_like_before(self) -> None:
        svc, cm = _make(workers=_distinct_workers())
        res = cm.dispatch("introspect.telemetry")
        assert res["gate_active"] is False
        assert res["publish"] is None
        assert res["resolved"] is None

    def test_gated_metrics_catalog_matches_registry(self) -> None:
        svc, cm = _make(workers=_distinct_workers())
        res = cm.dispatch("introspect.telemetry")
        assert res["gated_metrics"] == list(gated_metrics())

    def test_unknown_metric_still_surfaces_after_reconfigure(self) -> None:
        svc, cm = _make(workers=_distinct_workers())
        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"latency": {"interval_sec": 0.5}}}})
        res = cm.dispatch("introspect.telemetry")
        assert res["unknown_metrics"] == ["latency"]


# --------------------------------------------------------------------------- #
# п.7 — процесс без воркеров / без heartbeat: команда не падает
# --------------------------------------------------------------------------- #
class TestNoWorkersOrHeartbeat:
    """Ключ ``levels`` ОБЯЗАН присутствовать в ответе даже в вырожденных случаях —
    иначе тест тривиально «зелёный» уже сегодня просто потому, что поля нет вообще
    ни при каких условиях (см. докстринг модуля)."""

    def test_no_heartbeat_levels_is_none(self) -> None:
        """Нет ProcessHeartbeat вовсе → сенсора физически нет → levels is None."""
        svc, cm = _make(heartbeat=False)
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert "levels" in res
        assert res["levels"] is None

    def test_heartbeat_without_worker_manager_does_not_crash(self) -> None:
        """Heartbeat есть, worker_manager=None → допускаю None ИЛИ пустой контейнер."""
        svc, cm = _make(workers=None)
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert "levels" in res
        assert res["levels"] in (None, {}, [])

    def test_heartbeat_with_zero_workers_does_not_crash(self) -> None:
        """Heartbeat + worker_manager есть, воркеров 0 → допускаю None ИЛИ пустой контейнер."""
        svc, cm = _make(workers={})
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert "levels" in res
        assert res["levels"] in (None, {}, [])
