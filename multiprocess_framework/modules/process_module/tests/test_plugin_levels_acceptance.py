# -*- coding: utf-8 -*-
"""Независимые приёмочные тесты Task 3.5 (`plans/telemetry-stage6.md`).

Пишутся ДО реализации, от текста задачи, полученного напрямую в постановке (не из
`interface.py` — он в списке запрещённых к чтению файлов для этой роли, как и
`plugins/base.py`, `heartbeat/telemetry.py`, `heartbeat/process_heartbeat.py`,
`Plugins/sources/capture/plugin.py` и авторские `test_levels_*`/`test_plugin_levels_*`).

Контракт (дословно из постановки):
  - `ctx.declare_metric(name)` — объявляет уровень; владелец = имя плагина; тот же
    реестр `observability_declarations` (плоскость `KIND_METRIC`), второго не заводить.
  - `ctx.publish_metric(name, value)` — отдаёт текущее значение уровня.
  - Значение собирает сборщик телеметрийного тика процесса → дерево
    `processes.<процесс>.state.<name>`, под тем же publisher-gate, что и штатные
    метрики. Тот же сборщик обслуживает `introspect.telemetry` (секция `levels`).

Что ПРИШЛОСЬ предположить (см. также раздел «сомнения в контракте» в отчёте тестера):
  1. Метод-триггер тика на `ProcessHeartbeat` назван `_publish_plugin_levels_to_tree`
     по конвенции соседних `_publish_metrics_to_tree` / `_publish_router_shm_stats_to_tree`
     / `_publish_health_to_tree` (все три — реальные, уже существующие методы). Если
     разработчик назвал иначе, `_run_plugin_levels_tick` ниже упадёт с ЯВНЫМ
     сообщением, а не тихим `AttributeError` без контекста.
     ОБНОВЛЕНО Р3.5-12 (2026-08-16): три публикатора тика схлопнуты в один,
     `_publish_telemetry_to_tree`. Догадка тестера была верна для своего времени;
     свойства, которые он сторожил, не изменились — изменился адрес их вызова.
  2. Владелец объявления передаётся `PluginContext` через `plugin_name=...` в
     конструкторе. Если это не так — `TestDeclareConflict._make_ctx` падает с
     сообщением, что нужно переписать способ различения владельцев.

Оба предположения — ЛУЧШЕЕ, что можно вывести без чтения `interface.py`; расхождение
с реальной реализацией — не шум, а находка (см. отчёт).
"""

from __future__ import annotations

import pathlib
from typing import Any, Optional

import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)


# --------------------------------------------------------------------------- #
# Реестр observability_declarations — процессный, общий на все тесты модуля.
# Снимок/восстановление по конвенции, уже принятой в test_telemetry_gate.py.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _metric_registry_guard():
    from multiprocess_framework.modules.observability_declarations import (
        KIND_METRIC,
        declared_metrics,
        forget_declarations,
    )

    before = set(declared_metrics())
    yield
    # ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, Р3.5-11): точечно, а не сплошной очисткой
    # с восстановлением. Прежняя форма возвращала имена, но с ЧУЖИМ владельцем
    # ("test_restore_..."), и с приходом проверки владения (build_plugin_levels
    # сверяет публикатора с владельцем имени) это перестало быть косметикой:
    # после такого teardown `fps` числился бы за тестом, а не за фреймворком, и
    # соседние тесты судили бы подменённый реестр. См. docstring forget_declarations.
    forget_declarations(KIND_METRIC, names=set(declared_metrics()) - before)


# --------------------------------------------------------------------------- #
# Общий тестовый носитель: одновременно годится и как services для
# PluginContext (см. test_plugin_context_protocol.py), и как services для
# ProcessHeartbeat + BuiltinCommands (см. test_telemetry_gate.py /
# test_introspect_telemetry.py). Собран из ТЕХ ЖЕ полей, что уже используются
# этими соседними тестовыми файлами — не нового изобретения ради.
# --------------------------------------------------------------------------- #
class _StateProxy:
    """Мини-дерево состояния: set/merge пишут в plain dict по точечному пути."""

    def __init__(self) -> None:
        self.tree: dict[str, Any] = {}
        self.set_calls = 0
        self.merge_calls = 0

    def _node(self, path: str) -> dict[str, Any]:
        node = self.tree
        for part in path.split("."):
            node = node.setdefault(part, {})
        return node

    def set(self, path: str, value: Any) -> None:
        self.set_calls += 1
        *head, last = path.split(".")
        node = self.tree
        for part in head:
            node = node.setdefault(part, {})
        node[last] = value

    def merge(self, path: str, data: dict) -> None:
        self.merge_calls += 1
        self._node(path).update(data)

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: Optional[dict] = None) -> dict:
        return self.handlers[command](data or {})


