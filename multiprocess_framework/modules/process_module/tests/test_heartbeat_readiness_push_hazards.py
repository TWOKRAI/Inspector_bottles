# -*- coding: utf-8 -*-
"""Task 3.3 (system-run-state) — hazard-тесты автора: внеочередной heartbeat при смене готовности.

Не слепой набор (``test_heartbeat_readiness_push.py``) — свойства, которые автор гарантирует прямым вызовом
настоящего ``ProcessHeartbeat`` с минимальным носителем: смена — это отличие подписи (``paused``, ``ready``, набор
пар ``(node, severity)`` блокирующих причин) от подписи УШЕДШЕЙ копии; ``at``/тексты/неблокирующие в подпись не
входят; первый снимок сменой не считается; антидребезг; гонка «сравнили — снимок сменился — отправили»; сбой
отправки не теряет смену; push не двигает расписание регулярного; битая причина не съедает регулярный heartbeat.

Всё, что может блокировать, зовётся в daemon-потоке с join-дедлайном (``_bounded``). Настоящие процессы — в слепом
наборе и в ``test_heartbeat_paused_push_hazards.py``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat

_JOIN_S = 30.0
#: Окно антидребезга heartbeat — 0,5 с; сон чуть больше выводит из него.
_GAP_S = 0.55


def _reason(node: str, severity: str = "failure", text: str = "причина") -> dict:
    return {"node": node, "severity": severity, "reason": text, "source": "plugin"}


def _snap(
    *,
    ready: bool = True,
    reasons: Any = None,
    paused: bool = False,
    at: float = 1.0,
    **extra: Any,
) -> dict:
    snapshot: dict[str, Any] = {
        "ready": ready,
        "reasons": [] if reasons is None else reasons,
        "paused": paused,
        "at": at,
    }
    snapshot.update(extra)
    return snapshot


class _Svc:
    """Минимальный носитель ``ProcessHeartbeat``: снимок, запись отправок, сбой отправки по флагу."""

    def __init__(self, snapshot: Any = None) -> None:
        self.name = "hrp_proc"
        self.worker_manager = None
        self._readiness_snapshot = snapshot
        self.sent: list[dict] = []
        self.errors: list[str] = []
        self.debug: list[str] = []
        self.fail: Exception | None = None
        self.deliver = True
        self._config: dict[str, Any] = {"heartbeat_interval": 30.0}

    def send_message(self, target: str, message: dict) -> bool:
        if self.fail is not None:
            raise self.fail
        if not self.deliver:
            return False  # недоставка без исключения: так отвечает реальный send_to_process
        self.sent.append(message)
        return True

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_info(self, msg: str, **kw) -> None: ...

    def log_debug(self, msg: str, **kw) -> None:
        self.debug.append(msg)

    def log_error(self, msg: str, **kw) -> None:
        self.errors.append(msg)


def _started(svc: _Svc) -> ProcessHeartbeat:
    hb = ProcessHeartbeat(svc)  # type: ignore[arg-type]
    hb._started = True  # воркер такта не нужен: регулярный путь зовём руками
    return hb


def _bounded(fn: Callable[[], Any]) -> Any:
    """Вызов в daemon-потоке с join-дедлайном: зависание — красный тест, а не вечный прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается зовущему
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True, name="hrp-bounded")
    thread.start()
    thread.join(_JOIN_S)
    assert not thread.is_alive(), "вызов завис"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _push(hb: ProcessHeartbeat) -> bool:
    return _bounded(hb.push_if_changed)


def _regular(hb: ProcessHeartbeat) -> None:
    _bounded(lambda: hb._send_heartbeat({}))


def _readys(svc: _Svc) -> list[Any]:
    return [m["readiness"]["ready"] for m in svc.sent if "readiness" in m]


# --------------------------------------------------------------------------- #
# H1: первый снимок не смена
# --------------------------------------------------------------------------- #


def test_h1_first_snapshot_is_not_a_change() -> None:
    """В PM готовность ещё не уходила -> снимок с блокирующей причиной сменой не считается, сообщений нет."""
    svc = _Svc(_snap(ready=False, reasons=[_reason("pluginA")]))
    hb = _started(svc)

    assert [_push(hb) for _ in range(3)] == [False] * 3

    assert svc.sent == []


def test_h1_regular_without_readiness_leaves_first_snapshot_unsent() -> None:
    """Регулярный ушёл БЕЗ ``readiness`` (снимка ещё не было); появившийся снимок — всё ещё первый, не смена."""
    svc = _Svc(None)
    hb = _started(svc)
    _regular(hb)
    assert "readiness" not in svc.sent[0]

    svc._readiness_snapshot = _snap(ready=False, reasons=[_reason("pluginA")])

    assert _push(hb) is False
    assert len(svc.sent) == 1


