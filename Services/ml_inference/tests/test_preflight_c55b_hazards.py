"""Сторожа разработчика C-55b: инварианты проверки ассетов, которых нет в слепых REDS.

Г1 — `scan()` и `diagnose()` выбирают один и тот же файл весов.
Г2 — своя деградация health снимается, чужая — нет.
Г3 — пустая модель (штатный pass-through) health не портит.
Г4 — обход C-66: деградация из-за ассетов возвращается после закрытия breaker.
Г5 — смена модели из команды против идущего `process` не рвёт ни один поток.

Харнес (`_write_assets`, `_FakeBackend`, `_make_plugin`) скопирован из слепого
`test_preflight_c55b.py` (его не импортируем и не правим). Вызовы, способные повиснуть,
идут в daemon-потоке с дедлайном `join`. Ожидаемые значения — литералы спецификации.
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
from Services.ml_inference.core.registry import ModelRegistry
from Services.ml_inference.plugin.plugin import MLInferencePlugin

_DEADLINE_S = 10.0
_SIDECAR = "name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: m1_classes.txt\n"
_FRAME = np.zeros((8, 8, 3), np.uint8)


def _write_assets(root: Path, *, weights: str | None = "m1.onnx") -> None:
    """Ассеты модели `m1` (sidecar + метки) и, если задано, файл весов."""
    root.mkdir(parents=True, exist_ok=True)
    if weights is not None:
        (root / weights).write_bytes(b"x")
    (root / "m1.yaml").write_text(_SIDECAR, encoding="utf-8")
    (root / "m1_classes.txt").write_text("A\n", encoding="utf-8")


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка с фиксированными выходами (без onnxruntime)."""

    def __init__(self) -> None:
        super().__init__()
        self._outputs = {"logits": np.array([[1.0]], dtype=np.float32)}

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def _make_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: str = "m1",
    clock: Callable[[], float] | None = None,
) -> tuple[MLInferencePlugin, HealthState, list[str], MagicMock]:
    """Плагин с настоящими `HealthState`/`HealthReporter`; `configure` НЕ вызван."""
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _FakeBackend())
    calls: list[str] = []
    state_kwargs: dict[str, Any] = {} if clock is None else {"clock": clock}
    state = HealthState(
        log=lambda m: None,
        track=lambda exc, payload=None: calls.append(type(exc).__name__),
        log_only=False,
        **state_kwargs,
    )
    ctx = MagicMock()
    ctx.config = {"model": model, "models_dir": str(tmp_path)}
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.health = HealthReporter(state, source="ml_inference")
    return MLInferencePlugin(), state, calls, ctx


