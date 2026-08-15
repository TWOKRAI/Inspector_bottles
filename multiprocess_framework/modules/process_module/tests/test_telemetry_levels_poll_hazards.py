# -*- coding: utf-8 -*-
"""Авторские тесты опасностей МЕХАНИЗМА опроса уровней (Task 3.2, ADR-PM-035).

Приёмка (`test_telemetry_levels_poll_acceptance.py`) писалась независимым тестером от
формулировки требования и без доступа к реализации — она сторожит КОНТРАКТ команды.
Этот файл сторожит другое: то, что видно только изнутри собранного механизма, и чего
тестер видеть не мог, потому что оно не следует из требования.

**Что может сломаться именно в ЭТОМ механизме — по одной опасности на класс:**

H1. *Опрос идёт из ЧУЖОГО потока, посреди тика.* Публикация живёт в потоке воркера
    `heartbeat_sender`, команда — в потоке диспетчера, и общего замка между ними нет.
    Сборщик один на две дороги; заведись у него хоть капля состояния между вызовами
    (кэш последнего снимка, накопитель, «ленивая» инициализация) — опрос, пришедший
    ровно в момент публикации, увидел бы полу-собранный payload или испортил бы чужой.
    Рандеву ставится НА ОПЕРАЦИЮ (публикатор замирает внутри `proxy.merge`), а не на
    входе в цикл: барьер на входе разошёлся бы с настоящим окном гонки.

H2. *Соблазн позвать `due_metrics()` на дороге опроса.* Он выглядит правильным
    («тогда push и poll покажут одно и то же»), но `due_metrics` ПРОДВИГАЕТ `_next_due`:
    наблюдение съело бы слот метрики, и следующий тик молча не опубликовал бы её.
    Дефект тихий и растёт с частотой опроса — ровно тот класс «наблюдение мутирует
    систему», который спека отвергла у GUI-развилки 3.3. Сторожится двумя приборами:
    расписанием гейта (точный локализатор) И наблюдаемым следствием — тик ПОСЛЕ серии
    опросов обязан по-прежнему публиковать.

H3. *Отказ одной секции уносит весь ответ.* У снимка два независимых источника
    (`worker_manager` и `router`), и оба могут отказать порознь. Правило команды —
    best-effort по образцу `introspect.memory`: недоступная подсистема → `None` в своей
    секции. Отдельно сторожится, что проглоченный отказ ОСТАВЛЯЕТ СЛЕД (`levels_error`):
    следствие без причины хуже отсутствия.

H4. *Снимок отдаёт ссылки на живое.* `levels` уезжает потребителю по IPC, но внутри
    процесса это обычные dict'ы. Верни сборщик ссылку на внутреннее состояние — правка
    у потребителя (или сериализатор, дополняющий payload) отравила бы то, что процесс
    опубликует следующим тиком. Сторожится в обе стороны: правка ответа не меняет
    ни следующий push, ни исходный снимок воркеров.

H5. *Моя же правка публикатора.* Список shm-счётчиков выехал в общий сборщик, а
    поимённое сравнение тринадцати нулей заменено на `any(payload.values())`. Замена
    выглядит эквивалентной; проверяется, что она действительно эквивалентна — «всё по
    нулям» по-прежнему НЕ грузит дерево, а один ненулевой счётчик публикует полный набор.

H6. *`shm` мимо опроса.* Развилка с живыми последствиями: в юнит-тестах `router` обычно
    `None`, поэтому расхождение push/poll по группе `shm` невидимо — и приёмка тестера
    его увидеть не могла. На боевом процессе тик публикует `state.shm.*`, и опрос обязан
    отдавать ту же группу той же формой пути — в том числе когда гейт закрыл её для push.

H7. *`cycles` — единственный признак СВЕЖЕСТИ ЧИСЕЛ, и он односторонний* (ревью-блокер 2).
    `snapshot_ts` меряет возраст ответа, а не возраст чисел: у остановленного воркера штамп
    идёт, а `fps`/`latency_ms` стоят. Признак движения даёт счётчик циклов. Две опасности
    сразу: (а) он обязан ПРИЙТИ опросом — иначе потребитель 3.3 покажет «живо» на замёрзшей
    камере; (б) он обязан НЕ уехать в push — иначе цена pull-модели растёт листом на воркера
    на каждый тик, ради того, что нужно только опрашивающему. Асимметрия односторонняя, и
    именно её сторожит пара тестов: push ⊆ poll остаётся правдой.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)

# ---------------------------------------------------------------------------- #
# Харнесс (свой, намеренно не импортируется из приёмочного файла: приёмка — контракт,
# и сцеплять с ней авторские тесты значило бы чинить два файла одной правкой).
# ---------------------------------------------------------------------------- #
WORKERS = {
    # `cycles` кладёт сюда WorkerManager.get_worker_status (подмешивает снимок
    # CycleMetricsRecorder наверх статуса) — фикстура повторяет боевую форму.
    "w0": {"status": "running", "effective_hz": 23.7, "cycle_duration_ms": 41.3, "cycles": 1201},
    "w1": {"status": "running", "effective_hz": 31.9, "cycle_duration_ms": 17.6, "cycles": 3407},
}

# Полный набор ключей shm-payload'а (форма пути та же, что у push: state.shm.*).
SHM_KEYS = {
    "pickle_fallbacks",
    "torn_reads",
    "boundary_crossings",
    "queue_data_evicted",
    "queue_system_evict_blocked",
    "queue_observability_evicted",
    "queue_observability_send_failed",
    "observability_delivery_failed",
    "stale_drops",
    "loan_exhausted",
    "slots_released",
    "slots_reclaimed",
    "cache_size",
}


class _WorkerManager:
    def __init__(self, workers: dict) -> None:
        self.source = workers

    def get_all_workers_status(self) -> dict:
        # Как настоящий: отдаёт СВЕЖИЕ dict'ы, а не ссылки на внутренние.
        return {w: dict(v) for w, v in self.source.items()}


class _Proxy:
    def __init__(self) -> None:
        self.merge_calls = 0
        self.set_calls = 0
        self.merged: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self.merged.append((path, data))

    def set(self, path: str, value: object) -> None:
        self.set_calls += 1


class _BlockingProxy(_Proxy):
    """Замирает ВНУТРИ первого merge — рандеву на операции публикации (H1)."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True

    def merge(self, path: str, data: dict) -> None:
        if self._first:
            self._first = False
            self.entered.set()
            # Таймаут-предохранитель: тест, который ВИСНЕТ вместо падения, хуже
            # отсутствующего — он прячет регрессию за дедлайном прогона.
            self.release.wait(timeout=10.0)
        super().merge(path, data)


