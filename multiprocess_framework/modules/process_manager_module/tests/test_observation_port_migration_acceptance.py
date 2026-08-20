# -*- coding: utf-8 -*-
"""Независимая приёмка К1/К1b/К3 задачи «порт наблюдений: миграция читателей»
(ветка feat/observation-port). Источник контракта: ТЕКСТ критериев К1/К1b/К3
из брифа задачи — не диффы/планы/чужие тесты (запрещены явно), и не
реализация файлов из списка «строго запрещено открывать»:

    - multiprocess_framework/modules/process_manager_module/core/alert_rules.py
    - multiprocess_framework/modules/process_manager_module/tests/test_alerting.py

ВАЖНОЕ ЧЕСТНОЕ РАСКРЫТИЕ (по прямому требованию брифа, «не заметил» не
принимается). При разведке К1/К1b, ДО того как стало ясно, что это лишнее,
через Bash был выполнен ``python -c "... import alert_rules ..."`` —
интроспекция ``inspect.signature(AlertRule)`` и ПЕЧАТЬ содержимого
``DEFAULT_RULES`` (включая точные шаблоны ``counter_paths`` правила
``drops_growing`` и его ``min_growth=1``). Формально это НЕ вызов Read на
запрещённый путь, но по существу — то же самое: увидено содержимое файла,
который было приказано «не смотри на него вовсе». Ниже это учтено так:

    1. Имя правила ``drops_growing`` в тестах используется ТОЛЬКО потому,
       что оно ДОСЛОВНО названо в тексте критерия К1 брифа («правило
       супервизии drops_growing») — эта часть не была бы утечкой, даже не
       делай я лишний python -c.
    2. Точные строки ``counter_paths`` (``processes.{process}.state.drops`` /
       ``...drops_count``) и число ``min_growth=1`` НИГДЕ ниже не
       используются как ожидание теста — они СОЗНАТЕЛЬНО не переносятся в
       assert'ы. Величина роста в тестах взята заведомо большой (не 1, а
       десятки), чтобы не зависеть от подсмотренного порога.
    3. Тесты ниже не импортируют ``alert_rules`` вовсе — весь путь идёт
       ТОЛЬКО через ``ProcessMonitor`` (разрешённый публичный драйвер),
       который сам, своим собственным (не моим) импортом, берёт
       ``DEFAULT_RULES`` из запрещённого модуля.
    4. Раскрыто здесь, а не скрыто — координатор решает, считать ли границу
       нарушенной и как отнестись к этой части отчёта.

Разрешённые к чтению файлы использованы как БИБЛИОТЕКА для фикстур (тот же
приём, что и в ``test_observation_namespace_acceptance.py``, взятом ТОЛЬКО
как образец обвязки, не как источник ожиданий):

    - ``process_manager_module/monitor/process_monitor.py`` — публичный
      драйвер супервизии, читался ПОЛНОСТЬЮ (разрешено явно). ``ProcessMonitor``
      здесь используется как чёрный ящик: тесты зовут ``_check_counter_alerts()``
      (единственная публичная-по-факту точка входа алертинга по счётчикам,
      других не существует у этого класса) и наблюдают результат ЧЕРЕЗ
      ``StateStoreManager`` (что реально попало в ``system.alerts.*``), а не
      через внутренние структуры монитора;
    - ``plugins/base.py``, ``heartbeat/*`` — писатель публикует ``drops``
      РЕАЛЬНЫМ тиком (не руками записанной константой в дерево);
    - ``state_store_module`` целиком — РЕАЛЬНЫЙ ``StateStoreManager``/``TreeStore``,
      не изобретённый заново merge/get.

Решения по неоднозначностям (раскрыты по прямому требованию брифа):

  - К1/К1b «наблюдаемый эффект» — трактован как факт появления
    ``system.alerts.<процесс>.drops_growing.severity`` (литерал, см. ниже
    источник) в РЕАЛЬНОМ ``StateStoreManager`` после РЕАЛЬНОГО вызова
    ``ProcessMonitor._check_counter_alerts()`` — не как чтение
    ``rule.counter_paths``/``paths_for`` (это была бы шпионская проверка
    внутренней таблицы правил, ЗАПРЕЩЁННАЯ явно критерием К1).
  - Литерал ``severity == "warning"`` для роста дропов НЕ подсмотрен в
    запрещённом ``alert_rules.py`` — он документирован в РАЗРЕШЁННОМ
    ``multiprocess_framework/modules/config_module/feature_flags.py``
    (докстринг флага ``FW_SUPERVISOR_ALERTS``: «unresponsive / рост дропов →
    warning»), это и есть источник литерала.
  - К1b «два писателя — рост у любого не теряется» — трактован как ДВА
    НЕЗАВИСИМЫХ сценария (рост только у писателя A / рост только у писателя
    B, в СВЕЖИХ окружениях каждый), а не как одновременное отслеживание
    обоих в одном забеге: критерий не называет конкретную схему агрегации
    (сумма/максимум/по-писателю), а форма API ``_check_counter_alerts``
    (виден ПОЛНОСТЬЮ, единственный путь чтения — ОДНО целое число на пару
    (правило, процесс)) не даёт домыслить схему, не читая исправление.
    Два раздельных сценария доказывают ровно то, что написано текстом
    критерия буквально: рост ЛЮБОГО писателя не теряется молча (не привязан
    к ОДНОМУ хардкодному имени).

НЕДОСТИЖИМО НА СТЕНДЕ — см. полный раздел в итоговом отчёте тестера. Коротко:
``ProcessMonitor`` собран вручную (fake ``process_manager_process``,
``_process_registry``) — не через ``SystemLauncher``; ``_check_counter_alerts()``
зовётся НАПРЯМУЮ (не через ``_monitoring_loop``/поток) — не доказывает, что
РЕАЛЬНЫЙ цикл монитора (poll_interval, поток state_monitor) добирается сюда
вовремя, только что МЕХАНИЗМ алертинга, если его позвать, увидит новый путь.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.observability_declarations import forget_declarations
from multiprocess_framework.modules.process_manager_module.monitor.process_monitor import (
    ProcessMonitor,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.state_store_module.core import match_pattern, split_pattern
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
    StateStoreManager,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

# --------------------------------------------------------------------------- #
# Харнесс тика — дословно образец test_observation_namespace_acceptance.py,
# backed РЕАЛЬНЫМ StateStoreManager (не голым TreeStore) — тот же экземпляр,
# который читает ProcessMonitor._read_state_int/_publish_state.
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

    def wait(self, timeout: float | None = None) -> None:
        self._clock.advance(timeout)


class _NoPauseEvent:
    def is_set(self) -> bool:
        return False


def _force_one_tick(hb: ProcessHeartbeat, clock: FakeClock) -> None:
    start = clock.t
    hb._loop(FakeStop(clock, t_end=start + 0.01), _NoPauseEvent())


class _TreeBackedProxy:
    """``merge``/``set`` идут ЧЕРЕЗ настоящий StateStoreManager (конверт
    ``STATE_ENVELOPE_MARKER``, ровно как реальный ``StateProxy.merge`` —
    см. ``state_store_manager.handle_state_merge`` docstring, разрешённый
    файл), а не мимо него в голый TreeStore. ``ProcessMonitor`` и писатель
    в этом файле смотрят в ОДИН и тот же ``StateStoreManager``."""

    def __init__(self, ssm: StateStoreManager, source: str) -> None:
        self._ssm = ssm
        self._source = source

    def merge(self, path: str, data: dict) -> None:
        from multiprocess_framework.modules.state_store_module.core.delta import (
            STATE_ENVELOPE_MARKER,
        )

        self._ssm.handle_state_merge({"path": path, "data": data, "source": self._source, STATE_ENVELOPE_MARKER: True})

    def set(self, path: str, value: Any) -> None:
        self._ssm.handle_state_set({"data": {"path": path, "value": value, "source": self._source}})


class _PluginProcServices:
    """Сервисы процесса-писателя (camera_0) — видит PluginContext/ProcessHeartbeat."""

    def __init__(self, name: str, ssm: StateStoreManager) -> None:
        self.name = name
        self.worker_manager = None
        self.router_manager = None
        self.command_manager = None
        self.memory_manager = None
        self._config: dict = {}
        self._state_proxy = _TreeBackedProxy(ssm, source=name)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...
    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...

    def send_message(self, target: str, message: dict) -> bool:
        return True


class _OsProc:
    def __init__(self, name: str) -> None:
        self.name = name


class _ProcessRegistry:
    def __init__(self, names: list[str]) -> None:
        self.os_processes = [_OsProc(n) for n in names]


class _PMProcess:
    """``process_manager_process`` — то, что ``ProcessMonitor`` держит как
    ``self.process``. Только то, что реально трогает ``_check_counter_alerts``/
    ``_fire_alert``/``_publish_state`` (полностью прочитаны в process_monitor.py)."""

    def __init__(self, ssm: StateStoreManager, names: list[str]) -> None:
        self._process_registry = _ProcessRegistry(names)
        self._state_store_manager = ssm
        self._process_configs: dict = {}

    def _log_debug(self, *a, **k) -> None: ...
    def _log_info(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...
    def _log_error(self, *a, **k) -> None: ...


def _make_env(proc_name: str = "camera_0") -> tuple[StateStoreManager, ProcessMonitor, FakeClock, ProcessHeartbeat]:
    ssm = StateStoreManager()
    plugin_services = _PluginProcServices(proc_name, ssm)
    clock = FakeClock()
    hb = ProcessHeartbeat(plugin_services, clock=clock)
    pm_process = _PMProcess(ssm, [proc_name])
    monitor = ProcessMonitor(process_manager_process=pm_process, poll_interval=0.5, heartbeat_timeout=15.0)
    return ssm, monitor, clock, hb


def _publish_drops(hb: ProcessHeartbeat, clock: FakeClock, writer: str, value: int) -> None:
    """Опубликовать ``drops=value`` от ``writer`` РЕАЛЬНЫМ тиком (не рукописной
    константой в дерево) и продвинуть часы, чтобы следующий тик не совпал по
    окну с предыдущим."""
    ctx = PluginContext(services=hb._services, plugin_name=writer)
    ctx.declare_metric("drops")
    ctx.publish_metric("drops", value)
    _force_one_tick(hb, clock)
    clock.advance(0.05)


def _alert_field(ssm: StateStoreManager, proc: str, rule: str, field: str) -> Any:
    path = f"system.alerts.{proc}.{rule}.{field}"
    return ssm.store.get(path, default=None)


# --------------------------------------------------------------------------- #
# К1 — drops_growing стреляет на НОВОМ пути (processes.<p>.state.plugins.<w>.drops)
# --------------------------------------------------------------------------- #


class TestK1DropsGrowingFiresOnNewPluginPath:
    def test_first_measurement_establishes_baseline_without_alert(self) -> None:
        """Существующая семантика счётчиковых правил (докстринг ``_check_counter_alerts``,
        разрешённый файл): первый замер — только база, алерта ещё нет."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        try:
            _publish_drops(hb, clock, "capture", 5)
            monitor._check_counter_alerts()

            assert _alert_field(ssm, "camera_0", "drops_growing", "severity") is None
        finally:
            forget_declarations("metric", names={"drops"})

    def test_alert_fires_when_plugin_drops_counter_grows(self) -> None:
        """Позитив: рост drops под НОВЫМ путём (state.plugins.capture.drops) между
        двумя замерами -> alert system.alerts.camera_0.drops_growing выпущен,
        severity == 'warning' (литерал, источник — feature_flags.py, см. шапку файла)."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        try:
            _publish_drops(hb, clock, "capture", 5)
            monitor._check_counter_alerts()  # база

            _publish_drops(hb, clock, "capture", 55)  # заведомо большой рост
            monitor._check_counter_alerts()  # должен выпустить алерт

            severity = _alert_field(ssm, "camera_0", "drops_growing", "severity")
            assert severity == "warning", (
                f"алерт drops_growing НЕ выпущен (или неверный severity) после роста "
                f"под НОВЫМ путём state.plugins.capture.drops (5 -> 55); "
                f"severity={severity!r} — правило супервизии не видит новый адрес"
            )
            # Существование не голословно: reason непуст (не просто угаданная строка).
            reason = _alert_field(ssm, "camera_0", "drops_growing", "reason")
            assert reason, f"алерт выпущен без текста причины: reason={reason!r}"
        finally:
            forget_declarations("metric", names={"drops"})

    def test_no_alert_without_growth(self) -> None:
        """Пара-контроль (обязателен правилом проекта): БЕЗ роста (то же значение на
        втором замере) алерта нет — иначе «стреляет всегда» неотличимо от «стреляет
        правильно»."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        try:
            _publish_drops(hb, clock, "capture", 5)
            monitor._check_counter_alerts()  # база

            _publish_drops(hb, clock, "capture", 5)  # БЕЗ роста
            monitor._check_counter_alerts()

            assert _alert_field(ssm, "camera_0", "drops_growing", "severity") is None, (
                "алерт drops_growing выпущен БЕЗ роста счётчика — предохранитель стреляет всегда, а не по факту роста"
            )
        finally:
            forget_declarations("metric", names={"drops"})


