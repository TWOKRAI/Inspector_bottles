"""
Task 3.0 (observability-closure, Ф3) — приёмочные тесты по контракту,
написаны ДО реализации `judge_throttle_caps`.

Независимый тестер: тесты пишутся по контракту из ТЗ, а не по чтению
`telemetry_reload.py` / `observability_reload.py` — их тела НЕ читались.
Единственное, что было проверено заранее — сигнатуры через `inspect.signature`
(без чтения исходника), чтобы убедиться, что `detect_throttle_caps` уже
существует с указанной сигнатурой, а `judge_throttle_caps` — ещё нет.

Предмет: реальный "ask" публикатора учитывает эффективный такт heartbeat'а
(`effective_tick`) — публикатор физически не может публиковать чаще такта.
"""

from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.process_module.managers import (
    observability_reload as orl,
)
from multiprocess_framework.modules.process_module.managers import (
    telemetry_reload as tr,
)


# ---------------------------------------------------------------------------
# Два представления одного и того же кандидата на потолок троттла:
# через publish_section["metrics"] (ключ отчёта = имя метрики) и через
# observation_rules (правило по пути, ключ отчёта = сам паттерн).
# ---------------------------------------------------------------------------


def _metrics_shape(interval_sec, throttle_val):
    report_key = "fps"
    publish_section = {"metrics": {"fps": {"interval_sec": interval_sec}}}
    observation_rules = None
    throttle_rules = {"**.state.fps": throttle_val}
    return report_key, publish_section, observation_rules, throttle_rules


def _path_rule_shape(interval_sec, throttle_val):
    report_key = "proc.state.fps"
    publish_section = {}
    observation_rules = {"proc.state.fps": {"enabled": True, "interval_sec": interval_sec}}
    throttle_rules = {"proc.state.fps": throttle_val}
    return report_key, publish_section, observation_rules, throttle_rules


_SHAPES = pytest.mark.parametrize("shape", [_metrics_shape, _path_rule_shape], ids=["metrics", "path_rule"])


# ---------------------------------------------------------------------------
# Критерий 1 — пригодный такт (5.0) выше заявки (1.0) поднимает реальный ask
# до 5.0; троттл 2.0 слабее итогового ask → потолок не называется вовсе.
# ---------------------------------------------------------------------------


@_SHAPES
def test_criterion1_no_cap_when_tick_dominates_and_throttle_is_looser(shape):
    """Такт 5.0 > заявки 1.0 → ask=5.0; троттл 2.0 < 5.0 не режет — caps пуст."""
    _report_key, publish_section, observation_rules, throttle_rules = shape(interval_sec=1.0, throttle_val=2.0)
    store_throttle = SimpleNamespace(rules=throttle_rules)

    caps = tr.detect_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        effective_tick=5.0,
    )

    assert caps == {}


# ---------------------------------------------------------------------------
# Критерий 2 — потолок называет РЕАЛЬНЫЙ ask (5.0), а не заявленный (1.0).
# ---------------------------------------------------------------------------


@_SHAPES
def test_criterion2_cap_reports_real_ask_not_claimed_interval(shape):
    """publisher_interval_sec в отчёте — это max(заявка, такт) = 5.0, не 1.0."""
    report_key, publish_section, observation_rules, throttle_rules = shape(interval_sec=1.0, throttle_val=6.0)
    store_throttle = SimpleNamespace(rules=throttle_rules)

    caps = tr.detect_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        effective_tick=5.0,
    )

    assert caps == {report_key: {"publisher_interval_sec": 5.0, "throttle_interval_sec": 6.0}}


# ---------------------------------------------------------------------------
# Критерий 3 — такт неизвестен (None) → ask = заявка (без такта поведение как
# раньше, регресса быть не должно).
# ---------------------------------------------------------------------------


@_SHAPES
def test_criterion3_unknown_tick_falls_back_to_claimed_interval(shape):
    """effective_tick=None → ask берётся из заявленного interval_sec=1.0."""
    report_key, publish_section, observation_rules, throttle_rules = shape(interval_sec=1.0, throttle_val=2.0)
    store_throttle = SimpleNamespace(rules=throttle_rules)

    caps = tr.detect_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        effective_tick=None,
    )

    assert caps == {report_key: {"publisher_interval_sec": 1.0, "throttle_interval_sec": 2.0}}