class _Router:
    """Фейк router'а. `stats` — что вернуть; `raises` — отказать вместо ответа."""

    def __init__(self, stats: dict | None = None, raises: bool = False) -> None:
        self._stats = stats if stats is not None else {}
        self._raises = raises
        self.calls = 0

    def get_stats(self) -> dict:
        self.calls += 1
        if self._raises:
            raise RuntimeError("router недоступен")
        return {"router": dict(self._stats)}


class _HbServices:
    def __init__(self, *, workers: dict | None = None, proxy=None, router=None, name="camera_0") -> None:
        self.name = name
        self.worker_manager = _WorkerManager(workers) if workers is not None else None
        self._state_proxy = proxy if proxy is not None else _Proxy()
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


class _CommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _Services:
    def __init__(self, **kw) -> None:
        self.command_manager = _CommandManager()
        self.name = kw.get("name", "camera_0")
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        self._state_store_manager = None
        self.hb_services = _HbServices(**kw)
        self._heartbeat = ProcessHeartbeat(self.hb_services)

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _Services(**kw)
    bc = BuiltinCommands(svc)
    bc._register_introspect_commands()
    bc._register_observability_commands()
    return svc, svc.command_manager


def _one_tick(hb, stop_after_first=True) -> None:
    """Ровно одна итерация `_loop` (стоп-событие «сработало» со второй проверки)."""

    class _Stop:
        def __init__(self) -> None:
            self.n = 0

        def is_set(self) -> bool:
            self.n += 1
            return self.n > 1

        def wait(self, timeout=None) -> None: ...

    class _NoPause:
        def is_set(self) -> bool:
            return False

    hb._loop(_Stop(), _NoPause())