# --------------------------------------------------------------------------- #
# H8: что входит в подпись, а что нет (по эффекту: есть смена — сообщение, нет смены — тишина)
# --------------------------------------------------------------------------- #

_BASE_REASONS = [_reason("pluginA", "failure", "текст один")]

#: (имя, снимок после, ждём push). База: ``ready=True``, одна блокирующая причина ``pluginA/failure``, ``paused=False``.
_SIGNATURE_CASES = [
    ("only_at_changes", _snap(reasons=_BASE_REASONS, at=2.0), False),
    ("stale_after_s_added", _snap(reasons=_BASE_REASONS, at=2.0, stale_after_s=15.0), False),
    ("blocking_text_changes", _snap(reasons=[_reason("pluginA", "failure", "ДРУГОЙ текст")]), False),
    ("source_changes", _snap(reasons=[{**_BASE_REASONS[0], "source": "other"}]), False),
    ("reason_order_changes_only", _snap(reasons=list(reversed(_BASE_REASONS))), False),
    ("non_blocking_out_of_spec_added", _snap(reasons=[*_BASE_REASONS, _reason("pluginB", "out_of_spec")]), False),
    ("non_blocking_maintenance_added", _snap(reasons=[*_BASE_REASONS, _reason("pluginB", "maintenance")]), False),
    ("out_of_spec_flag_added", _snap(reasons=_BASE_REASONS, out_of_spec=True), False),
    ("ready_flips_same_reasons", _snap(ready=False, reasons=_BASE_REASONS), True),
    ("paused_flips", _snap(reasons=_BASE_REASONS, paused=True), True),
    ("severity_failure_to_check_function", _snap(reasons=[_reason("pluginA", "check_function")]), True),
    ("second_plugin_blocking_added", _snap(reasons=[*_BASE_REASONS, _reason("pluginB", "failure")]), True),
    ("same_plugin_second_severity", _snap(reasons=[*_BASE_REASONS, _reason("pluginA", "check_function")]), True),
    ("blocking_set_shrinks_same_ready", _snap(reasons=[]), True),
    ("blocking_node_renamed", _snap(reasons=[_reason("pluginZ", "failure")]), True),
]


@pytest.mark.parametrize(("name", "after", "expect_push"), _SIGNATURE_CASES, ids=[c[0] for c in _SIGNATURE_CASES])
def test_h8_signature_decides_push(name: str, after: dict, expect_push: bool) -> None:
    """Отличие подписи (paused / ready / пары (node, severity) блокирующих) -> push; остальное -> тишина."""
    svc = _Svc(_snap(reasons=_BASE_REASONS))
    hb = _started(svc)
    _regular(hb)
    assert len(svc.sent) == 1
    svc._readiness_snapshot = after

    assert _push(hb) is expect_push, name

    assert len(svc.sent) == (2 if expect_push else 1)


def test_h8_boot_latch_ready_without_reasons_is_a_change() -> None:
    """Защёлка boot: ``ready False -> True`` без единой причины — смена (подпись без ``ready`` её бы не увидела)."""
    svc = _Svc(_snap(ready=False, reasons=[]))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=True, reasons=[], at=2.0)

    assert _push(hb) is True

    assert _readys(svc) == [False, True]


def test_h8_stream_of_at_only_updates_sends_nothing() -> None:
    """Воркер снимка обновляет ``at`` 2 раза в секунду: 20 пересчётов без смены -> ни одного внеочередного."""
    svc = _Svc(_snap(reasons=_BASE_REASONS))
    hb = _started(svc)
    _regular(hb)
    for i in range(20):
        svc._readiness_snapshot = _snap(reasons=_BASE_REASONS, at=2.0 + i * 0.5)
        assert _push(hb) is False

    assert len(svc.sent) == 1


# --------------------------------------------------------------------------- #
# H2: антидребезг
# --------------------------------------------------------------------------- #


def test_h2_flapping_is_debounced_and_final_state_delivered() -> None:
    """40 смен ``ready`` за ~1 с: 1..3 внеочередных (окно 0,5 с), итог после затишья доставлен."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    started = time.monotonic()
    pushes = 0
    for i in range(40):
        svc._readiness_snapshot = _snap(ready=(i % 2 == 1), reasons=_BASE_REASONS if i % 2 == 0 else [])
        pushes += _push(hb)
        time.sleep(0.025)
    window = time.monotonic() - started
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)  # итог серии отличается от ушедшего
    time.sleep(_GAP_S)
    _push(hb)

    assert 1 <= pushes <= 3, f"{pushes} внеочередных за {window:.2f} с"
    assert _readys(svc)[-1] is False, _readys(svc)


def test_h2_suppressed_change_is_delivered_after_quiet() -> None:
    """Вторая смена внутри окна подавлена (сообщение не уходит), но не теряется: после затишья итог доставлен."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)
    assert _push(hb) is True
    svc._readiness_snapshot = _snap(ready=True)

    assert _push(hb) is False  # внутри окна
    time.sleep(_GAP_S)
    assert _push(hb) is True  # затишье

    assert _readys(svc) == [True, False, True]