def _in_daemon(fn: Callable[[], Any], box: dict[str, Any], key: str) -> threading.Thread:
    """Запустить `fn` в daemon-потоке; результат/исключение — в `box[key]`."""

    def _runner() -> None:
        try:
            box[key] = ("ok", fn())
        except BaseException as exc:  # noqa: BLE001 — отдаём в поток теста без потерь
            box[key] = ("exc", exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return thread


def _join_all(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(_DEADLINE_S)
        if thread.is_alive():
            pytest.fail(f"поток не завершился за {_DEADLINE_S} с (взаимная блокировка?)")


# --------------------------------------------------------------------------- #
# Г1: scan ≡ diagnose
# --------------------------------------------------------------------------- #


def test_g1_scan_and_diagnose_pick_the_same_weights(tmp_path: Path) -> None:
    """При `m1.onnx` + `m1.pth` обе дороги выбирают `m1.pth`; `bad.onnx` без sidecar — error."""
    _write_assets(tmp_path)
    (tmp_path / "m1.pth").write_bytes(b"x")
    (tmp_path / "bad.onnx").write_bytes(b"x")
    registry = ModelRegistry(tmp_path)

    scanned = registry.scan()

    assert sorted(scanned) == ["m1"]
    for model_id, spec in scanned.items():
        d = registry.diagnose(model_id)
        assert d.severity == "info", d.message
        assert d.path == spec.weights_path
    assert registry.diagnose("m1").path == tmp_path.resolve() / "m1.pth"
    assert registry.diagnose("bad").severity == "error"


# --------------------------------------------------------------------------- #
# Г2: чужая деградация не снимается
# --------------------------------------------------------------------------- #


def test_g2_foreign_degraded_survives_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ассеты на месте, деградацию поставил кто-то другой → `cmd_reload_model` её не трогает."""
    _write_assets(tmp_path)
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch)
    plugin.configure(ctx)
    state.degraded("чужая причина")

    plugin.cmd_reload_model({})

    snap = state.snapshot()
    assert snap["status"] == "degraded"
    assert snap["degraded_reason"] == "чужая причина"


# --------------------------------------------------------------------------- #
# Г3: пустая модель не деградирует
# --------------------------------------------------------------------------- #


def test_g3_empty_model_is_not_a_degradation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Модель не выбрана — штатный pass-through: статус `ok`, в плоскость ошибок ничего не уходит."""
    plugin, state, calls, ctx = _make_plugin(tmp_path, monkeypatch, model="")

    plugin.configure(ctx)

    assert state.snapshot()["status"] == "ok"
    assert calls == []

    answer = plugin.cmd_set_model({"model": ""})

    assert answer == {"status": "ok", "loaded_model": "", "error": ""}
    assert state.snapshot()["status"] == "ok"
    assert calls == []


# --------------------------------------------------------------------------- #
# Г4: обход C-66
# --------------------------------------------------------------------------- #


def test_g4_asset_degraded_returns_after_breaker_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """5 провалов загрузки открывают breaker; его закрытие стирает причину; `process` ставит её снова."""
    now = [1000.0]
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch, clock=lambda: now[0])

    plugin.configure(ctx)
    for _ in range(4):
        plugin.cmd_reload_model({})
    assert state.breaker_state == "open"

    # open -> half_open -> closed: каждый шаг ждёт свой cooldown (30 с по умолчанию), точка отсчёта
    # сдвигается на первом poll, поэтому часы двигаем перед каждым.
    now[0] += 62.0
    state.poll()
    now[0] += 62.0
    state.poll()
    # Предпосылка обхода (C-66): breaker закрылся и вместе со своей деградацией снял чужую причину.
    assert state.snapshot()["status"] == "ok"

    plugin._last_publish -= 2.0
    plugin.process([{"frame": _FRAME}])

    snap = state.snapshot()
    assert snap["status"] == "degraded"
    assert "m1" in snap["degraded_reason"]


# --------------------------------------------------------------------------- #
# Г5: гонка команды смены модели и process
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("last_model", "status", "loaded"),
    [("m1", "ok", "m1"), ("absent", "degraded", "")],
    ids=["valid-model", "missing-model"],
)
def test_g5_set_model_races_with_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last_model: str, status: str, loaded: str
) -> None:
    """`cmd_set_model` из второго потока во время 50 `process`: без исключений, итог = последняя модель."""
    _write_assets(tmp_path)
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch, model="")
    plugin.configure(ctx)

    box: dict[str, Any] = {}

    def _frames() -> int:
        for _ in range(50):
            plugin._last_publish -= 2.0  # каждый вызов доходит до _publish_state (проверка Б5а под замком)
            plugin.process([{"frame": _FRAME}])
        return 50

    def _commands() -> dict:
        plugin.cmd_set_model({"model": "m1"})
        return plugin.cmd_set_model({"model": last_model})

    _join_all([_in_daemon(_frames, box, "process"), _in_daemon(_commands, box, "command")])

    for key in ("process", "command"):
        kind, value = box[key]
        assert kind == "ok", f"{key}: {value!r}"
    assert state.snapshot()["status"] == status
    assert plugin._reg.loaded_model == loaded


# --------------------------------------------------------------------------- #
# Г6: перекрёст замка — снятие деградации (команда) против _publish_state (конвейер)
# --------------------------------------------------------------------------- #


class _PausingHealth:
    """Обёртка `HealthReporter`: после `set_status("ok")` встаёт на паузу до сигнала теста.

    Пауза оказывается внутри `_clear_asset_degraded`, т.е. под `_engine_lock` потока команды:
    статус уже `ok`, флаг плагина `_asset_degraded` ещё `True`.
    """

    def __init__(self, inner: HealthReporter) -> None:
        self._inner = inner
        self.armed = False
        self.paused = threading.Event()
        self.resume = threading.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def set_status(self, status: Any, reason: str | None = None) -> None:
        self._inner.set_status(status, reason)
        if self.armed and str(getattr(status, "value", status)) == "ok":
            self.paused.set()
            self.resume.wait(_DEADLINE_S)