# ---------------------------------------------------------------------------
# Критерий 4 — такт непригоден (0.0) И заявки нет (0.0) → кандидат НЕ судится,
# уходит в unjudged с причиной "no_tick", а не в caps.
# ---------------------------------------------------------------------------


def test_criterion4_metrics_no_claim_no_tick_is_unjudged_not_capped():
    """metrics: заявка 0.0 + такт 0.0 (непригоден) → unjudged["fps"]=="no_tick", caps пуст."""
    publish_section = {"metrics": {"fps": {"interval_sec": 0.0}}}
    store_throttle = SimpleNamespace(rules={"**.state.fps": 2.0})

    caps, unjudged = tr.judge_throttle_caps(publish_section, store_throttle, effective_tick=0.0)

    assert caps == {}
    assert unjudged == {"fps": "no_tick"}


def test_criterion4_path_rule_default_chain_no_tick_is_unjudged_not_capped():
    """path-правило: interval_sec=None -> default_interval_sec=None -> нет ключа
    default_interval_sec в publish_section -> тройной fallback к 0.0; такт 0.0
    (непригоден) -> unjudged с причиной "no_tick", caps пуст."""
    publish_section: dict = {}  # намеренно без ключа "default_interval_sec"
    observation_rules = {"proc.state.fps": {"enabled": True, "interval_sec": None}}
    store_throttle = SimpleNamespace(rules={"proc.state.fps": 2.0})

    caps, unjudged = tr.judge_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        default_interval_sec=None,
        effective_tick=0.0,
    )

    assert caps == {}
    assert unjudged == {"proc.state.fps": "no_tick"}


# ---------------------------------------------------------------------------
# Критерий 5 — judge_throttle_caps возвращает (caps, unjudged);
# detect_throttle_caps на ТОМ ЖЕ входе отдаёт ровно те же caps (обёртка не
# меняет контракт). Такт=None намеренно, чтобы в одном вызове получить и
# судимых (заявка>0), и несудимых (заявка<=0) кандидатов одновременно.
# ---------------------------------------------------------------------------


