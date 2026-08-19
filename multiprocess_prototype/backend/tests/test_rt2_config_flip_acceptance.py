# -*- coding: utf-8 -*-
"""Независимая приёмка РТ-2 (flip default_enabled) — prototype-половина (A1/A2/A3).

НЕЗАВИСИМЫЙ прогон: писался БЕЗ чтения plans/telemetry-stage6.md, plans/QUEUE.md,
git diff/log/show по ветке и БЕЗ чтения тестов автора
(test_telemetry_default_enabled_hazards.py / test_telemetry_default_enabled_acceptance.py).
Ожидаемые значения — литералы, взятые из чтения контрактных файлов, перечисленных в
задании (system.yaml, manager_setup.py), а не выведены вызовом кода, который тест
проверяет.

РАЗДЕЛЕНИЕ НА ДВА ФАЙЛА (находка, см. отчёт тестера, раздел 3): задание просило
единственный файл в multiprocess_framework/modules/process_module/tests/, но A1/A2/A3
неотделимы от боевого multiprocess_prototype/backend/config/system.yaml и
backend/state/manager_setup.py — импорт prototype ИЗ framework запрещён
`.sentrux/rules.toml` (`[[boundaries]] from="multiprocess_framework/*"
to="multiprocess_prototype/*"`, без исключения для tests/). Прототип ЛЕГИТИМНО
импортирует framework (composition root, см. CLAUDE.md «слои импортов»), поэтому
этот файл живёт здесь, а не наоборот. Companion-файл (A4/A5/A6) —
`multiprocess_framework/modules/process_module/tests/test_rt2_config_flip_acceptance.py`.

Критерии, закрываемые ЗДЕСЬ (буквально из задания):
    A1 — telemetry.publish в system.yaml ДЕЙСТВУЕТ, default_enabled == False.
    A2 — гейт из этого конфига отдаёт enabled=False для (а) известного каталогу имени,
         (б) имени, которого в metrics нет вовсе, (в) имени, объявленного ПОСЛЕ сборки гейта.
    A3 — telemetry.throttle НЕ действует ⇒ build_throttle_rules отдаёт полный дефолт.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.observability_declarations import declare_metric
from multiprocess_framework.modules.process_module.heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics

from multiprocess_prototype.backend.config.schemas import load_system_config
from multiprocess_prototype.backend.state.manager_setup import build_throttle_rules

# Дефолтный набор центрального троттла — переписан ВРУЧНУЮ по чтению
# multiprocess_prototype/backend/state/manager_setup.py:48-61 (_default_throttle_rules),
# а НЕ вызовом этой функции — иначе сравнение было бы тавтологией (код согласился бы
# с любым своим ответом). _SAFETY_INTERVAL_SEC = _MIN_PUBLISHER_INTERVAL_SEC(0.1) *
# _THROTTLE_SAFETY_MULTIPLIER(0.5) = 0.05 (там же, строки 23-24).
_EXPECTED_DEFAULT_THROTTLE_RULES = {
    "processes.**.state.fps": 0.05,
    "processes.**.state.capture_fps": 0.05,
    "processes.**.state.latency_ms": 0.05,
    "processes.**.state.uptime": 0.05,
    "processes.**.state.frame_count": 0.05,
    "processes.**.state.drops": 0.05,
    "processes.**.workers.*.effective_hz": 0.05,
    "processes.**.workers.*.cycle_duration_ms": 0.05,
}


class _FakeServices:
    """Дублёр сервисов процесса — только то, что реально трогает _build_telemetry_gate."""

    def __init__(self, name: str = "test_process") -> None:
        self.name = name
        self.worker_manager: Any = None
        self.router_manager: Any = None
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


def _build_real_gate() -> Any:
    """Гейт, собранный из БОЕВОГО system.yaml тем же методом, что в проде
    (ProcessHeartbeat._build_telemetry_gate, названный в задании явно)."""
    sc = load_system_config()
    services = _FakeServices()
    services._telemetry_config = sc.telemetry.model_dump()
    hb = ProcessHeartbeat(services)
    return hb._build_telemetry_gate()


# ===========================================================================
# A1 — секция telemetry.publish в system.yaml ДЕЙСТВУЕТ, default_enabled == False
# ===========================================================================


def test_a1_publish_section_is_active_in_production_system_yaml() -> None:
    """A1 (часть 1): telemetry.publish в боевом system.yaml — ДЕЙСТВУЮЩАЯ секция.

    Как упадёт: сейчас (2026-08-18) весь блок telemetry: в system.yaml
    закомментирован (строки 186-201) — load_system_config().telemetry.publish
    останется None, и assert упадёт AssertionError'ом "publish is None".
    """
    sc = load_system_config()
    assert sc.telemetry.publish is not None, (
        "telemetry.publish не действует (publish is None) — секция закомментирована "
        "или не задана в multiprocess_prototype/backend/config/system.yaml"
    )


def test_a1_default_enabled_is_literally_false() -> None:
    """A1 (часть 2): default_enabled внутри действующей секции равен False.

    Проверяем ПОЛЕ напрямую, а не только resolve() — у схем extra=ignore
    (Pydantic v2 default, SchemaBase его не переопределяет), опечатка в имени
    поля была бы молча проглочена и default_enabled остался бы на классовом
    дефолте True, а resolve() для имени с явным override всё равно мог бы
    случайно вернуть False и замаскировать поломку.

    Как упадёт: если publish есть, но default_enabled не выставлен в false
    (остался True или ключ переименован) — assert упадёт с фактическим True.
    """
    sc = load_system_config()
    assert sc.telemetry.publish is not None, "предпосылка: publish должен быть задан (A1.1)"
    assert sc.telemetry.publish.default_enabled is False


# ===========================================================================
# A2 — гейт из ЭТОГО конфига отдаёт enabled=False для любого имени метрики
# ===========================================================================


def test_a2a_gate_disables_every_catalog_metric_except_the_dashboard_whitelist() -> None:
    """A2(а): боевой гейт отдаёт enabled=False для любого каталожного имени, КРОМЕ
    объявленного белого списка дашборда — и ровно кроме него.

    Прежняя формулировка («enabled=False для ЛЮБОГО имени») была верна на момент
    исполнения флипа РТ-2 (``ee842a1a``) и стала ложью на ``cb79d884``: живой стенд
    показал, что кольцо истории read-model наполняет ТОЛЬКО push-дорога (опрос пишет
    ``record_history=False``, ADR-139), поэтому при пустом белом списке секция
    «Дашборд телеметрии» пуста НАВСЕГДА. ``fps``/``latency_ms`` внесены в
    ``telemetry.publish.metrics`` как ЯВНОЕ исключение (``system.yaml:261-269``), и
    исключение это сторожит пара тестов в
    ``multiprocess_prototype/backend/config/tests/test_telemetry_section.py:115,186``.
    Тест держался красным с ``cb79d884`` до 2026-08-19 — его никто не привёл в
    соответствие с решением, которое сам же конфиг документирует.

    Гарантия флипа при этом НЕ ослаблена, а сужена до проверяемой: множество
    включённых каталожных имён обязано СОВПАДАТЬ с белым списком. Третье имя,
    просочившееся в ``metrics``, красит тест — ровно то, ради чего пункт A2(а) и
    заводился.

    Оракул белого списка — ``_DASHBOARD_METRICS`` из виджета, НЕ ``system.yaml``:
    список, вычитанный из проверяемого файла, согласился бы с любым его состоянием.
    Тот же оракул, что у сторожей в ``test_telemetry_section.py`` — второго источника
    правды о белом списке в репозитории нет.

    Как упадёт: гейта нет вовсе → "gate is not None". Включено имя вне белого списка
    (ослабили ``default_enabled`` или добавили override) → множества разойдутся с
    показом лишнего имени. Метрику дашборда убрали из ``metrics`` → разойдутся с
    показом недостающего, и график дашборда молча опустеет.
    """
    # Локальный импорт — оракул целиком из виджета, не из yaml, который проверяем.
    from multiprocess_prototype.frontend.widgets.tabs.processes._system_dashboard import (
        _DASHBOARD_METRICS,
    )

    gate = _build_real_gate()
    assert gate is not None, (
        "publisher-gate не собрался из боевого system.yaml (см. A1/A2) — _build_telemetry_gate() вернул None"
    )
    whitelist = {key for key, _label in _DASHBOARD_METRICS}
    assert whitelist, "оракул сломан: у виджета дашборда пуст список метрик"
    catalog = set(gated_metrics())
    assert whitelist <= catalog, (
        f"белый список дашборда вышел за каталог gated_metrics(): {sorted(whitelist - catalog)} — "
        "либо метрика переименована, либо её производитель не импортирован"
    )

    still_enabled = {metric for metric in catalog if gate.config.resolve(metric)[0]}
    assert still_enabled == whitelist, (
        f"включены не те каталожные метрики: лишние {sorted(still_enabled - whitelist)}, "
        f"недостающие {sorted(whitelist - still_enabled)}; белый список — "
        f"{sorted(whitelist)} (system.yaml:261-269, исключение из флипа РТ-2)"
    )


def test_a2b_gate_disables_a_name_absent_from_metrics_entirely() -> None:
    """A2(б): для имени, которого в metrics НЕТ ВООБЩЕ (не каталожное, не override,
    выдуманное), гейт тоже отдаёт enabled=False — то есть default_enabled=False
    работает как истинный whitelist, а не «выключено только для известных».

    Как упадёт: аналогично test_a2a — либо gate is None (A1), либо enabled=True
    для заведомо неизвестного имени (default_enabled не долетел / остался True).
    """
    gate = _build_real_gate()
    assert gate is not None, "publisher-gate не собрался из боевого system.yaml (см. A1/A2)"
    enabled, _interval = gate.config.resolve("tester_rt2_never_configured_metric_a2b")
    assert enabled is False


def test_a2c_gate_disables_a_metric_declared_after_the_gate_was_built() -> None:
    """A2(в): гейт, УЖЕ собранный из боевого конфига, обязан гасить метрику,
    объявленную через declare_metric ПОСЛЕ его сборки — имитация плагина,
    заявившего своё имя позже (гейт не смеет кэшировать список имён на
    момент __init__/сборки, иначе поздние плагины молча остались бы включены).

    Проверяется due_metrics() — реальный per-тик результат (что публикатор
    реально возьмёт), а не только resolve() (которая по построению не читает
    каталог вовсе и поэтому сама по себе не доказывает независимость от
    момента объявления).

    Как упадёт: если A1 не выполнен — "gate is not None". Если due_metrics()
    когда-нибудь начнёт использовать список имён, зафиксированный на момент
    конструирования (регрессия кеширования) — позднее имя всё равно попало бы
    в allowed, и assert "not in allowed" упадёт.
    """
    gate = _build_real_gate()
    assert gate is not None, "publisher-gate не собрался из боевого system.yaml (см. A1/A2)"

    late_name = "tester_rt2_late_declared_metric_a2c"
    declare_metric(late_name, owner="tester:rt2_acceptance:late")

    allowed = gate.due_metrics()
    assert late_name not in allowed

    enabled, _interval = gate.config.resolve(late_name)
    assert enabled is False


# ===========================================================================
# A3 — telemetry.throttle НЕ действует ⇒ build_throttle_rules() без сужения
# ===========================================================================


def test_a3_throttle_section_is_inactive_in_production_config() -> None:
    """A3 (предпосылка): telemetry.throttle в боевом system.yaml НЕ задан (пуст) —
    иначе build_throttle_rules сузился бы намеренно (PC 2.1: заданный throttle
    ПОЛНОСТЬЮ заменяет хардкод-дефолты), и это уже не про критерий A3.

    Как упадёт: если владелец когда-нибудь раскомментирует блок throttle: в
    system.yaml вместе с publish: — предпосылка перестанет выполняться, и этот
    тест скажет об этом прямо, вместо того чтобы молча провалить следующий.
    """
    sc = load_system_config()
    assert not sc.telemetry.throttle, (
        "telemetry.throttle уже не пуст в боевом конфиге — предпосылка критерия A3 "
        "(секция throttle неактивна) больше не выполняется"
    )


def test_a3_build_throttle_rules_returns_the_full_unnarrowed_default_set() -> None:
    """A3: центральный троттл НЕ сужается — build_throttle_rules(sys_config) отдаёт
    полный дефолтный набор правил. Проверено ЧИСЛОМ и точным набором ключей.

    НАХОДКА про сам критерий (не про код): задание утверждает «их девять» правил.
    Прямым счётом по multiprocess_prototype/backend/state/manager_setup.py:48-61
    (_default_throttle_rules) их ВОСЕМЬ — см. отчёт тестера, раздел 3. Ниже
    пришпилен литеральный набор из восьми пар, переписанный вручную при чтении
    кода (не вызовом _default_throttle_rules() — иначе сравнение было бы
    тавтологией). Расхождение 8 vs 9 не патчится под критерий: если девятая
    запись когда-нибудь появится в коде намеренно — этот тест обязан покраснеть
    и заставить обновить и код, и число в задании синхронно.

    Как упадёт: если A1 протащит с собой АКТИВНЫЙ throttle (сузит правила) —
    build_throttle_rules вернёт другой набор ключей/значений, и assert равенства
    словарей упадёт с точным diff'ом. Если сам _default_throttle_rules потеряет
    или получит ключ — тоже упадёт здесь, а не молча.
    """
    sc = load_system_config()
    rules = build_throttle_rules(sc)
    assert rules == _EXPECTED_DEFAULT_THROTTLE_RULES
    assert len(rules) == 8  # ЛИТЕРАЛ по факту чтения кода. Задание пишет 9 — расхождение.
