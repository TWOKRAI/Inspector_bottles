# -*- coding: utf-8 -*-
"""Task 1.8 (system-run-state) — слепые приёмочные тесты чистой ``run_state.evaluate`` с автоперезапуском.

Контракт (из брифа задачи; interface.py нет — тестируется текст требований):
``evaluate(expected, leaves, alive, now, stale_s, *, running=False, auto_restart=frozenset(), down_since=None,
grace_s=30.0, given_up=frozenset()) -> (ready, reasons)``. Флаг действует только при ``running=True``: процесс из
``auto_restart``, который не жив или без свежего листа, у которого окно ``now - down_since.get(name, now) < grace_s``
не истекло и которого нет в ``given_up``, даёт ОДНУ причину ``out_of_spec`` «перезапуск <процесс>» (source
``liveness``) вместо всех своих причин ``failure``; такая причина ``ready`` не блокирует.

Красный до реализации: ``TypeError`` на новый kwarg (``running`` / ``auto_restart`` / ``down_since`` / ...) — это и
есть отсутствие функциональности. Охранные (зелёные до реализации): вызовы со старой сигнатурой.

Решения тестера (ASSUMPTION; список — в отчёте):
  * текст причины лежит под ключом ``reason`` (как у причин агрегата в ``run_state._reason``), сравнивается как
    точная строка по подстановке из брифа: «перезапуск cam», «cam: перезапуск не завершён за 5.5 с»,
    «cam: супервизор отказался от перезапуска»; число ``grace_s`` везде 5.5 (``{:g}`` и ``str`` дают «5.5»);
  * в истёкшем окне проверяется наличие ровно одной причины-«не завершён за…» и ``ready is False``; будут ли
    при этом сохранены прежние причины процесса — требованиями не определено и не проверяется;
  * ``down_since`` и ``now`` — на одних часах (``now - down_since[name]`` — длительность окна).
"""

from __future__ import annotations

import pytest

from ..process import run_state as run_state_mod

_NOW = 1000.0
_STALE_S = 3.0
_GRACE_S = 5.5  # точно представимо в двоичной дроби: 1000.0 - 5.5 и 1000.0 - 5.25 без ошибки округления


def _leaf(*, ready: bool = True, reasons: list[dict] | None = None, age_s: float = 0.0) -> dict:
    return {"ready": ready, "reasons": list(reasons or []), "paused": False, "at": _NOW - age_s}


def _plugin_failure(node: str, text: str) -> dict:
    return {"node": node, "severity": "failure", "reason": text, "source": "plugin"}


def _evaluate(expected: list[str], leaves: dict, alive: dict, **kwargs) -> tuple[bool, list[dict]]:
    return run_state_mod.evaluate(expected, leaves, alive, _NOW, _STALE_S, **kwargs)


def _flagged(**extra) -> dict:
    """Базовые kwargs «система в работе, ``cam`` с флагом автоперезапуска»."""
    return {"running": True, "auto_restart": frozenset({"cam"}), "grace_s": _GRACE_S, **extra}


# --------------------------------------------------------------------------- #
# 1. Окно не истекло: все причины процесса с флагом -> ОДНА out_of_spec «перезапуск <процесс>»
# --------------------------------------------------------------------------- #

_MODEL_NOT_LOADED = _plugin_failure("cam.detect", "модель не загружена")


@pytest.mark.parametrize(
    ("leaves", "alive", "down_since"),
    [
        pytest.param({}, {"cam": False}, {"cam": _NOW - 2.0}, id="dead-no-leaf"),
        pytest.param({"cam": _leaf(age_s=3600.0)}, {"cam": True}, {"cam": _NOW - 2.0}, id="alive-stale-leaf"),
        pytest.param(
            {"cam": _leaf(ready=False, reasons=[_MODEL_NOT_LOADED])},
            {"cam": True},
            {"cam": _NOW - 2.0},
            id="alive-fresh-leaf-model-not-loaded",
        ),
        pytest.param({}, {"cam": False}, None, id="dead-down_since-omitted"),
        pytest.param({}, {"cam": False}, {}, id="dead-no-entry-in-down_since"),
        pytest.param({}, {"cam": False}, {"cam": _NOW - 5.25}, id="dead-just-inside-window"),
    ],
)
def test_flagged_process_in_window_is_one_out_of_spec_restart_reason(
    leaves: dict, alive: dict, down_since: dict | None
) -> None:
    """Процесс с флагом (``running=True``) не жив / без свежего листа / с failure листа, окно не истекло ->
    ``ready is True`` и РОВНО одна причина ``out_of_spec``/``liveness`` по узлу «перезапуск cam»;
    причина листа «модель не загружена» и «процесс не жив» не просачиваются."""
    ready, reasons = _evaluate(["cam"], leaves, alive, down_since=down_since, **_flagged())

    assert ready is True
    assert len(reasons) == 1, reasons
    assert reasons[0]["node"] == "cam"
    assert reasons[0]["severity"] == "out_of_spec"
    assert reasons[0]["source"] == "liveness"
    assert reasons[0]["reason"] == "перезапуск cam"