def test_criterion5_detect_wraps_judge_and_caps_match_exactly():
    """caps из detect_throttle_caps == caps из judge_throttle_caps на одном входе,
    даже когда среди кандидатов есть и капнутые, и unjudged, и некапнутые."""
    publish_section = {
        "metrics": {
            "fps": {"interval_sec": 1.0},  # судим, капнут (throttle 6.0 > 1.0)
            "temp": {"interval_sec": 0.0},  # без такта и без заявки -> unjudged
        }
    }
    observation_rules = {
        "proc.state.pressure": {"enabled": True, "interval_sec": 1.0},  # судим, НЕ капнут
        "proc.state.idle": {"enabled": True, "interval_sec": 0.0},  # unjudged
    }
    store_throttle = SimpleNamespace(
        rules={
            "**.state.fps": 6.0,
            "**.state.temp": 3.0,
            "proc.state.pressure": 0.5,
            "proc.state.idle": 4.0,
        }
    )

    caps_from_judge, unjudged = tr.judge_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        effective_tick=None,
    )
    caps_from_detect = tr.detect_throttle_caps(
        publish_section,
        store_throttle,
        observation_rules=observation_rules,
        effective_tick=None,
    )

    assert caps_from_detect == caps_from_judge
    # предметная проверка — совпадение не должно быть совпадением двух пустых словарей
    assert caps_from_judge == {"fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 6.0}}
    assert unjudged == {"temp": "no_tick", "proc.state.idle": "no_tick"}


# ---------------------------------------------------------------------------
# Критерий 6 — троттл=0 (полная блокировка) остаётся потолком при ЛЮБОМ
# пригодном ask: и когда такт поднимает ask выше заявки, и когда такта нет
# вовсе и ask берётся из заявки.
# ---------------------------------------------------------------------------


def test_criterion6_metrics_full_block_caps_even_when_tick_raises_ask():
    """metrics: троттл=0.0 капает даже когда пригодный такт поднял ask до 5.0."""
    publish_section = {"metrics": {"fps": {"interval_sec": 1.0}}}
    store_throttle = SimpleNamespace(rules={"**.state.fps": 0.0})

    caps = tr.detect_throttle_caps(publish_section, store_throttle, effective_tick=5.0)

    assert caps == {"fps": {"publisher_interval_sec": 5.0, "throttle_interval_sec": 0.0}}


def test_criterion6_path_rule_full_block_caps_without_tick():
    """path-правило: троттл=0.0 капает и без такта — ask берётся из заявки 1.0."""
    observation_rules = {"proc.state.fps": {"enabled": True, "interval_sec": 1.0}}
    store_throttle = SimpleNamespace(rules={"proc.state.fps": 0.0})

    caps = tr.detect_throttle_caps({}, store_throttle, observation_rules=observation_rules, effective_tick=None)

    assert caps == {"proc.state.fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 0.0}}


# ---------------------------------------------------------------------------
# Критерий 7 — apply_observation_policy: ключ "capped_by_throttle_unjudged"
# присутствует ТОЛЬКО когда список непуст (не пустой словарь — ключа нет).
#
# Сигнатура (подтверждена через inspect.signature, тело САМОЙ apply_observation_policy
# в observability_reload.py НЕ читалось): apply_observation_policy(heartbeat, section,
# *, store_throttle=None) -> Optional[Dict].
#
# ПЕРВАЯ попытка (см. отчёт) строила фейковый heartbeat с "громким" методом
# apply_observation_policy(section), исходя из брифа. Прогон вслепую показал:
# модуль вызывает именно heartbeat.apply_observation_policy(section) — это
# РЕАЛЬНЫЙ метод класса ProcessHeartbeat (heartbeat/process_heartbeat.py:725,
# файл НЕ входит в список запрещённых), а не что-то, что можно замокать без
# потери смысла проверки. Поэтому здесь используется настоящий ProcessHeartbeat
# с минимальным duck-typed services (приём уже был в моей памяти:
# .claude/agent-memory/tester/feedback_test_live_telemetry_gate_without_full_boot.md,
# сам этот приём — не про предмет задачи, только про то, как поднять живой
# гейт без полного boot'а системы).
# ---------------------------------------------------------------------------


class _MinimalServices:
    """Минимальный duck-typed services — только то, что ProcessHeartbeat реально
    читает по пути _build_telemetry_gate()/apply_observation_policy() при таком
    конфиге: get_config(key, default). Логирующие методы намеренно отсутствуют —
    все вызовы _log_heartbeat/_warn_* в реализации уже проверены как no-op без них
    (getattr(..., None) с graceful return)."""

    def __init__(self, config: dict) -> None:
        self._config = config

    def get_config(self, key, default=None):
        return self._config.get(key, default)


def _live_heartbeat(*, heartbeat_interval: float):
    from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
        ProcessHeartbeat,
    )

    services = _MinimalServices({"telemetry": {"publish": {"metrics": {}}}})
    hb = ProcessHeartbeat(services)
    hb._interval = heartbeat_interval  # обходим start() (не поднимаем воркеры)
    hb._telemetry_gate = hb._build_telemetry_gate()
    return hb


def test_criterion7_unjudged_key_absent_when_empty():
    """Ключа "capped_by_throttle_unjudged" в ответе НЕТ (не пустой dict), когда
    unjudged-список пуст — единственное правило порта имеет положительную заявку
    (0.5), поэтому судится независимо от такта (пригоден он или нет)."""
    heartbeat = _live_heartbeat(heartbeat_interval=5.0)  # такт пригоден: 5.0
    store_throttle = SimpleNamespace(rules={"proc.state.fps": 2.0})
    section = {"rules": {"proc.state.fps": {"enabled": True, "interval_sec": 0.5}}}

    result = orl.apply_observation_policy(heartbeat, section, store_throttle=store_throttle)

    assert result is not None
    assert "capped_by_throttle_unjudged" not in result


def test_criterion7_unjudged_key_present_when_nonempty():
    """Ключ "capped_by_throttle_unjudged" ПРИСУТСТВУЕТ и непуст: такт heartbeat'а
    сделан непригодным (0.0) И правило порта не заявляет частоты (0.0) —
    ровно комбинация критерия 4, "нет ни такта, ни заявки"."""
    heartbeat = _live_heartbeat(heartbeat_interval=0.0)  # такт непригоден: 0.0
    store_throttle = SimpleNamespace(rules={"proc.state.idle": 2.0})
    section = {"rules": {"proc.state.idle": {"enabled": True, "interval_sec": 0.0}}}

    result = orl.apply_observation_policy(heartbeat, section, store_throttle=store_throttle)

    assert result is not None
    assert "capped_by_throttle_unjudged" in result
    assert result["capped_by_throttle_unjudged"]