class _ProcServices:
    """Один носитель на оба use-case: PluginContext.services И ProcessHeartbeat._services."""

    def __init__(self, *, name: str = "proc") -> None:
        self.name = name
        self.worker_manager = None
        self.memory_manager = None
        self.router_manager = None
        self.command_manager = _FakeCommandManager()
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self._config: dict = {}
        self._state_proxy = _StateProxy()
        self._state_store_manager = None
        self._heartbeat: Optional[ProcessHeartbeat] = None
        self.logs: list[dict] = []
        self.sent_messages: list[dict] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_info(self, msg: str, **k) -> None:
        self.logs.append({"level": "INFO", "msg": msg})

    def log_debug(self, msg: str, **k) -> None:
        self.logs.append({"level": "DEBUG", "msg": msg})

    def log_warning(self, msg: str, **k) -> None:
        self.logs.append({"level": "WARNING", "msg": msg})

    def log_error(self, msg: str, **k) -> None:
        self.logs.append({"level": "ERROR", "msg": msg})

    # ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, расхождение Р-1 отчёта teamlead'а).
    # Дубль тестера нёс четыре log_*, а PluginContext требует ПЯТЬ: конструктор
    # делает self.log_critical = self._stamped(services.log_critical) без getattr-
    # фолбэка, и это НАМЕРЕННО — фолбэк открыл бы обратно дефект A2/Б-2, где
    # ctx.log_warning ронял старт захвата. Пропуск пятого метода ронял четыре
    # теста задачи 3.5 в AttributeError ДО первой проверяемой строки, то есть
    # прятал результат за дефектом харнеса. Добавлен пятый — тест не ослаблен,
    # починен носитель.
    def log_critical(self, msg: str, **k) -> None:
        self.logs.append({"level": "CRITICAL", "msg": msg})

    # BuiltinCommands (в отличие от ProcessHeartbeat) зовёт _log_info/_log_debug
    # с подчёркиванием — см. test_introspect_telemetry.py._FakeServices. Нужны оба
    # набора имён, раз один носитель играет обе роли.
    def _log_info(self, *a, **k) -> None:
        pass

    def _log_debug(self, *a, **k) -> None:
        pass

    def send_message(self, target: str, message: dict) -> bool:
        self.sent_messages.append({"target": target, "message": message})
        return True

    def receive_message(self, timeout: Optional[float] = None) -> Optional[dict]:
        return None


def _boot(name: str = "proc") -> tuple[_ProcServices, ProcessHeartbeat]:
    services = _ProcServices(name=name)
    hb = ProcessHeartbeat(services)
    services._heartbeat = hb
    return services, hb


def _run_plugin_levels_tick(hb: ProcessHeartbeat, *, allowed_metrics=None):
    """Триггер тика-сборщика уровней плагина. Имя метода — ЛУЧШАЯ ДОГАДКА (см. докстринг
    модуля) по конвенции соседей. Отсутствие атрибута = отдельная, явная причина
    падения — не путать с обычным ``AttributeError`` без контекста.
    """
    fn = getattr(hb, "_publish_telemetry_to_tree", None)
    if fn is None:
        pytest.fail(
            "ProcessHeartbeat не предоставляет '_publish_telemetry_to_tree' — сборщик телеметрии тика не подключён"
        )
    # Воркеров нет намеренно: этот файл судит УРОВЕНЬ, а не агрегат. До Р3.5-12
    # уровни ехали своим merge; теперь их несёт общий payload тика, и пустой
    # снимок воркеров его не отменяет (ровно ловушка №1 объединения — ранний
    # выход по `not workers` не имеет права проглотить уровни и shm).
    return fn({}, allowed_metrics=allowed_metrics)


def _dispatch_introspect_telemetry(services: _ProcServices) -> dict:
    bc = BuiltinCommands(services)
    bc._register_introspect_commands()
    return services.command_manager.dispatch("introspect.telemetry")