# --------------------------------------------------------------------------- #
# H3: подпись — из реально ушедшей копии (гонка)
# --------------------------------------------------------------------------- #


def test_h3_signature_comes_from_the_sent_copy_not_from_the_compared_snapshot() -> None:
    """Между сравнением и отправкой снимок сменился обратно: ушла копия нового снимка, дубля после неё нет.

    Сравнение видит B (``ready=False``) против ушедшего A, а копию в сообщение берёт отправка — к этому моменту
    снимок уже C (равен A по подписи). Запомни push подпись B, следующий пересчёт увидел бы C != B и послал бы
    дубль уже ушедшего C.
    """
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)  # B: то, что увидит сравнение
    real_collect = hb._collect_workers

    def _collect_then_swap() -> dict:
        svc._readiness_snapshot = _snap(ready=True, at=3.0)  # C: снимок сменился после сравнения
        return real_collect()

    hb._collect_workers = _collect_then_swap  # type: ignore[method-assign]

    assert _push(hb) is True
    assert _readys(svc) == [True, True], "ушла копия нового снимка C"
    time.sleep(_GAP_S)

    assert _push(hb) is False, "дубль уже ушедшего снимка: подпись взята не из ушедшей копии"
    assert len(svc.sent) == 2


# --------------------------------------------------------------------------- #
# H4: дубля после регулярного нет
# --------------------------------------------------------------------------- #


def test_h4_regular_heartbeat_carrying_the_change_suppresses_push() -> None:
    """Регулярный унёс смену (новое ``ready`` и блокирующая причина) -> внеочередной по тому же снимку не нужен."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)
    _regular(hb)  # регулярный несёт новый снимок

    assert [_push(hb) for _ in range(3)] == [False] * 3

    assert _readys(svc) == [True, False]


def test_h4_first_regular_heartbeat_records_the_signature() -> None:
    """Первый регулярный heartbeat со снимком задаёт «ушедшее»: следующая смена относительно него уходит push-ем."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    assert _push(hb) is False  # до первого регулярного сравнивать не с чем
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)

    assert _push(hb) is True

    assert _readys(svc) == [True, False]


# --------------------------------------------------------------------------- #
# H5: сбой отправки не теряет смену
# --------------------------------------------------------------------------- #


def test_h5_failed_push_does_not_mark_change_as_sent() -> None:
    """Отправка упала -> подпись не записана, смена не потеряна: после сбоя и затишья push доносит её."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)
    svc.fail = RuntimeError("сбой")

    assert _push(hb) is False
    svc.fail = None
    time.sleep(_GAP_S)

    assert _push(hb) is True
    assert _readys(svc) == [True, False]


def test_h5_failed_regular_heartbeat_does_not_mark_change_as_sent() -> None:
    """Регулярная отправка упала (исключение наружу) -> подпись не записана: push потом доносит смену."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)
    svc.fail = RuntimeError("сбой регулярной отправки")
    with pytest.raises(RuntimeError):
        _bounded(lambda: hb._send_heartbeat({}))
    svc.fail = None

    assert _push(hb) is True

    assert _readys(svc) == [True, False]


def test_h5b_undelivered_push_does_not_mark_change_as_sent() -> None:
    """``send_message`` вернул ``False`` (недоставка без исключения): push -> ``False``, подпись не записана; после
    восстановления доставки смена повторяется (после антидребезга), а не теряется."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    sig_before = hb._last_sent_sig
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)
    svc.deliver = False

    assert _push(hb) is False
    assert hb._last_sent_sig == sig_before, "недоставленная смена помечена ушедшей"
    svc.deliver = True
    time.sleep(_GAP_S)

    assert _push(hb) is True
    assert _readys(svc) == [True, False]


def test_h5b_undelivery_is_logged_once_per_series_without_values() -> None:
    """Серия недоставок: ERROR один раз (только факт, без значений причин); после доставки серия закрыта."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(ready=False, reasons=[_reason("SECRET_NODE", text="SECRET_TEXT")])
    svc.deliver = False
    results = []
    for _ in range(3):
        results.append(_push(hb))
        time.sleep(_GAP_S)

    assert results == [False] * 3
    assert len(svc.errors) == 1, svc.errors
    assert "SECRET" not in svc.errors[0], svc.errors[0]
    svc.deliver = True
    assert _push(hb) is True
    assert len(svc.errors) == 1