def test_g6_publish_tick_cannot_reassert_during_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пока команда снимает деградацию, тик `_publish_state` не должен поставить её обратно.

    Без замка (или без его захвата в тике) тик видит статус `ok` и флаг `True` -> ставит
    `degraded`, потом команда гасит флаг: деградация остаётся навсегда, владельца у неё нет.
    """
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch)
    health = _PausingHealth(ctx.health)
    ctx.health = health
    plugin.configure(ctx)  # ассетов нет -> degraded, флаг поднят
    assert state.snapshot()["status"] == "degraded"
    assert plugin._asset_degraded is True

    _write_assets(tmp_path)
    health.armed = True
    box: dict[str, Any] = {}
    command = _in_daemon(lambda: plugin.cmd_reload_model({}), box, "command")
    assert health.paused.wait(_DEADLINE_S), "команда не дошла до set_status('ok')"

    plugin._last_publish -= 2.0
    tick = _in_daemon(lambda: plugin.process([{"no_frame": 1}]), box, "tick")  # без `frame`: сразу в _publish_state
    tick.join(0.6)  # тик либо пропущен (замок занят), либо ждёт замок; в любом случае не ставит degraded
    health.resume.set()
    _join_all([command, tick])

    for key in ("command", "tick"):
        kind, value = box[key]
        assert kind == "ok", f"{key}: {value!r}"
    assert state.snapshot()["status"] == "ok"
    assert plugin._asset_degraded is False


# --------------------------------------------------------------------------- #
# Г7: обход C-66 не понижает failed
# --------------------------------------------------------------------------- #


def test_g7_publish_tick_keeps_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Статус `failed` выставил кто-то другой -> тик с поднятым флагом ассетов его не понижает."""
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch)
    plugin.configure(ctx)  # ассетов нет -> флаг поднят
    assert plugin._asset_degraded is True
    state.failed("fatal elsewhere")

    plugin._last_publish -= 2.0
    plugin.process([{"frame": _FRAME}])

    snap = state.snapshot()
    assert snap["status"] == "failed"
    assert snap["degraded_reason"] == "fatal elsewhere"


# --------------------------------------------------------------------------- #
# Г8: файл меток не UTF-8
# --------------------------------------------------------------------------- #


def test_g8_non_utf8_labels_is_error_without_exception_text(tmp_path: Path) -> None:
    """Файл меток из sidecar с не-UTF-8 байтами -> error, path = файл меток, в тексте только имя типа."""
    _write_assets(tmp_path)
    (tmp_path / "m1_classes.txt").write_bytes(b"\xff\xfe\x00bad")

    d = ModelRegistry(tmp_path).diagnose("m1")

    assert d.severity == "error"
    assert d.path == tmp_path.resolve() / "m1_classes.txt"
    assert d.message.endswith("UnicodeDecodeError")
    assert "codec" not in d.message


# --------------------------------------------------------------------------- #
# Г9: тик _publish_state не ждёт загрузку модели
# --------------------------------------------------------------------------- #


class _BlockingBackend(_FakeBackend):
    """Backend, чей `load` встаёт на `threading.Event` (не sleep) до сигнала теста."""

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self._entered = entered
        self._release = release

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._entered.set()
        self._release.wait(_DEADLINE_S)
        self._spec = spec


def test_g9_publish_tick_does_not_wait_for_model_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Команда держит `_engine_lock` на загрузке модели -> `process` без кадра возвращается сразу."""
    _write_assets(tmp_path)
    plugin, _state, _calls, ctx = _make_plugin(tmp_path, monkeypatch, model="")
    plugin.configure(ctx)
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr("Services.ml_inference.engine._make_backend", lambda _t: _BlockingBackend(entered, release))

    box: dict[str, Any] = {}
    command = _in_daemon(lambda: plugin.cmd_set_model({"model": "m1"}), box, "command")
    tick: threading.Thread | None = None
    try:
        assert entered.wait(_DEADLINE_S), "загрузка модели не началась"
        plugin._last_publish -= 2.0
        tick = _in_daemon(lambda: plugin.process([{"no_frame": 1}]), box, "tick")
        tick.join(1.0)
        tick_done = not tick.is_alive()
        load_still_blocked = not release.is_set()
    finally:
        release.set()
    _join_all([command] + ([tick] if tick is not None else []))

    assert load_still_blocked
    assert tick_done, "process ждал замок на время загрузки модели"
    for key in ("command", "tick"):
        kind, value = box[key]
        assert kind == "ok", f"{key}: {value!r}"