def _polled_level(polled: dict, name: str):
    """Достать уровень из ответа опроса по ФАКТИЧЕСКОЙ форме секции ``levels``.

    ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, расхождение Р-2 отчёта teamlead'а).
    Тестер предположил плоскую форму ``levels[name]`` — «симметрично resolved».
    Форма другая и симметрия у неё иная: уровень лежит там же, где штатный ``fps``,
    то есть ``levels["state"][name]`` (``levels`` = ``{"workers": {...},
    "state": {...}}``). Спека говорила «наравне с fps/latency_ms» — вот это место.

    Плоская форма не просто отличалась бы — она СЛОМАЛА бы свойство, которое сам
    тест защищает: ``TelemetryPoller._flatten_levels`` склеивает ключи ответа с
    префиксом ``processes.<name>``, поэтому плоское имя уехало бы в
    ``processes.<p>.<имя>`` — мимо пути ``processes.<p>.state.<имя>``, которым его
    пишет push. То есть «push и poll совпадают» перестало бы выполняться именно
    из-за формы, выбранной ради удобства проверки.

    Модель тестера была неверна — это находка, а не шум, и она записана здесь,
    а не молча исправлена.
    """
    return ((polled.get("levels") or {}).get("state") or {}).get(name)


# --------------------------------------------------------------------------- #
# Критерий 1 — одна дорога: push (тик → дерево) и poll (introspect.telemetry.levels)
# обязаны совпасть составом ключей и значением.
# --------------------------------------------------------------------------- #
class TestSingleRoadPushEqualsPoll:
    def test_pushed_value_matches_polled_value(self):
        services, hb = _boot(name="cam0")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("custom_quality")
        ctx.publish_metric("custom_quality", 42.0)

        _run_plugin_levels_tick(hb, allowed_metrics=None)
        pushed = services._state_proxy.get("processes.cam0.state.custom_quality")
        assert pushed == 42.0, (
            f"push: ожидали 42.0 в дереве по processes.cam0.state.custom_quality, получили {pushed!r}"
        )

        polled = _dispatch_introspect_telemetry(services)
        assert "levels" in polled, "introspect.telemetry не отдаёт секцию 'levels'"
        assert _polled_level(polled, "custom_quality") == 42.0, (
            f"poll разошёлся с push: дерево содержит 42.0, poll отдал "
            f"{_polled_level(polled, 'custom_quality')!r} — расхождение состава/значения ключей"
        )

    def test_builtin_metrics_share_the_same_levels_section(self):
        """«наравне со штатными fps/latency_ms» — уровень плагина лежит В ТОЙ ЖЕ секции.

        ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, расхождение Р-4 отчёта teamlead'а).
        Исходный тест падал `TypeError: 'NoneType' is not iterable`: на процессе без
        воркеров и router'а `levels` = ``None``, и это КОНТРАКТ (ADR-PM-035: «None =
        сенсоров нет», отличается от «команда не сработала»), а не дефект.
        Хуже другое: единственное его утверждение было `issuperset(set())` — истина
        для любого множества, включая пустое. Тест ничего не проверял и при живом
        `levels` был бы зелен на чём угодно.
        Переписан на настоящее свойство: уровень плагина обязан лежать в ТОЙ ЖЕ
        секции ``state``, где сборщик держит штатные метрики, — иначе «наравне» не
        выполнено, а `TelemetryPoller._flatten_levels` уведёт его мимо пути push'а.
        """
        services, hb = _boot(name="cam0b")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("neighbour_level")
        ctx.publish_metric("neighbour_level", 3.0)
        _run_plugin_levels_tick(hb, allowed_metrics=None)

        polled = _dispatch_introspect_telemetry(services)
        levels = polled.get("levels")
        assert isinstance(levels, dict), f"ожидали непустую секцию levels при наличии показаний, получили {levels!r}"
        state_section = levels.get("state") or {}
        assert state_section.get("neighbour_level") == 3.0, (
            f"уровень плагина обязан лежать в levels['state'] рядом со штатными "
            f"метриками; секция state = {state_section!r}"
        )


