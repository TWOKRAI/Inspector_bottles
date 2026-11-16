"""Task 2.2b (system-run-state) — слепая приёмка ``MLInferencePlugin.readiness(ctx)``: «модель не загружена».

Контракт (DESIGN П.7 из ``plans/2026-10-27_system-run-state/tasks/2.2.md``, реализации нет): существующая ветвь
ассетов остаётся ПЕРВОЙ и сохраняет приоритет (``failure`` «ассеты непригодны»). Новая ветвь: если не выбрана модель
(``model == ""``) или ``engine.is_ready`` ложно — одна причина ``out_of_spec`` с текстом
«модель не загружена: кадры идут без распознавания»; исключение при чтении ``is_ready`` (гонка с ``unload()``) —
тот же ``out_of_spec``, а не ``failure`` «readiness() упал»; модель загружена — ``[]``.

Решения тестера (``# ASSUMPTION``, подробности в отчёте):
  * текст новой причины — РОВНО литерал из DESIGN, БЕЗ префикса «ml_inference: » (в отличие от ветви ассетов,
    у которой префикс есть); форма элемента — dict ``{"severity", "reason"}`` без лишних ключей;
  * «модель не выбрана» задаётся конфигом ``model == ""`` при ИСПРАВНЫХ ассетах на диске (веса, sidecar, метки);
  * «движок не готов» — публичный ``InferenceEngine.unload()`` на настоящем движке плагина после ``configure``;
  * «is_ready бросает» — подмена свойства ``InferenceEngine.is_ready`` (через ``monkeypatch``, откат сам);
  * ``ready`` снимка оркестратора для ``out_of_spec`` в DESIGN не уточнён — тест его не проверяет.

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

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.engine import InferenceEngine
from Services.ml_inference.plugin.plugin import MLInferencePlugin

_DEADLINE_S = 10.0
_PROC = "ml_not_loaded_proc"
_SIDECAR = "name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: m1_classes.txt\n"
_NOT_LOADED = [{"severity": "out_of_spec", "reason": "модель не загружена: кадры идут без распознавания"}]
_ASSETS_FAILURE = [{"severity": "failure", "reason": "ml_inference: ассеты модели непригодны: нет весов модели"}]


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


def _configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, model: str = "m1"
) -> tuple[MLInferencePlugin, HealthState, MagicMock]:
    """Плагин с настоящими ``HealthState``/``HealthReporter``, ``configure`` вызван на ``tmp_path``."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    state = HealthState(log=lambda m: None, track=lambda exc, payload=None: None, log_only=False)
    ctx = MagicMock()
    ctx.config = {"model": model, "models_dir": str(tmp_path)}
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.health = HealthReporter(state, source="ml_inference")
    plugin = MLInferencePlugin()
    _call_with_deadline(lambda: plugin.configure(ctx))
    return plugin, state, ctx


def _readiness(plugin: MLInferencePlugin, ctx: MagicMock) -> Any:
    return _call_with_deadline(lambda: plugin.readiness(ctx))


def _raise_attribute_error(_self: object) -> bool:
    """Имитация гонки ``unload()``: ``_backend`` обнулён между проверкой и чтением."""
    raise AttributeError("'NoneType' object has no attribute 'is_loaded'")


def test_no_model_selected_with_healthy_assets_gives_out_of_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель не выбрана (``model == ""``), ассеты исправны -> одна причина ``out_of_spec`` с точным текстом."""
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch, model="")
    assert plugin._engine.is_ready is False  # предпосылка: ничего не загружено
    assert state.snapshot()["status"] == "ok", state.snapshot()  # предпосылка: ассеты исправны, не degraded

    assert _readiness(plugin, ctx) == _NOT_LOADED


def test_model_selected_but_engine_not_ready_gives_out_of_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель выбрана и была загружена, затем ``engine.is_ready`` стал ложным -> то же ``out_of_spec``."""
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    assert plugin._engine.is_ready is True  # предпосылка: до выгрузки модель загружена
    assert _readiness(plugin, ctx) == []  # предпосылка: пока всё в порядке, причин нет

    plugin._engine.unload()

    assert plugin._engine.is_ready is False
    assert state.snapshot()["status"] == "ok", state.snapshot()  # предпосылка: ассеты по-прежнему исправны
    assert _readiness(plugin, ctx) == _NOT_LOADED