# ============================================================================ #
# H1 — опрос посреди тика, из чужого потока
# ============================================================================ #
class TestPollDuringTick:
    def test_poll_while_publisher_is_inside_merge(self) -> None:
        """Публикатор замер ВНУТРИ `proxy.merge`; опрос приходит ровно в это окно.

        Наблюдаемый эффект: ответ опроса полон (числа обоих воркеров на месте), и за
        время опроса не прибавилось НИ ОДНОЙ записи в дерево — счётчик прокси остаётся
        тем же, что был до опроса (тик всё ещё держит свою первую запись незавершённой).
        """
        proxy = _BlockingProxy()
        svc, cm = _make(workers=WORKERS, proxy=proxy)

        thread = threading.Thread(target=_one_tick, args=(svc._heartbeat,), daemon=True)
        thread.start()
        try:
            assert proxy.entered.wait(timeout=10.0), "публикатор не дошёл до merge"
            before = proxy.merge_calls + proxy.set_calls

            res = cm.dispatch("introspect.telemetry")

            assert res["success"] is True
            numbers = set()
            for w in res["levels"]["workers"].values():
                numbers |= {v for v in w.values() if isinstance(v, (int, float))}
            assert {23.7, 41.3, 31.9, 17.6} <= numbers, numbers
            assert proxy.merge_calls + proxy.set_calls == before
        finally:
            proxy.release.set()
            thread.join(timeout=10.0)
        assert not thread.is_alive(), "поток публикации не завершился — тик завис"


# ============================================================================ #
# H2 — опрос не двигает расписание гейта
# ============================================================================ #
class TestPollDoesNotTouchTheGate:
    def test_next_due_unchanged_after_polls(self) -> None:
        """Точный локализатор: `_next_due` и сам объект гейта — те же после серии опросов."""
        svc, cm = _make(workers=WORKERS)
        svc._heartbeat.reconfigure_telemetry({})  # гейт активен, дефолты
        gate = svc._heartbeat._telemetry_gate
        before = dict(gate._next_due)

        for _ in range(5):
            cm.dispatch("introspect.telemetry")

        assert svc._heartbeat._telemetry_gate is gate, "опрос подменил гейт"
        assert dict(gate._next_due) == before, gate._next_due

    def test_tick_after_polls_still_publishes(self) -> None:
        """Наблюдаемое следствие того же свойства: если бы опрос съедал слот метрики
        (позвав `due_metrics`), тик после серии опросов опубликовал бы пустоту."""
        proxy = _Proxy()
        svc, cm = _make(workers=WORKERS, proxy=proxy)
        svc._heartbeat.reconfigure_telemetry({})

        for _ in range(5):
            cm.dispatch("introspect.telemetry")
        assert proxy.merge_calls == 0

        _one_tick(svc._heartbeat)
        assert proxy.merge_calls == 1, proxy.merged
        _path, data = proxy.merged[0]
        assert data["workers"]["w0"]["effective_hz"] == 23.7
        assert data["state"]["fps"] == 31.9


# ============================================================================ #
# H3 — отказ секции не уносит ответ, но оставляет след
# ============================================================================ #
class TestSectionFailureIsContained:
    def test_router_failure_leaves_worker_levels_intact(self) -> None:
        """`router.get_stats()` падает → секции `shm` нет, воркерные уровни на месте."""
        router = _Router(raises=True)
        svc, cm = _make(workers=WORKERS, router=router)

        res = cm.dispatch("introspect.telemetry")

        assert res["success"] is True
        assert router.calls == 1, "сборщик даже не спросил router"
        assert "shm" not in (res["levels"].get("state") or {})
        assert res["levels"]["workers"]["w0"]["effective_hz"] == 23.7

    def test_collector_failure_keeps_command_alive_and_names_the_reason(self) -> None:
        """Сборщик целиком падает → команда всё равно `success=True`, `levels=None`,
        и причина НАЗВАНА: проглоченный отказ без следа хуже отсутствия секции."""
        svc, cm = _make(workers=WORKERS)

        def _boom():
            raise RuntimeError("сборщик сломан")

        svc._heartbeat.current_levels_snapshot = _boom

        res = cm.dispatch("introspect.telemetry")

        assert res["success"] is True
        assert res["levels"] is None
        assert "сборщик сломан" in res["levels_error"]
        # Соседние секции не пострадали.
        assert res["gated_metrics"]

    def test_worker_status_failure_does_not_crash_the_poll(self) -> None:
        """Отказ `get_all_workers_status()` → снимок пуст, но команда отвечает."""
        svc, cm = _make(workers=WORKERS)

        def _boom():
            raise RuntimeError("worker_manager сломан")

        svc.hb_services.worker_manager.get_all_workers_status = _boom

        res = cm.dispatch("introspect.telemetry")

        assert res["success"] is True
        assert res["levels"] is None