# --------------------------------------------------------------------------- #
# Критерий 2 — гейт накрывает объявленный уровень. ПАРА: закрыт→ноль, открыт→ненулевое.
# --------------------------------------------------------------------------- #
class TestGatePairsClosedAndOpen:
    def test_gate_closed_hides_then_open_reveals(self):
        services, hb = _boot(name="cam1")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("custom_level_gated")
        ctx.publish_metric("custom_level_gated", 7.0)

        hb.reconfigure_telemetry({"metrics": {"custom_level_gated": {"enabled": False}}})
        allowed_off = hb._telemetry_gate.due_metrics(now=0.0)
        _run_plugin_levels_tick(hb, allowed_metrics=allowed_off)
        assert services._state_proxy.get("processes.cam1.state.custom_level_gated") is None, (
            "гейт закрыт, а значение всё равно попало в дерево — подтверждающий ноль "
            "не защита, если он не парный: закрытый гейт обязан ДАВАТЬ ноль наблюдаемо"
        )
        off_poll = _dispatch_introspect_telemetry(services)
        # ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, расхождение Р-3 отчёта teamlead'а).
        # Тестер утверждал ОБРАТНОЕ: «закрытый гейт: poll всё равно отдаёт уровень»
        # как дефект. Это неверная модель, и она противоречит ADR-PM-035 и приёмке
        # 3.3 этого же плана: гейт управляет PUSH'ем, а не тем, что процесс знает о
        # себе; опрос обязан работать ИМЕННО при закрытом гейте — иначе флип РТ-2
        # ослепляет вкладку, ради которой опрос и заводился.
        # Его утверждение проходило СЛУЧАЙНО — из-за неверной формы (Р-2): имени не
        # было на верхнем уровне ответа, и проверка «not in» зеленела ни на чём.
        # Асимметрия push/poll здесь — контракт, и теперь она проверяется как контракт.
        assert _polled_level(off_poll, "custom_level_gated") == 7.0, (
            "закрытый гейт обязан ГАСИТЬ PUSH и НЕ гасить опрос (ADR-PM-035): "
            f"опрос отдал {_polled_level(off_poll, 'custom_level_gated')!r} вместо 7.0"
        )

        hb.reconfigure_telemetry({"metrics": {"custom_level_gated": {"enabled": True}}, "telemetry_mode": "merge"})
        allowed_on = hb._telemetry_gate.due_metrics(now=1.0)
        _run_plugin_levels_tick(hb, allowed_metrics=allowed_on)
        pushed = services._state_proxy.get("processes.cam1.state.custom_level_gated")
        assert pushed == 7.0, (
            f"гейт открыт — ожидали ненулевое 7.0 в дереве, получили {pushed!r}. "
            f"Без этой половины пары закрытый-ноль ничего не доказывает: он одинаков "
            f"и когда механизм вообще не подключён"
        )
        on_poll = _dispatch_introspect_telemetry(services)
        assert _polled_level(on_poll, "custom_level_gated") == 7.0


# --------------------------------------------------------------------------- #
# Критерий 3 — фреймворк не знает прикладных имён.
#
# ВАЖНО (см. «сомнения в контракте» в отчёте): слепой grep всех четырёх слов по
# ВСЕМУ дереву фреймворка уже красный ДО Task 3.5 — 'paused'/'frozen'/'drops'
# легитимно живут в фреймворке по не связанным с этой задачей причинам
# (ProcessStatus.PAUSED, dataclass(frozen=...), счётчики ring_buffer/alert_rules).
# Проверено грепом перед написанием теста. Поэтому:
#   - 'frame_count' — единственное чистое слово, проверяется по ВСЕМУ дереву;
#   - 'drops'/'frozen' — сужены до поверхности задачи (plugins/, heartbeat/,
#     observability_declarations.py), где оба тоже сейчас чисты;
#   - 'paused' не проверяется вовсе — уже легитимно в plugins/base.py (жизненный
#     цикл плагина), слепой grep не отличит его от прикладного флага camera capture.
# Исключение: каталоги tests/ (по всему дереву) — авторские и наши же тесты.
# --------------------------------------------------------------------------- #
_FRAMEWORK_ROOT = pathlib.Path(__file__).resolve().parents[3]
assert _FRAMEWORK_ROOT.name == "multiprocess_framework", _FRAMEWORK_ROOT


def _grep_literal(roots: list[pathlib.Path], literal: str) -> list[pathlib.Path]:
    hits: list[pathlib.Path] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for f in files:
            if "tests" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if literal in text:
                hits.append(f)
    return hits