def test_degraded_assets_keep_priority_over_not_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ассеты деградированы И модель не загружена -> только прежний ``failure`` (ветвь ассетов первая, не «обе»)."""
    _write_assets(tmp_path, weights=False)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    assert state.snapshot()["status"] == "degraded", state.snapshot()  # предпосылка: ассеты непригодны
    assert plugin._engine.is_ready is False  # предпосылка: модель не загружена

    got = _readiness(plugin, ctx)

    assert got == _ASSETS_FAILURE, got
    assert len(got) == 1, got  # не добавляется второй элемент out_of_spec


def test_loaded_model_has_no_reasons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель выбрана и загружена -> ``[]`` (именно ``list``)."""
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    assert plugin._engine.is_ready is True
    assert plugin._reg.model == "m1"

    got = _readiness(plugin, ctx)

    assert got == []
    assert isinstance(got, list)


def test_is_ready_raising_gives_out_of_spec_not_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``engine.is_ready`` бросает (гонка с ``unload()``) -> то же ``out_of_spec``; ``readiness()`` не бросает."""
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    assert _readiness(plugin, ctx) == []  # предпосылка: без подмены причин нет
    monkeypatch.setattr(InferenceEngine, "is_ready", property(_raise_attribute_error))

    got = _readiness(plugin, ctx)

    assert got == _NOT_LOADED, got
    assert "readiness() упал" not in str(got), got


def test_not_loaded_reason_clears_after_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Выгрузили модель -> ``out_of_spec``; ``cmd_reload_model`` вернул модель -> причина пропала (``[]``).

    Сверх строки REDS 13 (держит, что причина не залипает); при расхождении с реализацией — вопрос лиду.
    """
    _write_assets(tmp_path)
    plugin, state, ctx = _configured(tmp_path, monkeypatch)
    plugin._engine.unload()
    assert _readiness(plugin, ctx) == _NOT_LOADED  # без этого тест ничего не доказывает

    _call_with_deadline(lambda: plugin.cmd_reload_model({}))

    assert plugin._engine.is_ready is True
    assert _readiness(plugin, ctx) == []


def _orchestrated(tmp_path: Path, model: str) -> PluginOrchestrator:
    """Настоящий ``PluginOrchestrator`` с ``MLInferencePlugin`` (форма элемента ``readiness()`` на стыке)."""
    services = MockProcessServices(name=_PROC)
    services._current_process_status = "running"  # процесс объявил готовность
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [
            {
                "plugin_class": "Services.ml_inference.plugin.plugin.MLInferencePlugin",
                "plugin_name": "ml_inference",
                "model": model,
                "models_dir": str(tmp_path),
            }
        ]
    )
    orch.boot()
    assert [p.state.value for p in orch.plugins] == ["running"]  # boot не упал, плагин поднят
    return orch


def test_wired_no_model_reason_reaches_snapshot_as_out_of_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Связка с настоящим оркестратором: модель не выбрана -> в снимке одна причина ``out_of_spec`` (не ``failure``)."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    _write_assets(tmp_path)
    orch = _orchestrated(tmp_path, model="")

    snap = orch.readiness_snapshot()

    assert len(snap["reasons"]) == 1, snap
    reason = snap["reasons"][0]
    assert reason["node"] == f"{_PROC}.ml_inference", reason
    assert reason["severity"] == "out_of_spec", reason
    assert reason["source"] == "readiness", reason
    assert reason["reason"] == "модель не загружена: кадры идут без распознавания", reason


def test_wired_is_ready_raising_is_out_of_spec_not_orchestrator_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Связка: ``is_ready`` бросает -> оркестратор видит ``out_of_spec`` от плагина, а не свой ``failure`` «упал»."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    _write_assets(tmp_path)
    orch = _orchestrated(tmp_path, model="m1")
    assert orch.readiness_snapshot()["reasons"] == []  # предпосылка: загруженная модель — причин нет
    monkeypatch.setattr(InferenceEngine, "is_ready", property(_raise_attribute_error))

    snap = orch.readiness_snapshot()

    assert len(snap["reasons"]) == 1, snap
    reason = snap["reasons"][0]
    assert reason["severity"] == "out_of_spec", reason
    assert reason["source"] == "readiness", reason
    assert reason["reason"] == "модель не загружена: кадры идут без распознавания", reason
