"""Task 1.6 (system-run-state) — слепая приёмка ``MLInferencePlugin.readiness(ctx)`` при непригодных ассетах.

Требование (из брифа, реализации нет): при непригодных ассетах модели (``_fail_assets``, health ``degraded``)
``readiness(ctx)`` возвращает ровно одну причину ``severity="failure"``, текст = тот же, что плагин кладёт в health
``degraded`` (начинается с «ml_inference: »). При пригодной модели или после исправления ассетов
(повторная загрузка -> ``_clear_asset_degraded``) — пусто. ``readiness()`` не ждёт ``_engine_lock``: пока другой поток
держит замок (долгая загрузка), вызов возвращается быстро (< 1 с).

Решения тестера (``# ASSUMPTION``, подробности в отчёте):
  * форма элемента — контракт ``ProcessModulePlugin.readiness`` из ``plugins/base.py``: ``{"severity", "reason"}``;
    для «пар (severity, reason)» из брифа ``_pairs`` принимает и кортеж, и dict, так что тест не зависит от формы;
  * «тот же текст, что в health» = ``HealthState.snapshot()["degraded_reason"]`` настоящего ``HealthState``;
  * вызов ``readiness`` ДО ``configure`` не проверяется.

Ожидаемые значения — литералы. Блокирующие вызовы идут в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.plugin.plugin import MLInferencePlugin

_DEADLINE_S = 10.0
_FAST_S = 1.0
_SIDECAR = "name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: m1_classes.txt\n"


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка без onnxruntime."""

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return {"logits": np.array([[1.0]], dtype=np.float32)}

    def unload(self) -> None:
        self._spec = None


def _write_assets(root: Path, *, weights: bool = True) -> None:
    """Ассеты модели ``m1``: sidecar + метки всегда, веса — по флагу."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "m1.yaml").write_text(_SIDECAR, encoding="utf-8")
    (root / "m1_classes.txt").write_text("A\n", encoding="utf-8")
    if weights:
        (root / "m1.onnx").write_bytes(b"x")


def _call_with_deadline[T](fn: Callable[[], T], deadline_s: float = _DEADLINE_S) -> T:
    """Вызвать ``fn`` в daemon-потоке; не вернулся за ``deadline_s`` -> падение теста, а не зависание."""
    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["exc"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(deadline_s)
    if thread.is_alive():
        pytest.fail(f"вызов не вернулся за {deadline_s} с (завис / ждёт замок)")
    if "exc" in box:
        raise box["exc"]
    return box["value"]


def _configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[MLInferencePlugin, HealthState, MagicMock]:
    """Плагин с настоящими ``HealthState``/``HealthReporter``, ``configure`` вызван на ``tmp_path``."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    state = HealthState(log=lambda m: None, track=lambda exc, payload=None: None, log_only=False)
    ctx = MagicMock()
    ctx.config = {"model": "m1", "models_dir": str(tmp_path)}
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.health = HealthReporter(state, source="ml_inference")
    plugin = MLInferencePlugin()
    _call_with_deadline(lambda: plugin.configure(ctx))
    return plugin, state, ctx


def _pairs(raw: Any) -> list[tuple[str, str]]:
    """Причины ``readiness()`` как пары (severity, reason): принимает dict-элемент контракта и кортеж."""
    assert isinstance(raw, list), raw
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append((item["severity"], item["reason"]))
        else:
            out.append((item[0], item[1]))
    return out


def test_missing_weights_gives_single_failure_with_health_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет весов: одна причина ``failure``, текст = ``degraded_reason`` health, с префиксом и id модели."""
    _write_assets(tmp_path, weights=False)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    snap = state.snapshot()
    assert snap["status"] == "degraded", snap  # предпосылка: ассеты действительно непригодны

    got = _pairs(_call_with_deadline(lambda: plugin.readiness(ctx)))

    assert len(got) == 1, got
    severity, reason = got[0]
    assert severity == "failure", got
    assert reason == snap["degraded_reason"], (reason, snap)
    assert reason.startswith("ml_inference: "), reason
    assert "m1" in reason, reason


def test_healthy_model_has_no_reasons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Охранный (зелёный и до реализации): пригодная модель -> ``readiness()`` пуст, именно ``list``."""
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    assert state.snapshot()["status"] == "ok"
    assert plugin._reg.loaded_model == "m1"

    got = _call_with_deadline(lambda: plugin.readiness(ctx))

    assert got == []
    assert isinstance(got, list)


def test_reason_clears_after_assets_fixed_and_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Причина есть при отсутствии весов и пропадает после появления ассетов + ``cmd_reload_model``."""
    plugin, state, ctx = _configured(tmp_path, monkeypatch)  # пустой каталог: весов нет
    before = _pairs(_call_with_deadline(lambda: plugin.readiness(ctx)))
    assert [s for s, _ in before] == ["failure"], before  # без этого тест ничего не доказывает

    _write_assets(tmp_path)
    _call_with_deadline(lambda: plugin.cmd_reload_model({}))

    assert state.snapshot()["status"] == "ok"
    assert _call_with_deadline(lambda: plugin.readiness(ctx)) == []


def test_readiness_does_not_wait_for_engine_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пока другой поток держит ``_engine_lock``, ``readiness()`` отвечает за < 1 с с той же причиной."""
    _write_assets(tmp_path, weights=False)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    expected_text = state.snapshot()["degraded_reason"]

    acquired = threading.Event()
    release = threading.Event()

    def _hold_lock() -> None:
        with plugin._engine_lock:
            acquired.set()
            release.wait(30.0)

    holder = threading.Thread(target=_hold_lock, daemon=True)
    holder.start()
    try:
        assert acquired.wait(5.0), "держатель не взял _engine_lock"
        got = _pairs(_call_with_deadline(lambda: plugin.readiness(ctx), deadline_s=_FAST_S))
    finally:
        release.set()
        holder.join(5.0)

    assert got == [("failure", expected_text)], got