def test_h5b_regular_path_ignores_undelivery_otherwise_unchanged() -> None:
    """Регулярный heartbeat при недоставке не бросает и не логирует ERROR (поведение прежнее), подпись не пишет."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    svc.deliver = False

    _regular(hb)

    assert hb._last_sent_sig is None
    assert svc.errors == []


# --------------------------------------------------------------------------- #
# H6: push не двигает расписание регулярного
# --------------------------------------------------------------------------- #


def test_h6_push_does_not_move_regular_schedule() -> None:
    """Внеочередной heartbeat не трогает метку последней регулярной отправки: срок следующего регулярного прежний."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    hb._last_heartbeat_sent = 123.0  # метка, которую двигает только цикл регулярного такта
    due_before = hb._heartbeat_due(130.0, 0.5)
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)

    assert _push(hb) is True

    assert hb._last_heartbeat_sent == 123.0
    assert hb._heartbeat_due(130.0, 0.5) is due_before


def test_h6_push_leaves_unsent_schedule_unsent() -> None:
    """Регулярный ещё не уходил (метка None): push не создаёт метку и не отменяет «первый тик всегда шлёт»."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    hb._last_heartbeat_sent = None
    svc._readiness_snapshot = _snap(ready=False, reasons=_BASE_REASONS)

    assert _push(hb) is True

    assert hb._last_heartbeat_sent is None
    assert hb._heartbeat_due(1.0, 0.5) is True


# --------------------------------------------------------------------------- #
# H7: битая причина не съедает регулярный heartbeat и не роняет воркер снимка
# --------------------------------------------------------------------------- #

_BROKEN_SNAPSHOTS = [
    pytest.param(_snap(reasons="не список"), id="reasons_is_str"),
    pytest.param(_snap(reasons=None, ready=False), id="reasons_none"),
    pytest.param(_snap(reasons=[1, None, "x", ["y"]]), id="elements_not_dict"),
    pytest.param(_snap(reasons=[{"node": "a"}, {"severity": "failure"}, {}]), id="elements_without_keys"),
    pytest.param(_snap(reasons=[{"node": ["SECRET_NODE"], "severity": "failure"}]), id="unhashable_node"),
    pytest.param(_snap(reasons=[{"node": {"k": 1}, "severity": "check_function"}]), id="dict_node"),
]


@pytest.mark.parametrize("broken", _BROKEN_SNAPSHOTS)
def test_h7_broken_reason_does_not_eat_regular_heartbeat(broken: dict) -> None:
    """Любая форма битых ``reasons``: регулярный heartbeat уходит (liveness не съеден), снимок едет как есть."""
    svc = _Svc(broken)
    hb = _started(svc)

    _regular(hb)

    assert len(svc.sent) == 1
    assert svc.sent[0]["command"] == "heartbeat"
    assert svc.sent[0]["status"] == "unknown" and svc.sent[0]["pid"] > 0
    assert "readiness" in svc.sent[0]


@pytest.mark.parametrize("broken", _BROKEN_SNAPSHOTS)
def test_h7_broken_reason_does_not_raise_in_push_and_never_beats_a_regular_one(broken: dict) -> None:
    """Push по битому снимку не бросает; регулярный после него по-прежнему уходит."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = broken

    result = _push(hb)

    assert isinstance(result, bool)
    _regular(hb)
    assert svc.sent[-1]["command"] == "heartbeat"


def test_h7_signature_failure_is_logged_once_per_exception_type_without_values() -> None:
    """Сбой расчёта подписи: ERROR один раз на тип исключения; в логе только тип, без значений причин."""
    svc = _Svc(_snap(ready=True))
    hb = _started(svc)
    _regular(hb)
    svc._readiness_snapshot = _snap(reasons=[{"node": ["SECRET_NODE"], "severity": "failure", "reason": "SECRET_TEXT"}])

    results = [_push(hb) for _ in range(4)]

    assert results == [False] * 4
    assert len(svc.errors) == 1, svc.errors
    assert "TypeError" in svc.errors[0]
    assert "SECRET" not in svc.errors[0], svc.errors[0]
    assert len(svc.sent) == 1  # внеочередных не было
    # серия закрыта успешным расчётом -> повторный сбой того же типа логируется снова
    svc._readiness_snapshot = _snap(ready=True)
    assert _push(hb) is False
    svc._readiness_snapshot = _snap(reasons=[{"node": ["SECRET_NODE"], "severity": "failure"}])
    assert _push(hb) is False
    assert len(svc.errors) == 2, svc.errors