# --------------------------------------------------------------------------- #
# 2. Флаг не действует при running=False
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("running_kwargs", [{"running": False}, {}], ids=["running-false", "running-omitted"])
def test_flag_is_inert_when_not_running(running_kwargs: dict) -> None:
    """Вне ``running`` (явное ``False`` и умолчание) мёртвый процесс с флагом — ``failure``/``liveness``
    «процесс не жив»: система не готова (START запрещён), перезапуск не маскируется."""
    ready, reasons = _evaluate(
        ["cam"],
        {},
        {"cam": False},
        auto_restart=frozenset({"cam"}),
        down_since={"cam": _NOW - 2.0},
        grace_s=_GRACE_S,
        **running_kwargs,
    )

    assert ready is False
    assert len(reasons) == 1, reasons
    assert reasons[0]["node"] == "cam"
    assert reasons[0]["severity"] == "failure"
    assert reasons[0]["source"] == "liveness"
    assert reasons[0]["reason"] == "процесс не жив"


# --------------------------------------------------------------------------- #
# 3. failure остаётся блокирующим там, где флаг не покрывает
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("kwargs", "leaves", "alive", "expected_severity_by_node"),
    [
        # охранный (зелёный до реализации): прежняя сигнатура, мёртвый процесс -> failure
        pytest.param({}, {}, {"cam": False}, {"cam": "failure"}, id="guard-old-signature-dead"),
        pytest.param(
            {"auto_restart": frozenset({"cam"})},
            {"cam": _leaf(ready=False, reasons=[_MODEL_NOT_LOADED])},
            {"cam": True},
            {"cam.detect": "failure"},
            id="flagged-healthy-fresh-leaf-no-down_since-stays-failure",
        ),
        pytest.param(
            {"auto_restart": frozenset({"cam"})},
            {"cam": _leaf(), "rec": _leaf()},
            {"cam": True, "rec": False},
            {"rec": "failure"},
            id="unflagged-neighbour-dead-in-running",
        ),
        pytest.param(
            {"auto_restart": frozenset({"cam"}), "down_since": {"cam": _NOW - 1.0}},
            {"rec": _leaf()},
            {"cam": False, "rec": False},
            {"cam": "out_of_spec", "rec": "failure"},
            id="mixed-flagged-restarting-and-unflagged-dead",
        ),
    ],
)
def test_failure_still_blocks_where_flag_does_not_cover(
    kwargs: dict, leaves: dict, alive: dict, expected_severity_by_node: dict[str, str]
) -> None:
    """Процесс с флагом, который жив со свежим листом и без записи в ``down_since``, и процесс БЕЗ флага
    не меняются: их ``failure`` блокируют ``ready`` и в ``running``; флаг соседа чужую причину не гасит."""
    is_guard = not kwargs
    call_kwargs = dict(kwargs) if is_guard else {"running": True, "grace_s": _GRACE_S, **kwargs}
    expected = ["cam", "rec"] if "rec" in alive else ["cam"]

    ready, reasons = _evaluate(expected, leaves, alive, **call_kwargs)

    got = {r["node"]: r["severity"] for r in reasons}
    assert got == expected_severity_by_node, reasons
    assert ready is False


# --------------------------------------------------------------------------- #
# 4. Граница окна: < grace_s — перезапуск идёт; >= grace_s — failure «не завершён за N с»
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("elapsed_s", "in_window"),
    [
        pytest.param(0.0, True, id="just-down"),
        pytest.param(5.25, True, id="a-quarter-second-before-the-edge"),
        pytest.param(5.5, False, id="exactly-grace_s"),
        pytest.param(5.75, False, id="a-quarter-second-after-the-edge"),
        pytest.param(3600.0, False, id="an-hour"),
    ],
)
def test_grace_window_boundary(elapsed_s: float, in_window: bool) -> None:
    """``now - down_since[cam]`` строго меньше ``grace_s`` -> ``out_of_spec`` «перезапуск cam», ``ready``;
    равно ``grace_s`` и больше -> ``failure``/``liveness`` «cam: перезапуск не завершён за 5.5 с», не ``ready``."""
    ready, reasons = _evaluate(["cam"], {}, {"cam": False}, down_since={"cam": _NOW - elapsed_s}, **_flagged())

    if in_window:
        assert ready is True
        assert [(r["severity"], r["reason"]) for r in reasons] == [("out_of_spec", "перезапуск cam")], reasons
    else:
        assert ready is False
        timeouts = [r for r in reasons if r["reason"] == "cam: перезапуск не завершён за 5.5 с"]
        assert len(timeouts) == 1, reasons
        assert timeouts[0]["node"] == "cam"
        assert timeouts[0]["severity"] == "failure"
        assert timeouts[0]["source"] == "liveness"
        assert not any(r["severity"] == "out_of_spec" for r in reasons), reasons


# --------------------------------------------------------------------------- #
# 5. Супервизор отказался — failure в любом окне
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "down_since",
    [{"cam": _NOW - 1.0}, {"cam": _NOW}, {}],
    ids=["inside-window", "just-went-down", "no-entry"],
)
def test_given_up_process_is_failure_in_any_window(down_since: dict) -> None:
    """Процесс с флагом в ``given_up`` -> ``failure``/``liveness`` «cam: супервизор отказался от перезапуска»,
    ``ready is False``, даже пока окно ``grace_s`` не истекло; причины «перезапуск cam» (out_of_spec) нет."""
    ready, reasons = _evaluate(
        ["cam"], {}, {"cam": False}, down_since=down_since, given_up=frozenset({"cam"}), **_flagged()
    )

    assert ready is False
    gave_up = [r for r in reasons if r["reason"] == "cam: супервизор отказался от перезапуска"]
    assert len(gave_up) == 1, reasons
    assert gave_up[0]["node"] == "cam"
    assert gave_up[0]["severity"] == "failure"
    assert gave_up[0]["source"] == "liveness"
    assert not any(r["severity"] == "out_of_spec" for r in reasons), reasons
