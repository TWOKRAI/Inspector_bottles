# -*- coding: utf-8 -*-
"""Независимая приёмка РТ-2 (flip default_enabled) — framework-половина (A4/A5/A6).

НЕЗАВИСИМЫЙ прогон: писался БЕЗ чтения plans/telemetry-stage6.md, plans/QUEUE.md,
git diff/log/show по ветке и БЕЗ чтения тестов автора
(test_telemetry_default_enabled_hazards.py / test_telemetry_default_enabled_acceptance.py).
Ожидаемые значения — литералы, взятые из чтения контрактных файлов, перечисленных в
задании (telemetry_publish_config.py, process_heartbeat.py, telemetry.py), а не
выведены вызовом кода, который тест проверяет.

РАЗДЕЛЕНИЕ НА ДВА ФАЙЛА (находка, см. отчёт тестера, раздел 3): задание просило один
файл здесь, но критерии A1/A2/A3 неотделимы от `multiprocess_prototype` (боевой
system.yaml, `build_throttle_rules`) — импорт prototype из framework запрещён
`.sentrux/rules.toml` (`[[boundaries]] from="multiprocess_framework/*"
to="multiprocess_prototype/*"`), правило не делает исключения для tests/. Поэтому:
    - ЗДЕСЬ (framework/.../tests/) — A4, A5, A6: чистая проверка контракта
      TelemetryPublishConfig/TelemetryGate/ProcessHeartbeat, без прототипа.
    - `multiprocess_prototype/backend/tests/test_rt2_config_flip_acceptance.py` —
      A1, A2, A3: то, что неотделимо от боевого system.yaml.

Критерии, закрываемые ЗДЕСЬ (буквально из задания):
    A4 — status/error/pid/uptime/paused/frozen НЕ зависят от default_enabled.
    A5 — introspect.telemetry → levels покрывает все имена, которые гейт может выключить.
    A6 — «нет секции» ≠ «default_enabled: false» ≠ «явное правило на имя» (три состояния).
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declare_metric,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.configs import TelemetryPublishConfig
from multiprocess_framework.modules.process_module.health import HealthState
from multiprocess_framework.modules.process_module.heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
    TelemetryGate,
    build_worker_telemetry,
    gated_metrics,
)

# ---------------------------------------------------------------------------
# Симуляция «процесс с плагином захвата» — БЕЗ импорта Plugins.sources.capture.plugin
# (там declare_metric зовётся в __init__ инстанса, а не при импорте модуля; поднимать
# камеру/симулятор ради каталога метрик непропорционально). Имена и сам факт трёх
# declare_metric — из задания (перечислены буквально как «для процесса с плагином
# захвата это восемь имён»), а не подсмотрены в plan/diff.
#
# ВАЖНО (правка после находки координатора, воспроизведено парой с
# test_plugin_levels_ownership_acceptance.py): observability_declarations._DECLARED —
# процессный ГЛОБАЛ, живущий весь pytest-прогон. Объявление МОДУЛЬНОГО уровня
# (было раньше) держит capture_fps/frame_count/drops под тестовым владельцем
# НАВСЕГДА — и в полном гейте реальный Plugins/sources/capture/plugin.py, объявляя
# те же имена под СВОИМ владельцем ("capture"), падает ValueError'ом на конфликте
# владельцев (_declare, observability_declarations.py:105). Поэтому объявление
# теперь — в фикстуре ниже, с обязательным forget_declarations(kind=KIND_METRIC,
# names=...) в teardown: убирает ТОЛЬКО эти три имени, чужие объявления не трогает
# (в отличие от forget_declarations() без аргументов — та чистит реестр целиком).
# ---------------------------------------------------------------------------
_SIM_CAPTURE_OWNER = "tester:rt2_acceptance:capture_plugin_sim"
_SIM_CAPTURE_METRIC_NAMES = ("capture_fps", "frame_count", "drops")


@pytest.fixture
def capture_plugin_metrics_declared() -> Iterator[str]:
    """Объявляет три capture-метрики под тестовым владельцем на время теста и
    гарантированно забывает их после — единственная форма, которая не портит
    соседей ни в этом файле, ни (что и обнаружилось) в полном прогоне гейта.
    """
    for name in _SIM_CAPTURE_METRIC_NAMES:
        declare_metric(name, owner=_SIM_CAPTURE_OWNER)
    try:
        yield _SIM_CAPTURE_OWNER
    finally:
        forget_declarations(kind=KIND_METRIC, names=_SIM_CAPTURE_METRIC_NAMES)


# Восемь имён из текста задания дословно (capture_fps/frame_count/drops —
# симулированные три; cycle_duration_ms/effective_hz/fps/latency_ms — telemetry.py;
# shm — process_heartbeat.py). Используется как МНОЖЕСТВО-ПОДМНОЖЕСТВО, которое
# gated_metrics() обязан содержать — НЕ как равенство (см. докстринг
# test_a5_gated_catalog_includes_the_eight_names_named_in_the_task про то, почему
# равенство неассертируемо в общем прогоне).
_GATED_CATALOG_LITERAL = frozenset(
    {
        "capture_fps",
        "cycle_duration_ms",
        "drops",
        "effective_hz",
        "fps",
        "frame_count",
        "latency_ms",
        "shm",
    }
)

# Поля, которыми publisher-gate НЕ владеет (инвариант плана «errors/status always-on»).
_ALWAYS_ON_NAMES = frozenset({"status", "error", "pid", "uptime", "paused", "frozen"})


# ---------------------------------------------------------------------------
# Минимальные дублёры IProcessServices — без поднятия процесса/IPC/Qt.
# ---------------------------------------------------------------------------
class _FakeServices:
    """Дублёр сервисов процесса — только то, что реально трогают тестируемые методы."""

    def __init__(self, name: str = "test_process") -> None:
        self.name = name
        self.worker_manager: Any = None
        self.router_manager: Any = None
        self._state_proxy: Any = None
        self._health_state: Any = None
        self._telemetry_config: dict | None = None

    def get_config(self, key: str, default: Any = None) -> Any:
        if key == "telemetry":
            return self._telemetry_config
        return default

    def log_info(self, *_a: Any, **_kw: Any) -> None:
        pass

    def log_debug(self, *_a: Any, **_kw: Any) -> None:
        pass

    def log_warning(self, *_a: Any, **_kw: Any) -> None:
        pass

    def send_message(self, *_a: Any, **_kw: Any) -> None:
        pass


class _FakeWorkerManager:
    def __init__(self, statuses: dict) -> None:
        self._statuses = statuses

    def get_all_workers_status(self) -> dict:
        return self._statuses


class _FakeRouter:
    """Пустая карта счётчиков — build_router_shm_telemetry всё равно вернёт ПОЛНЫЙ
    набор ключей с нулями (узкий аксессор читает через .get(key, 0))."""

    def __init__(self, stats: dict | None = None) -> None:
        self._stats = stats or {}

    def get_shm_stats(self) -> dict:
        return dict(self._stats)


class _RecordingProxy:
    """Фиксирует merge()/set() вызовы — без реального StateProxy/IPC."""

    def __init__(self) -> None:
        self.merges: list[tuple[str, dict]] = []
        self.sets: list[tuple[str, Any]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, data))

    def set(self, path: str, value: Any) -> None:
        self.sets.append((path, value))


# ===========================================================================
# A4 — status/error/pid/uptime/paused/frozen НЕ зависят от default_enabled
# ===========================================================================


def test_a4_worker_status_survives_a_fully_closed_gate() -> None:
    """A4: гейт не владеет полем status воркера. При ПОЛНОСТЬЮ закрытом гейте
    (allowed_metrics=set() — эквивалент default_enabled=False без единого
    включённого имени) status всё равно попадает в payload, а частотные
    метрики (effective_hz/cycle_duration_ms/агрегат state) — нет.

    Как упадёт: если status когда-нибудь заведут под тот же gate-guard, что
    hz/lat (регрессия рефакторинга build_worker_telemetry) — workers.w1
    перестанет содержать "status" при пустом allowed_metrics.
    """
    workers = {"w1": {"status": "running", "effective_hz": 30.0, "cycle_duration_ms": 12.0}}
    result = build_worker_telemetry(workers, "proc", allowed_metrics=set())
    assert result is not None
    _path, data = result
    assert data["workers"]["w1"]["status"] == "running"
    assert "effective_hz" not in data["workers"]["w1"]
    assert "cycle_duration_ms" not in data["workers"]["w1"]
    assert "state" not in data


def test_a4_health_error_publish_ignores_the_telemetry_gate() -> None:
    """A4: error (health) не проходит через publisher-gate вовсе.
    _publish_health_to_tree не принимает allowed_metrics и обязан доставить
    отчёт об ошибке в дерево, даже когда self._telemetry_gate наглухо закрыт
    (default_enabled=False, ни одного включённого имени).

    Как упадёт: если health когда-нибудь заведут под общий gate-параметр
    (архитектурная регрессия, слияние двух independent-каналов) — proxy.set
    по health-путям не будет вызван, и assert на непустой proxy.sets упадёт.
    """
    proxy = _RecordingProxy()
    health_state = HealthState()
    health_state.report_error(RuntimeError("boom"), context="test_a4")

    services = _FakeServices()
    services._state_proxy = proxy
    services._health_state = health_state

    hb = ProcessHeartbeat(services)
    closed_config = TelemetryPublishConfig.from_dict({"default_enabled": False})
    hb._telemetry_gate = TelemetryGate(closed_config)  # гейт наглухо закрыт руками

    hb._publish_health_to_tree()

    assert proxy.sets, "health/error не долетел до дерева при закрытом telemetry-гейте"
    published_paths = [path for path, _value in proxy.sets]
    assert any("health" in p for p in published_paths), published_paths


def test_a4_gate_catalog_never_lists_the_always_on_fields() -> None:
    """A4: гейт способен выключать ТОЛЬКО метрики из своего каталога (gated_metrics()).
    Если бы status/error/pid/uptime/paused/frozen туда попали — default_enabled=False
    погасил бы и их, что прямо запрещено инвариантом плана «errors/status always-on».

    Как упадёт: будущий declare_metric("status", ...) (или любое из пяти прочих
    always-on имён) молча протащит поле под гейт — пересечение множеств станет
    непустым, и assert покажет точное имя нарушителя.
    """
    overlap = _ALWAYS_ON_NAMES & set(gated_metrics())
    assert overlap == set()


# ===========================================================================
# A5 — introspect.telemetry → levels покрывает все гасимые гейтом имена
# ===========================================================================


def test_a5_gated_catalog_includes_the_eight_names_named_in_the_task(
    capture_plugin_metrics_declared: str,
) -> None:
    """A5 (предпосылка): каталог gated_metrics() для процесса с симулированным
    плагином захвата СОДЕРЖИТ все восемь имён, перечисленные в задании буквально
    (capture_fps, cycle_duration_ms, drops, effective_hz, fps, frame_count,
    latency_ms, shm) — подмножество, НЕ равенство.

    ПОЧЕМУ НЕ РАВЕНСТВО (правка после находки координатора, воспроизведено парой
    с test_plugin_levels_ownership_acceptance.py): gated_metrics() читает
    ПРОЦЕССНЫЙ ГЛОБАЛ (observability_declarations._DECLARED), который растёт
    ИМПОРТОМ и живёт весь pytest-прогон — это не баг, а ровно то, что утверждает
    сам критерий A5/устройство каталога (per-process, накопительный). В прогоне
    ОДНОГО файла глобал содержит только то, что импортировал этот файл, и
    равенство совпадает с восемью именами случайно. В ПОЛНОМ прогоне
    (python scripts/run_framework_tests.py) к этому моменту в каталоге уже лежат
    метрики, объявленные СОСЕДНИМИ тестовыми модулями (например,
    test_telemetry_gate.py объявляет "прикладная_метрика") — множество будет
    БОЛЬШЕ восьми, и равенство упадёт не из-за дефекта проверяемого свойства, а
    из-за того, что тест неявно требует «глобал чист», то есть охраняет ПОРЯДОК
    ЗАПУСКА тестов, а не заявленное свойство. Подмножество проверяет ровно то,
    что важно: восемь имён ТОЧНО присутствуют, независимо от того, кто ещё
    успел объявиться раньше.

    Как упадёт: если где-то во фреймворке уберут один из восьми declare_metric
    (или переименуют) — missing станет непустым, и assert назовёт точные имена.
    """
    missing = set(_GATED_CATALOG_LITERAL) - set(gated_metrics())
    assert missing == set(), f"каталог не содержит: {sorted(missing)}"


def test_a5_polled_levels_cover_every_name_the_gate_can_turn_off(
    capture_plugin_metrics_declared: str,
) -> None:
    """A5: множество имён, ДОСТУПНЫХ через introspect.telemetry → levels
    (ProcessHeartbeat.current_levels_snapshot), обязано ПОКРЫВАТЬ множество имён,
    которые гейт при default_enabled=False выключает (все восемь из
    _GATED_CATALOG_LITERAL). Опрос принципиально НЕ гейтуется
    (allowed_metrics=None внутри снимка, по докстрингу current_levels_snapshot) —
    показания обязаны быть видны даже когда push для этих же имён погашен.

    "levels" трактуется как ВЕСЬ payload снимка (state.* + workers.*.*), а не
    только подсекция state — effective_hz/cycle_duration_ms структурно лежат
    под workers.<w>.*, а не под state (см. build_worker_telemetry).

    Как упадёт: если какое-то из восьми имён структурно не может попасть в
    payload снимка (например, поменяли ключ, под которым plugin_levels отдаёт
    capture_fps, или current_levels_snapshot перестал звать один из трёх
    сборщиков) — missing будет непустым, и assert назовёт ровно эти имена.
    Это прямая проверка ЖИВОГО пробела: если она красная — А5 не выполнен, и
    это находка, а не хрупкость теста.
    """
    workers = {
        "cam_worker": {"status": "running", "effective_hz": 25.0, "cycle_duration_ms": 8.0},
    }
    services = _FakeServices()
    services.worker_manager = _FakeWorkerManager(workers)
    services.router_manager = _FakeRouter({})  # даже нули → непустой "shm" на опросе

    writer = capture_plugin_metrics_declared
    levels_store = PluginLevels()
    levels_store.publish("capture_fps", 24.7, writer)
    levels_store.publish("frame_count", 1234, writer)
    levels_store.publish("drops", 3, writer)
    setattr(services, PLUGIN_LEVELS_ATTR, levels_store)

    hb = ProcessHeartbeat(services)
    snapshot = hb.current_levels_snapshot()
    assert snapshot is not None, "current_levels_snapshot() вернул None — сенсоров нет вовсе"

    # Ф1 «порт наблюдений»: уровни плагинов лежат под state.plugins.<писатель>.<имя>,
    # агрегаты фреймворка — по-прежнему прямо в state. Собираем ИМЕНА ЛИСТЬЕВ с обоих
    # ярусов: критерий A5 про имена, которые гейт умеет выключать, а гейт матчит
    # по имени листа независимо от глубины пути.
    state_section = snapshot.get("state", {})
    observed_names: set[str] = set(state_section.keys()) - {"plugins"}
    for _writer, leaves in (state_section.get("plugins") or {}).items():
        observed_names |= set(leaves.keys())
    for _wname, wdata in snapshot.get("workers", {}).items():
        observed_names |= set(wdata.keys()) - {"status", "cycles"}

    missing = set(_GATED_CATALOG_LITERAL) - observed_names
    assert missing == set(), f"опрос НЕ показывает: {sorted(missing)} (наблюдалось: {sorted(observed_names)})"


# ===========================================================================
# A6 — «нет секции» ≠ «default_enabled: false» ≠ «явное правило на имя»
# ===========================================================================


def test_a6_missing_telemetry_section_means_no_gate_and_full_publish() -> None:
    """A6 (состояние 1 — «секции нет»): конфиг БЕЗ ключа "telemetry" вовсе ⇒ гейта
    нет (_build_telemetry_gate() is None), и это ДРУГОЕ состояние, чем
    default_enabled=False: там гейт есть и активно режет, здесь гейта нет вовсе,
    allowed_metrics для тика остаётся None ⇒ publish всё (обратная совместимость).

    Как упадёт: если «нет секции» когда-нибудь начнут трактовать как «всё
    выключено» (слияние состояний, прямо запрещённое A6) — либо
    _build_telemetry_gate() перестанет возвращать None на пустом конфиге
    (первый assert), либо build_worker_telemetry с allowed_metrics=None
    перестанет публиковать частотные метрики (второй/третий assert).
    """
    services = _FakeServices()  # _telemetry_config=None по умолчанию — ключа нет вовсе
    hb = ProcessHeartbeat(services)
    gate = hb._build_telemetry_gate()
    assert gate is None

    workers = {"w1": {"status": "running", "effective_hz": 10.0, "cycle_duration_ms": 5.0}}
    allowed_metrics = gate.due_metrics() if gate is not None else None
    result = build_worker_telemetry(workers, "proc", allowed_metrics)
    assert result is not None
    _path, data = result
    assert data["workers"]["w1"]["effective_hz"] == 10.0
    assert data["state"]["fps"] == 10.0


def test_a6_explicit_per_metric_rule_beats_default_enabled_false() -> None:
    """A6 (состояния 2 и 3 — не сливаются): «default_enabled: false» (белый список)
    и «явное правило metrics.<имя>.enabled: true» (точечное включение) для ОДНОГО
    и того же имени метрики обязаны давать РАЗНЫЙ результат — иначе точечный
    override не имел бы смысла, а два разных состояния конфига схлопнулись бы
    в одно наблюдаемое поведение.

    Как упадёт: если explicit metrics.<имя>.enabled=true начнёт игнорироваться
    при default_enabled=False (регрессия резолва/слияние состояний) — второй
    assert (enabled_with_override is True) упадёт, хотя первый (enabled_no_override
    is False) останется зелёным, что и укажет: сломался именно override, а не сам флип.
    """
    cfg_whitelist = TelemetryPublishConfig.from_dict({"default_enabled": False})
    enabled_no_override, _ = cfg_whitelist.resolve("custom_metric_x")
    assert enabled_no_override is False

    cfg_override = TelemetryPublishConfig.from_dict(
        {"default_enabled": False, "metrics": {"custom_metric_x": {"enabled": True}}}
    )
    enabled_with_override, _ = cfg_override.resolve("custom_metric_x")
    assert enabled_with_override is True