# ============================================================================ #
# H4 — снимок не отдаёт ссылок на живое
# ============================================================================ #
class TestSnapshotIsDetached:
    def test_mutating_the_answer_does_not_poison_the_next_push(self) -> None:
        proxy = _Proxy()
        svc, cm = _make(workers=WORKERS, proxy=proxy)

        levels = cm.dispatch("introspect.telemetry")["levels"]
        levels["workers"]["w0"]["effective_hz"] = 999.0
        levels["state"]["fps"] = 999.0
        levels["state"]["injected"] = "мусор"

        _one_tick(svc._heartbeat)

        _path, data = proxy.merged[0]
        assert data["workers"]["w0"]["effective_hz"] == 23.7
        assert data["state"]["fps"] == 31.9
        assert "injected" not in data["state"]

    def test_poll_does_not_mutate_the_worker_source(self) -> None:
        source_before = {w: dict(v) for w, v in WORKERS.items()}
        svc, cm = _make(workers=WORKERS)

        cm.dispatch("introspect.telemetry")

        assert svc.hb_services.worker_manager.source == source_before

    def test_two_polls_return_independent_objects(self) -> None:
        svc, cm = _make(workers=WORKERS)

        first = cm.dispatch("introspect.telemetry")["levels"]
        first["workers"]["w0"]["effective_hz"] = 999.0
        second = cm.dispatch("introspect.telemetry")["levels"]

        assert second["workers"]["w0"]["effective_hz"] == 23.7


# ============================================================================ #
# H5 — эквивалентность переписанного guard'а публикатора
# ============================================================================ #
class TestShmPublisherGuardPreserved:
    def test_all_counters_zero_still_not_published(self) -> None:
        """Все нули → дерево НЕ грузим (прежнее поведение поимённого сравнения)."""
        proxy = _Proxy()
        svc, _cm = _make(workers=WORKERS, proxy=proxy, router=_Router({}))

        _one_tick(svc._heartbeat)

        paths = [p for p, _ in proxy.merged]
        assert not any(p.endswith("state.shm") for p in paths), paths

    def test_single_nonzero_counter_publishes_the_full_set(self) -> None:
        proxy = _Proxy()
        router = _Router({"frame_torn_reads": 3})
        svc, _cm = _make(workers=WORKERS, proxy=proxy, router=router)

        _one_tick(svc._heartbeat)

        shm = [d for p, d in proxy.merged if p.endswith("state.shm")]
        assert len(shm) == 1, proxy.merged
        assert set(shm[0]) == SHM_KEYS
        assert shm[0]["torn_reads"] == 3
        assert shm[0]["pickle_fallbacks"] == 0

    def test_gate_without_shm_skips_the_source_entirely(self) -> None:
        """Гейт закрыл `shm` → publish даже не спрашивает router (экономия источника)."""
        proxy = _Proxy()
        router = _Router({"frame_torn_reads": 3})
        svc, _cm = _make(workers=WORKERS, proxy=proxy, router=router)
        svc._heartbeat.reconfigure_telemetry({"metrics": {"shm": {"enabled": False}}})

        _one_tick(svc._heartbeat)

        assert router.calls == 0
        assert not any(p.endswith("state.shm") for p, _ in proxy.merged)


# ============================================================================ #
# H6 — shm едет опросом, в том числе при закрытом для push гейте
# ============================================================================ #
class TestShmTravelsWithThePoll:
    def test_poll_includes_shm_under_the_same_path_shape_as_push(self) -> None:
        proxy = _Proxy()
        router = _Router({"frame_torn_reads": 3, "frame_boundary_crossings": 7})
        svc, cm = _make(workers=WORKERS, proxy=proxy, router=router)

        _one_tick(svc._heartbeat)
        pushed = [d for p, d in proxy.merged if p.endswith("state.shm")][0]

        levels = cm.dispatch("introspect.telemetry")["levels"]

        # Та же группа, та же форма пути: push кладёт в processes.<name>.state.shm,
        # снимок — в поддерево state.shm того же processes.<name>.
        assert levels["state"]["shm"] == pushed

    def test_poll_returns_shm_even_when_the_gate_closed_it_for_push(self) -> None:
        """Главный приз развилки: гейт закрыл `shm` → в дереве её нет, опрос отдаёт.

        Именно этого приёмка тестера увидеть не могла — там `router is None`.
        """
        proxy = _Proxy()
        router = _Router({"frame_torn_reads": 3})
        svc, cm = _make(workers=WORKERS, proxy=proxy, router=router)
        svc._heartbeat.reconfigure_telemetry({"metrics": {"shm": {"enabled": False}}})

        _one_tick(svc._heartbeat)
        assert not any(p.endswith("state.shm") for p, _ in proxy.merged)

        levels = cm.dispatch("introspect.telemetry")["levels"]
        assert levels["state"]["shm"]["torn_reads"] == 3

    def test_zero_counters_are_a_reading_for_the_poll(self) -> None:
        """У публикатора «все нули» = не грузить дерево; у опроса — показание «всё чисто».
        Разные ответы на одни данные — намеренно, поэтому проверяются порознь."""
        svc, cm = _make(workers=WORKERS, router=_Router({}))

        levels = cm.dispatch("introspect.telemetry")["levels"]

        assert set(levels["state"]["shm"]) == SHM_KEYS
        assert set(levels["state"]["shm"].values()) == {0}