class TestFrameworkDoesNotKnowAppNames:
    """ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, расхождение Р-5 отчёта teamlead'а).

    Три grep-теста сняты и заменены ОДНИМ положительным свойством. Причина —
    оракул давал 100 % ложных срабатываний, и это проверено поимённо:

      * `drops` находился в ``heartbeat/telemetry.py:241`` — как подстрока
        ``frame_stale_drops``, счётчика SHM САМОГО фреймворка;
      * `frame_count` находился в ``plugins/base.py:1188`` — как подстрока
        ``frame_counter`` внутри ДОКСТРИНГА.

    Ни одно из двух не является прикладным именем в коде. Слепой grep по слову не
    отличает докстринг от кода и не отличает целое слово от подстроки, а `paused`/
    `frozen` живут во фреймворке законно (``ProcessStatus.PAUSED``,
    ``dataclass(frozen=True)``) — тестер сам это назвал сомнением в контракте, и
    сомнение оказалось верным.

    Заменяющее свойство сильнее отрицательного грепа: механизм с зашитым списком
    имён проваливает его ПО ПОСТРОЕНИЮ, потому что выдуманного имени в списке быть
    не может. Отрицание «имени нет в коде» доказывает меньше, чем утверждение
    «любое имя работает».
    """

    def test_a_name_that_exists_nowhere_in_the_repo_still_arrives(self):
        services, hb = _boot(name="cam2")
        ctx = PluginContext(services=services, config={})
        # Имя БЕЗ точек — намеренно. Точечное имя ("zzz.made.up.level") тоже доезжает,
        # но ложится ЛИТЕРАЛЬНЫМ ключом ``state["zzz.made.up.level"]``, а не вложенными
        # узлами; проверено разведением 2026-08-16. Это отдельный вопрос (имена stats-
        # плоскости в проекте точечные: capture.frames), он записан резидуалом задачи и
        # к свойству универсальности отношения не имеет — тест судил бы форму пути
        # вместо «фреймворк не знает имён».
        made_up = "zzz_made_up_level"

        # Страж самого оракула: имя обязано отсутствовать в дереве фреймворка,
        # иначе тест перестал бы проверять универсальность и стал бы проверять
        # «имя уже зашито».
        assert _grep_literal([_FRAMEWORK_ROOT], made_up) == [], (
            f"{made_up!r} встречается во фреймворке — выдуманное имя перестало быть выдуманным"
        )

        ctx.declare_metric(made_up)
        # 1.2, а не 1.25: сборщик округляет до 1 знака (ADR-PM-035, то же и на опросе),
        # и round(1.25, 1) = 1.2 — литерал 1.25 проверял бы округление, а не универсальность.
        # Округление имеет собственный тест (критерий 7).
        ctx.publish_metric(made_up, 1.2)
        _run_plugin_levels_tick(hb, allowed_metrics=None)

        pushed = services._state_proxy.get(f"processes.cam2.state.{made_up}")
        assert pushed == 1.2, f"push: выдуманное имя не доехало в дерево ({pushed!r}) — признак зашитого списка имён"
        assert _polled_level(_dispatch_introspect_telemetry(services), made_up) == 1.2, (
            "poll: выдуманное имя не доехало в опрос — push и poll разошлись"
        )


# --------------------------------------------------------------------------- #
# Критерий 4 — SubPluginContext несёт ОБЕ дороги и они РАБОТАЮТ (не только по имени).
# --------------------------------------------------------------------------- #
class TestSubPluginContextCarriesBothRoads:
    def test_default_sub_context_is_a_named_noop_not_an_error(self):
        sub = SubPluginContext()
        # Своей плоскости у вложенного контекста без родителя нет — но это должно
        # быть названным no-op (по аналогии с write_document), а не AttributeError.
        sub.declare_metric("x")
        sub.publish_metric("x", 1.0)

    def test_parent_can_hand_both_roads_down_and_they_actually_work(self):
        services, hb = _boot(name="cam3")
        parent = PluginContext(services=services, config={})

        # ПРАВКА ВЛАДЕЛЬЦА СПЕКИ (2026-08-16, находка ИНЪЕКЦИИ И4, а не чтения).
        # Здесь стояла ручная сборка `SubPluginContext(declare_metric=parent.declare_metric,
        # publish_metric=parent.publish_metric)`. Она проверяла делегирование, но НЕ
        # трогала `from_parent` — то самое перечисление дорог, которое урок Н-6 велит
        # держать в одном месте и которое ломается на практике. Инъекция «обе дороги
        # убраны из from_parent» оставляла этот тест ЗЕЛЁНЫМ: он собирал контекст в
        # обход боевой дороги, то есть доказывал собственную проводку теста.
        # Переведён на `from_parent` — теперь инъекция красит его поимённо.
        sub = SubPluginContext.from_parent(parent)
        sub.declare_metric("sub_level")
        sub.publish_metric("sub_level", 3.5)

        _run_plugin_levels_tick(hb, allowed_metrics=None)
        pushed = services._state_proxy.get("processes.cam3.state.sub_level")
        assert pushed == pytest.approx(3.5), (
            "SubPluginContext.declare_metric/publish_metric присутствуют по имени, но "
            "не делегируют в реальный механизм родителя — значение не дошло до дерева. "
            "Оракул обязан читать протокол (эффект), а не список литералов (наличие атрибута)"
        )


