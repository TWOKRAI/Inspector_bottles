"""Hazard-тесты DS-1 Task 2.1: происхождение предсказания (`angle_symmetry`, `model_id`).

`model_id` в item — id модели, которая РЕАЛЬНО дала `predictions`, а не значение регистра `model`
на момент сборки item: команда `set_model` меняет регистр на другом потоке до того, как возьмёт
`_engine_lock`. Сценарии (детерминированно, на threading.Event, без sleep-синхронизации):

- R1: predict идёт на modelX, на другом потоке `set_model(<другая | ghost | "">)` уже поменял регистр;
- R2: кадр прошёл проверку `is_ready`, ждёт лок, пока модель выгружают → `predictions == []`, `model_id` нет;
- R4: регистр поменяли без перезагрузки (без потоков) → в item модель движка, а не регистра.

Плюс плагин-уровневый тест `angle_symmetry` (между движком и выходом плагина лежит копирование
`_mark_below_threshold`) и явный `full` в карте симметрий.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.engine import InferenceEngine
from Services.ml_inference.plugin.plugin import MLInferencePlugin
from Services.ml_inference.tests.conftest import _build_dummy_onnx

_DEADLINE_S = 10.0


class _FakeBackend(BaseInferenceBackend):
    def __init__(self, outputs: dict[str, np.ndarray]) -> None:
        super().__init__()
        self._outputs = outputs

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def _make_ctx(config: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config
    ctx.registers = None
    ctx.state_proxy = None
    return ctx


def _frame() -> np.ndarray:
    return np.zeros((120, 160, 3), dtype=np.uint8)


def _run_in_thread(fn: Callable[[], object]) -> tuple[threading.Thread, list[object]]:
    """Daemon-поток: результат (или исключение) в списке, join — с дедлайном в тесте."""
    box: list[object] = []

    def _target() -> None:
        try:
            box.append(fn())
        except BaseException as exc:  # noqa: BLE001 — отдать в тест, не потерять в потоке
            box.append(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread, box


def _join(thread: threading.Thread) -> None:
    thread.join(_DEADLINE_S)
    assert not thread.is_alive(), "поток завис (дедлок?)"


@pytest.fixture
def two_models_dir(dummy_models_dir: Path) -> Path:
    """Две реальные dummy-модели modelX / modelY (ключ каталога = stem файла)."""
    sidecar = (dummy_models_dir / "dummy.yaml").read_text(encoding="utf-8")
    for name in ("modelX", "modelY"):
        _build_dummy_onnx(dummy_models_dir / f"{name}.onnx")
        (dummy_models_dir / f"{name}.yaml").write_text(sidecar.replace("dummy.onnx", f"{name}.onnx"), encoding="utf-8")
    return dummy_models_dir


@pytest.fixture
def plugin_x(two_models_dir: Path) -> MLInferencePlugin:
    """Плагин с загруженной через `load_model` моделью modelX."""
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(two_models_dir), "model": "modelX", "confidence_threshold": 0.0}))
    assert plugin._engine.is_ready
    assert plugin._engine.current_model_id == "modelX"
    return plugin


class _HookLock:
    """Обёртка `_engine_lock` с хуками: `on_enter` — поток дошёл до ожидания лока;
    `on_first_exit` — после ПЕРВОГО освобождения лока (окно «вышли из лока, но ещё не собрали item»)."""

    def __init__(
        self,
        inner: threading.Lock,
        on_enter: Callable[[], None] | None = None,
        on_first_exit: Callable[[], None] | None = None,
    ) -> None:
        self._inner = inner
        self._on_enter = on_enter
        self._on_first_exit = on_first_exit

    def __enter__(self) -> None:
        if self._on_enter is not None:
            self._on_enter()
        self._inner.acquire()

    def __exit__(self, *_exc: object) -> None:
        self._inner.release()
        hook, self._on_first_exit = self._on_first_exit, None
        if hook is not None:
            hook()


# --- R1: set_model на другом потоке во время predict -------------------------


@pytest.mark.parametrize("target", ["modelY", "ghost", ""])
def test_model_id_is_model_that_ran_while_set_model_races(plugin_x: MLInferencePlugin, target: str) -> None:
    plugin = plugin_x
    entered, release, reg_changed, switched = (threading.Event() for _ in range(4))

    backend = plugin._engine._backend
    real_infer = backend.infer

    def _blocking_infer(tensor: np.ndarray) -> dict[str, np.ndarray]:
        entered.set()  # predict держит _engine_lock и стоит внутри инференса modelX
        assert release.wait(_DEADLINE_S)
        return real_infer(tensor)

    backend.infer = _blocking_infer

    real_load = plugin._load_selected_model

    def _load_after_register_set() -> None:
        reg_changed.set()  # cmd_set_model уже записал регистр, дальше блокируется на локе
        try:
            real_load()
        finally:
            switched.set()  # set_model довёл смену модели до конца

    plugin._load_selected_model = _load_after_register_set
    # после выхода predict-потока из лока set_model успевает полностью отработать ДО сборки item:
    # чтение id после лока увидело бы уже новую модель (или None)
    plugin._engine_lock = _HookLock(plugin._engine_lock, on_first_exit=lambda: switched.wait(_DEADLINE_S))

    predict_thread, predict_box = _run_in_thread(lambda: plugin.process([{"frame": _frame()}]))
    assert entered.wait(_DEADLINE_S)
    switch_thread, switch_box = _run_in_thread(lambda: plugin.cmd_set_model({"model": target}))
    assert reg_changed.wait(_DEADLINE_S)
    assert plugin._reg.model == target  # предусловие: регистр уже НЕ modelX, а predict ещё идёт

    release.set()
    _join(predict_thread)
    _join(switch_thread)

    out = predict_box[0]
    assert not isinstance(out, BaseException), out
    assert len(out[0]["predictions"]) == 3  # predict отработал на modelX
    assert out[0]["model_id"] == "modelX"
    assert not isinstance(switch_box[0], BaseException), switch_box[0]


# --- R2: модель выгружена, пока кадр ждал лок --------------------------------


def test_no_model_id_when_model_unloaded_while_frame_waits_for_lock(plugin_x: MLInferencePlugin) -> None:
    plugin = plugin_x
    real_lock = plugin._engine_lock
    waiting = threading.Event()
    plugin._engine_lock = _HookLock(real_lock, on_enter=waiting.set)

    real_lock.acquire()  # «set_model» держит лок: кадр, прошедший is_ready, встанет на нём
    try:
        predict_thread, predict_box = _run_in_thread(lambda: plugin.process([{"frame": _frame()}]))
        assert waiting.wait(_DEADLINE_S)
        # то, что делает set_model("ghost") под локом: регистр + выгрузка модели
        plugin._reg.model = "ghost"
        plugin._engine.unload()
    finally:
        real_lock.release()
    _join(predict_thread)

    out = predict_box[0]
    assert not isinstance(out, BaseException), out
    assert out[0]["predictions"] == []
    assert "model_id" not in out[0]


# --- R4: регистр изменён без перезагрузки ------------------------------------


def test_model_id_follows_engine_not_register(plugin_x: MLInferencePlugin) -> None:
    plugin_x._reg.model = "modelY"  # без set_model/reload: движок всё ещё держит modelX

    out = plugin_x.process([{"frame": _frame()}])

    assert len(out[0]["predictions"]) == 3
    assert out[0]["model_id"] == "modelX"


def test_model_id_changes_after_real_switch(plugin_x: MLInferencePlugin) -> None:
    """Контроль: после настоящего set_model id следует за новой моделью (id не «залип»)."""
    assert plugin_x.cmd_set_model({"model": "modelY"})["loaded_model"]

    out = plugin_x.process([{"frame": _frame()}])

    assert out[0]["model_id"] == "modelY"


# --- angle_symmetry -----------------------------------------------------------


def _angle_engine(tmp_path: Path, symmetry: dict[str, str], logits: list[float]) -> InferenceEngine:
    """Движок с fake-backend; id выставлен так, как это делает load_model."""
    spec = ModelSpec(
        name="t",
        weights_path=tmp_path / "m.onnx",
        input_size=(32, 32),
        angle_head=True,
        symmetry=symmetry,
    )
    outputs = {
        "logits": np.array([logits], dtype=np.float32),
        "angle": np.array([[0.0, 1.0]], dtype=np.float32),
    }
    engine = InferenceEngine(str(tmp_path))
    backend = _FakeBackend(outputs)
    backend.load(spec)
    engine._backend, engine._spec, engine._labels = backend, spec, ["Ж", "О", "Щ"]
    engine._model_id = "fake_model"
    return engine


def test_explicit_full_in_symmetry_map_gives_full(tmp_path: Path) -> None:
    """`full` задан в карте явно (не fallback) → у топ-1 `angle_symmetry == "full"`, угол невалиден."""
    engine = _angle_engine(tmp_path, {"Ж": "none", "О": "180", "Щ": "full"}, [0.0, 0.0, 9.0])

    top1 = engine.predict(np.zeros((40, 40, 3), dtype=np.uint8))[0]

    assert top1["label"] == "Щ"
    assert top1["angle_symmetry"] == "full"
    assert top1["angle_valid"] is False


def test_plugin_output_carries_angle_symmetry_and_model_id(tmp_path: Path) -> None:
    plugin = MLInferencePlugin()
    plugin.configure(_make_ctx({"models_dir": str(tmp_path), "model": "fake_model", "confidence_threshold": 0.0}))
    plugin._engine = _angle_engine(tmp_path, {"Ж": "none", "О": "180"}, [0.0, 9.0, 0.0])  # top-1 = «О»
    assert plugin._engine.is_ready

    out = plugin.process([{"frame": np.zeros((40, 40, 3), dtype=np.uint8)}])

    top1 = out[0]["predictions"][0]
    assert top1["label"] == "О"
    assert top1["angle_symmetry"] == "180"
    assert out[0]["model_id"] == "fake_model"
    assert "angle_symmetry" not in out[0]["predictions"][1]  # только у топ-1