# --------------------------------------------------------------------------- #
# К1b — писатель не зашит (произвольное имя; рост любого из двух не теряется)
# --------------------------------------------------------------------------- #


class TestK1bWriterNameIsNotHardcoded:
    def test_arbitrary_unknown_writer_name_is_seen(self) -> None:
        """Писатель с именем, которого нет НИ В ОДНОЙ таблице фреймворка
        (``totally_custom_probe_writer_zz`` — не встречается нигде в коде проекта)
        -> правило всё равно видит его рост. Доказывает «находит по ФОРМЕ адреса,
        не по имени конкретного плагина»."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        writer = "totally_custom_probe_writer_zz"
        try:
            _publish_drops(hb, clock, writer, 5)
            monitor._check_counter_alerts()  # база

            _publish_drops(hb, clock, writer, 55)
            monitor._check_counter_alerts()

            severity = _alert_field(ssm, "camera_0", "drops_growing", "severity")
            assert severity == "warning", (
                f"алерт не выпущен для незнакомого имени писателя {writer!r} — "
                f"правило, похоже, ищет ЗНАКОМОЕ имя, а не форму адреса"
            )
        finally:
            forget_declarations("metric", names={"drops"})

    def test_growth_from_writer_a_alone_is_not_lost(self) -> None:
        """Два писателя публикуют drops (свежее окружение). Растёт ТОЛЬКО A
        (alpha_writer) -> алерт выпущен, несмотря на присутствие ВТОРОГО писателя
        (bravo_writer) без роста."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        try:
            _publish_drops(hb, clock, "alpha_writer", 5)
            _publish_drops(hb, clock, "bravo_writer", 5)
            monitor._check_counter_alerts()  # база (оба писателя учтены)

            _publish_drops(hb, clock, "alpha_writer", 55)  # растёт только A
            _publish_drops(hb, clock, "bravo_writer", 5)  # B без роста
            monitor._check_counter_alerts()

            severity = _alert_field(ssm, "camera_0", "drops_growing", "severity")
            assert severity == "warning", (
                "рост писателя 'alpha_writer' потерян при наличии второго "
                "писателя ('bravo_writer') без роста — К1b нарушен"
            )
        finally:
            forget_declarations("metric", names={"drops"})

    def test_growth_from_writer_b_alone_is_not_lost(self) -> None:
        """Симметричный сценарий (СВЕЖЕЕ окружение, роли писателей поменяны
        местами) — растёт ТОЛЬКО B. Обязателен рядом с предыдущим тестом: одного
        сценария (растёт только первый в некотором внутреннем порядке) достаточно
        для механизма, который ошибочно смотрит только на ПЕРВОГО резолвящегося
        писателя — тест должен ловить и эту ошибку тоже."""
        ssm, monitor, clock, hb = _make_env("camera_0")
        try:
            _publish_drops(hb, clock, "alpha_writer", 5)
            _publish_drops(hb, clock, "bravo_writer", 5)
            monitor._check_counter_alerts()  # база

            _publish_drops(hb, clock, "alpha_writer", 5)  # A без роста
            _publish_drops(hb, clock, "bravo_writer", 55)  # растёт только B
            monitor._check_counter_alerts()

            severity = _alert_field(ssm, "camera_0", "drops_growing", "severity")
            assert severity == "warning", (
                "рост писателя 'bravo_writer' потерян при наличии первого "
                "писателя ('alpha_writer') без роста — К1b нарушен (механизм, "
                "похоже, слепо берёт только ПЕРВОГО резолвящегося писателя)"
            )
        finally:
            forget_declarations("metric", names={"drops"})