# --------------------------------------------------------------------------- #
# Критерий 5 — отключаемость: без настроенной телеметрии publish_metric — no-op.
# --------------------------------------------------------------------------- #
class TestNoOpWithoutTelemetryConfigured:
    def test_publish_metric_is_a_named_noop_without_telemetry(self):
        services = MockProcessServices(name="bare")  # без heartbeat, без state_proxy
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("orphan_level")
        # Не должно бросать ни AttributeError, ни любое другое исключение.
        ctx.publish_metric("orphan_level", 1.0)

    def test_default_sub_plugin_context_publish_metric_is_noop(self):
        SubPluginContext().publish_metric("orphan_sub_level", 2.0)


# --------------------------------------------------------------------------- #
# Критерий 6 — конфликт объявлений: разные владельцы = отказ; тот же владелец = не конфликт.
#
# Предположение (см. докстринг файла): владелец передаётся PluginContext через
# plugin_name=... в конструкторе. Если это не так — _make_ctx падает с явным
# сообщением вместо того, чтобы тихо утвердить неверный контракт.
# --------------------------------------------------------------------------- #
class TestDeclareConflict:
    def _make_ctx(self, *, plugin_name: str, process_name: str = "conflict_proc") -> PluginContext:
        services = MockProcessServices(name=process_name)
        try:
            return PluginContext(services=services, config={}, plugin_name=plugin_name)
        except TypeError as exc:
            pytest.fail(
                f"PluginContext(..., plugin_name={plugin_name!r}) -> TypeError: {exc}. "
                "Тест предполагает, что владелец объявления — параметр конструктора "
                "'plugin_name' (interface.py скрыт от независимого тестера, это лучшая "
                "догадка). Если владелец берётся иначе — переписать этот тест под "
                "реальный способ различения владельцев."
            )

    def test_two_different_owners_conflict(self):
        ctx_a = self._make_ctx(plugin_name="plugin_a")
        ctx_b = self._make_ctx(plugin_name="plugin_b")
        ctx_a.declare_metric("shared_name")
        with pytest.raises(ValueError):
            ctx_b.declare_metric("shared_name")

    def test_same_owner_redeclared_is_not_a_conflict(self):
        ctx_a = self._make_ctx(plugin_name="plugin_a2")
        ctx_a.declare_metric("shared_name_2")
        ctx_a.declare_metric("shared_name_2")  # повторное объявление тем же владельцем — не конфликт


# --------------------------------------------------------------------------- #
# Критерий 7 — единица и форма: округление сборщика до 1 знака, значение — как отдано.
# --------------------------------------------------------------------------- #
class TestValueRoundingObservedAtOneDecimal:
    def test_value_rounds_to_one_decimal_in_tree_and_poll(self):
        services, hb = _boot(name="cam2")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("custom_precise")
        ctx.publish_metric("custom_precise", 15.34)

        _run_plugin_levels_tick(hb, allowed_metrics=None)
        pushed = services._state_proxy.get("processes.cam2.state.custom_precise")
        assert pushed == pytest.approx(15.3), f"округление сборщика: ожидали 15.3, получили {pushed!r}"

        polled = _dispatch_introspect_telemetry(services)
        assert _polled_level(polled, "custom_precise") == pytest.approx(15.3), (
            f"poll не согласован с push по округлению: получили {_polled_level(polled, 'custom_precise')!r}"
        )
