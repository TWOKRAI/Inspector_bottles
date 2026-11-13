# -*- coding: utf-8 -*-
"""Task 1.7c (system-run-state) — слепые приёмочные тесты чистой ``run_state.evaluate`` с ``restarting``.

Контракт (из брифа; interface.py нет): ``evaluate(EvalInput(expected, leaves, alive, now, stale_s, running=False,
auto_restart=..., down_since=..., grace_s=30.0, given_up=..., restarting: frozenset[str] = frozenset())``. Процесс из
``restarting`` (и из ``expected``) даёт РОВНО ОДНУ причину ``failure`` «<процесс>: перезапускается супервизором»
(``node`` = процесс, ``source`` = ``liveness``) независимо от листа и от того, жив ли процесс; ``ready`` False.
Вызовы без ``restarting`` не меняются.

Красный до реализации: ``TypeError`` на новый kwarg ``restarting`` — это и есть отсутствие функциональности.
Охранный (зелёный до реализации): вызовы со старой сигнатурой.

Решения тестера (ASSUMPTION; список — в отчёте):
  * текст причины лежит под ключом ``reason`` (как у причин агрегата в ``run_state._reason``); сравнивается кортеж
    ``(node, severity, source, reason)``, лишние ключи словаря причины не мешают;
  * пересечение ``restarting`` с ``auto_restart`` при ``running=True`` требованиями не определено — не проверяется;
  * процесс из ``restarting``, которого нет в ``expected``, причину не даёт (``restarting`` действует «в ``expected``»).
"""

from __future__ import annotations

import pytest

from ..process import run_state as run_state_mod

_NOW = 1000.0
_STALE_S = 3.0
_CAM_RESTARTING = ("cam", "failure", "liveness", "cam: перезапускается супервизором")


def _leaf(*, ready: bool = True, reasons: list[dict] | None = None, age_s: float = 0.0) -> dict:
    return {"ready": ready, "reasons": list(reasons or []), "paused": False, "at": _NOW - age_s}


def _shape(reasons: list[dict]) -> list[tuple[str, str, str, str]]:
    return [(r["node"], r["severity"], r["source"], r["reason"]) for r in reasons]


@pytest.mark.parametrize(
    ("expected", "leaves", "alive", "restarting", "running", "want_reasons"),
    [
        pytest.param(
            ["cam"], {"cam": _leaf()}, {"cam": True}, {"cam"}, False, [_CAM_RESTARTING], id="fresh-leaf-alive"
        ),
        pytest.param(
            ["cam"],
            {"cam": _leaf(age_s=100.0)},
            {"cam": True},
            {"cam"},
            False,
            [_CAM_RESTARTING],
            id="stale-leaf-alive",
        ),
        pytest.param(["cam"], {}, {"cam": False}, {"cam"}, False, [_CAM_RESTARTING], id="no-leaf-dead"),
        pytest.param(
            ["cam"],
            {
                "cam": _leaf(
                    ready=False, reasons=[{"node": "cam.x", "severity": "failure", "reason": "z", "source": "plugin"}]
                )
            },
            {"cam": True},
            {"cam"},
            False,
            [_CAM_RESTARTING],
            id="leaf-with-own-failure-collapses-to-one",
        ),
        pytest.param(["cam"], {"cam": _leaf()}, {"cam": True}, {"cam"}, True, [_CAM_RESTARTING], id="running-true"),
        pytest.param(
            ["aux", "cam"],
            {"aux": _leaf(), "cam": _leaf()},
            {"aux": True, "cam": True},
            {"cam"},
            False,
            [_CAM_RESTARTING],
            id="neighbour-healthy-no-reason",
        ),
        # охранный в форме нового kwarg: имя вне expected причины не даёт
        pytest.param(
            ["cam"], {"cam": _leaf()}, {"cam": True}, {"ghost"}, False, [], id="restarting-name-not-in-expected"
        ),
    ],
)
def test_restarting_process_gives_exactly_one_failure(
    expected: list[str],
    leaves: dict,
    alive: dict,
    restarting: set[str],
    running: bool,
    want_reasons: list[tuple],
) -> None:
    """Процесс из ``restarting`` -> одна ``failure``/``liveness`` «cam: перезапускается супервизором» при любом листе и
    любой живости; здоровый сосед причин не даёт; ``ready`` False (True, если причин нет)."""
    ready, reasons = run_state_mod.evaluate(
        run_state_mod.EvalInput(
            expected, leaves, alive, _NOW, _STALE_S, running=running, restarting=frozenset(restarting)
        )
    )

    assert _shape(reasons) == want_reasons, reasons
    assert ready is (want_reasons == [])


@pytest.mark.parametrize(
    ("leaves", "alive", "want_ready", "want_reasons"),
    [
        pytest.param({"cam": _leaf()}, {"cam": True}, True, [], id="healthy"),
        pytest.param(
            {"cam": _leaf()}, {"cam": False}, False, [("cam", "failure", "liveness", "процесс не жив")], id="dead"
        ),
        pytest.param(
            {}, {"cam": True}, False, [("cam", "failure", "liveness", "нет отчёта о готовности")], id="no-leaf"
        ),
    ],
)
def test_guard_calls_without_restarting_unchanged(
    leaves: dict, alive: dict, want_ready: bool, want_reasons: list[tuple]
) -> None:
    """Охранный (зелёный до реализации): вызов без ``restarting`` даёт прежние литералы."""
    ready, reasons = run_state_mod.evaluate(run_state_mod.EvalInput(["cam"], leaves, alive, _NOW, _STALE_S))

    assert ready is want_ready
    assert _shape(reasons) == want_reasons, reasons