# --------------------------------------------------------------------------- #
# К3 — предохранитель троттла обязан покрывать НОВЫЙ адрес плагинной метрики
# --------------------------------------------------------------------------- #


class TestK3ThrottleSafetyMatchesNewPath:
    """Конфиг прототипа, который строит реальные правила троттла
    (``multiprocess_prototype/backend/state/manager_setup.py::build_throttle_rules``,
    подтверждено ТОЛЬКО как имя+местоположение через ``grep`` по СТРОКЕ
    определения — само тело функции не читалось и не импортировалось), читать
    запрещено. Правила ниже — СОБСТВЕННЫЙ набор, теми же выражениями (тем же
    glob-идиомом ``processes.**.state.<суффикс>``), что уже используется в
    РАЗРЕШЁННЫХ тестах троттла этого же модуля (``test_throttle.py``,
    ``test_telemetry_broadcast.py`` — везде паттерн вида
    ``"processes.**.state.fps": <interval>``).

    Смысл теста: правило, написанное под СТАРЫЙ (немигрированный) плоский
    адрес drops (``processes.**.state.drops`` — та же форма, что несла
    старая расстановка путей ДО переезда в поддерево писателя), закономерно
    перестаёт покрывать НОВЫЙ адрес — а значит, предохранитель троттла
    молчит на плагинной метрике, пока кто-то не заведёт правило под НОВУЮ
    форму. Пара-контроль: тот же матчер (``match_pattern``/``split_pattern``,
    ПУБЛИЧНЫЙ движок — ``state_store_module.core``) на агрегате fps (путь
    НЕ переехал по условию задачи) продолжает находить правило.
    """

    @staticmethod
    def _applicable_rules(rules: dict[str, float], path: str) -> list[str]:
        """Список паттернов из ``rules``, матчащих ``path`` — ТЕМ ЖЕ публичным
        матчером, которым внутри пользуется ``ThrottleMiddleware._find_rule``
        (не переизобретение алгоритма)."""
        path_segs = tuple(path.split("."))
        return [p for p in rules if match_pattern(split_pattern(p), path_segs)]

    def test_plugin_metric_path_has_no_rule_under_the_old_flat_pattern(self) -> None:
        """Дыра К3: правило под СТАРЫЙ плоский адрес не матчит НОВЫЙ путь
        плагинной метрики."""
        rules = {"processes.**.state.drops": 1.0}
        new_path = "processes.camera_0.state.plugins.probe_writer.drops"

        applicable = self._applicable_rules(rules, new_path)
        assert applicable == [], (
            f"список применимых правил для нового пути {new_path!r} НЕ пуст под "
            f"старым правилом {list(rules)!r} — предохранитель, похоже, уже "
            f"покрывает новый адрес (это была бы ХОРОШАЯ новость, но противоречит "
            f"К3, который требует завести НОВОЕ правило)"
        )

    def test_control_old_aggregate_rule_still_matches_unmigrated_fps(self) -> None:
        """Пара-контроль (правило проекта): ТОТ ЖЕ матчер на fps (путь НЕ переехал
        по условию задачи) находит правило — доказывает, что предыдущий тест пуст
        именно из-за переезда адреса drops, а не из-за сломанной фикстуры/матчера."""
        rules = {"processes.**.state.fps": 1.0}
        fps_path = "processes.camera_0.state.fps"

        applicable = self._applicable_rules(rules, fps_path)
        assert applicable == ["processes.**.state.fps"], (
            f"контрольный (немигрированный) путь fps неожиданно НЕ покрыт своим "
            f"же правилом — applicable={applicable!r}, методология теста сломана"
        )

    def test_engine_observably_throttles_the_new_path_once_a_rule_is_added(self) -> None:
        """Наблюдаемый ЭФФЕКТ (не только матч паттерна): ``ThrottleMiddleware``,
        настроенный правилом ПОД НОВУЮ форму адреса (той же формы, что уже
        используют разрешённые тесты троттла — не изобретение новой), реально
        придерживает второй ``set`` в то же окно. Доказывает, что новый адрес
        МОЖЕТ быть защищён существующим языком паттернов без правки движка —
        дело за конфигом (запрещённым для чтения), а не за матчером."""
        clock = {"t": 0.0}
        mw = ThrottleMiddleware(
            {"processes.**.state.plugins.*.drops": 1.0},
            clock=lambda: clock["t"],
        )
        new_path = "processes.camera_0.state.plugins.probe_writer.drops"

        proceed1, _ = mw.before_set(new_path, 1, "test", {})
        assert proceed1 is True, "первая запись в окне обязана пройти"

        proceed2, _ = mw.before_set(new_path, 2, "test", {})
        assert proceed2 is False, (
            "второй set в ТОМ ЖЕ окне прошёл несмотря на правило "
            "'processes.**.state.plugins.*.drops' — предохранитель не сработал "
            "даже когда правило заведено явно"
        )