# ============================================================================ #
# H7 — cycles: признак свежести ЧИСЕЛ, только на дороге опроса
# ============================================================================ #
class TestCyclesIsThePollOnlyFreshnessSignal:
    def test_poll_carries_cycles_per_worker(self) -> None:
        svc, cm = _make(workers=WORKERS)

        levels = cm.dispatch("introspect.telemetry")["levels"]

        assert levels["workers"]["w0"]["cycles"] == 1201
        assert levels["workers"]["w1"]["cycles"] == 3407

    def test_push_does_not_carry_cycles(self) -> None:
        """Иначе цена pull-модели растёт листом на воркера на КАЖДЫЙ тик."""
        proxy = _Proxy()
        svc, _cm = _make(workers=WORKERS, proxy=proxy)

        _one_tick(svc._heartbeat)

        _path, data = proxy.merged[0]
        assert "cycles" not in data["workers"]["w0"], data["workers"]["w0"]
        assert "cycles" not in data["workers"]["w1"]

    def test_pushed_numbers_remain_a_subset_of_polled(self) -> None:
        """Асимметрия односторонняя: опрос ДОБАВЛЯЕТ поле, а не меняет числа.

        То же свойство, что сторожит п.5 приёмки, — проверяется здесь ещё раз уже
        с `cycles` в ответе, чтобы добавка не превратилась в расхождение.
        """
        proxy = _Proxy()
        svc, cm = _make(workers=WORKERS, proxy=proxy)

        _one_tick(svc._heartbeat)
        _path, pushed = proxy.merged[0]
        levels = cm.dispatch("introspect.telemetry")["levels"]

        for wname, wdata in pushed["workers"].items():
            for key, value in wdata.items():
                assert levels["workers"][wname][key] == value, (wname, key)
        assert pushed["state"]["fps"] == levels["state"]["fps"]

    def test_stalled_worker_shows_frozen_cycles_while_numbers_repeat(self) -> None:
        """Сценарий, ради которого поле заведено: числа стоят — счётчик тоже стоит.

        Наблюдаемый эффект: два опроса дают одинаковые `fps`/`cycles`, а `snapshot_ts`
        РАЗНЫЙ — то есть по штампу «свежо», по счётчику «встало». Пара разводит эти
        два случая, штамп в одиночку — нет.
        """
        svc, cm = _make(workers=WORKERS)

        first = cm.dispatch("introspect.telemetry")
        second = cm.dispatch("introspect.telemetry")

        assert second["snapshot_ts"] >= first["snapshot_ts"]
        assert first["levels"]["workers"]["w0"]["cycles"] == second["levels"]["workers"]["w0"]["cycles"]
        assert first["levels"]["state"]["fps"] == second["levels"]["state"]["fps"]

        # А у живого воркера счётчик двигается — иначе тест выше был бы вакуумом
        # (он бы «проходил» и на реализации, которая не отдаёт cycles вовсе).
        svc.hb_services.worker_manager.source["w0"]["cycles"] = 1202
        third = cm.dispatch("introspect.telemetry")
        assert third["levels"]["workers"]["w0"]["cycles"] == 1202

    def test_worker_without_cycle_recorder_simply_has_no_field(self) -> None:
        """Воркер без `get_cycle_metrics` (не loop-раннер) — поля нет, команда цела."""
        svc, cm = _make(workers={"plain": {"status": "running", "effective_hz": 12.5}})

        levels = cm.dispatch("introspect.telemetry")["levels"]

        assert levels["workers"]["plain"]["effective_hz"] == 12.5
        assert "cycles" not in levels["workers"]["plain"]
